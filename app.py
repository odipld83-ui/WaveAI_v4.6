#!/usr/bin/env python3
# -*- coding: utf-8 -*-\n
"""
WaveAI - Système d'Agents IA (Google Gemini ONLY)
Version: GEMINI ONLY - Stabilité maximale et corrections finales PostgreSQL
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests

# -- DATABASE IMPORTS AND CONFIGURATION (POSTGRESQL VERSION) --
import psycopg2
from urllib.parse import urlparse

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Lit la clé secrète depuis l'environnement (SECRET_KEY)
app.secret_key = os.environ.get('SECRET_KEY', 'waveai-secret-key-2024')

# Configuration de la base de données (PostgreSQL)
DATABASE_URL = os.environ.get('DATABASE_URL')

# Configuration de l'API Gemini
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}"

def get_db_connection():
    """Crée et retourne une connexion à la base de données PostgreSQL."""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL non défini.")
    
    # Parse l'URL de la base de données (nécessaire pour Render/Heroku)
    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port
    
    conn = psycopg2.connect(
        database=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )
    return conn

class APIManager:
    """Gestionnaire simplifié pour la clé Gemini et la DB (PostgreSQL)"""
    
    def __init__(self):
        # L'initialisation est appelée dans le __main__
        pass 
        
    def init_database(self):
        """
        Initialise la base de données PostgreSQL (tables) et effectue la migration.
        Assure que la colonne 'created_at' est ajoutée si elle manque.
        """
        if not DATABASE_URL:
            logger.error("Initialisation DB échouée: DATABASE_URL non défini.")
            return

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Création de la table api_keys (avec le schéma complet)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        provider TEXT PRIMARY KEY,
                        api_key TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        last_tested TIMESTAMP,
                        test_status TEXT DEFAULT 'untested',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # 2. CORRECTION DE MIGRATION : Ajout de la colonne manquante si la table existait
                try:
                    cursor.execute("SELECT created_at FROM api_keys LIMIT 0")
                except psycopg2.ProgrammingError as e:
                    if 'created_at' in str(e):
                        conn.rollback() # Annule la transaction ratée
                        cursor.execute("ALTER TABLE api_keys ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                        logger.info("Migration DB: Colonne 'created_at' ajoutée à la table api_keys.")
                    else:
                        raise 

                # 3. Création de la table scheduled_tasks
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_tasks (
                        id SERIAL PRIMARY KEY,
                        task_type TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        body TEXT NOT NULL,
                        scheduled_date TIMESTAMP NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                logger.info("Base de données PostgreSQL initialisée/mise à jour avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation/mise à jour de la base de données PostgreSQL: {e}")
            raise 
    
    def save_api_key(self, provider, api_key):
        """
        Sauvegarde la clé API Gemini. Requête simplifiée pour la robustesse.
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # On retire 'created_at' de l'INSERT car la DB gère la valeur par défaut
                cursor.execute(
                    """
                    INSERT INTO api_keys (provider, api_key, is_active)
                    VALUES (%s, %s, TRUE)
                    ON CONFLICT (provider) DO UPDATE
                    SET api_key = EXCLUDED.api_key, 
                        is_active = EXCLUDED.is_active;
                    """, 
                    (provider, api_key)
                )
                
                conn.commit()
                logger.info(f"Clé API sauvegardée pour {provider}")
                return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la clé {provider}: {e}")
            return False
    
    def get_api_key(self, provider='gemini'):
        """Récupère la clé API Gemini."""
        if provider == 'gemini':
            env_key = os.getenv('GEMINI_API_KEY')
            if env_key:
                return env_key
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT api_key FROM api_keys 
                    WHERE provider = %s AND is_active = TRUE
                ''', (provider,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la clé {provider}: {e}")
            return None
    
    def get_api_status(self, provider='gemini'):
        """Récupère le statut de l'API Gemini"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT api_key, test_status, last_tested, created_at 
                    FROM api_keys 
                    WHERE provider = %s
                ''', (provider,))
                result = cursor.fetchone()
                
            key_from_db = result[0] if result else None
            status = result[1] if result else 'missing'
            last_tested = result[2] if result else None
            created_at = result[3] if result else None

            key_from_env = os.getenv('GEMINI_API_KEY')
            
            is_configured = (key_from_db is not None) or (key_from_env is not None)
            key_to_display = key_from_env if key_from_env else key_from_db

            return {
                'configured': is_configured,
                'key_preview': key_to_display[:8] + '...' if key_to_display and len(key_to_display) > 8 else (key_to_display if key_to_display else 'N/A'),
                'status': status,
                'last_tested': last_tested.isoformat() if last_tested else None,
                'created_at': created_at.isoformat() if created_at else None,
                'model': GEMINI_MODEL
            }
            
        except Exception as e:
            logger.error(f"Erreur statut APIs: {e}")
            return {
                'configured': False,
                'key_preview': 'N/A',
                'status': 'error',
                'last_tested': None,
                'model': GEMINI_MODEL
            }

    def log_test_result(self, provider, status):
        """Mettre à jour le statut du test"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE api_keys 
                    SET test_status = %s, last_tested = CURRENT_TIMESTAMP
                    WHERE provider = %s
                ''', (status, provider))
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du test {provider}: {e}")

    def test_gemini_api(self):
        """Test simple de l'API Gemini"""
        api_key = self.get_api_key('gemini')
        
        if not api_key:
            self.log_test_result('gemini', 'missing')
            return False, "Clé API Gemini introuvable.", None
        
        try:
            logger.info(f"Test du modèle Gemini: {GEMINI_MODEL}")
            test_prompt = "Dis 'OK' et rien d'autre."
            url = GEMINI_API_URL.format(GEMINI_MODEL, api_key)
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": test_prompt}]}
                ],
                "generationConfig": { 
                    "maxOutputTokens": 10,
                    "temperature": 0.0
                }
            }
            
            response = requests.post(url, json=payload, timeout=20)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    content = result['candidates'][0]['content']
                    if 'parts' in content and content['parts']:
                        text = content['parts'][0].get('text', '').strip().upper()
                        if 'OK' in text or 'OK' == text:
                            self.log_test_result('gemini', 'success')
                            return True, "API Gemini fonctionnelle.", None
                
                self.log_test_result('gemini', 'error')
                return False, f"API Gemini : Réponse inattendue. {response.text}", None

            else:
                error_msg = response.json().get('error', {}).get('message', 'Erreur HTTP inconnue')
                logger.error(f"Erreur API Gemini ({response.status_code}): {error_msg}")
                self.log_test_result('gemini', 'error')
                return False, f"Erreur API Gemini ({response.status_code}): {error_msg}", None
            
        except Exception as e:
            logger.error(f"Erreur lors du test Gemini: {e}")
            self.log_test_result('gemini', 'error')
            return False, f"Erreur non gérée lors du test Gemini: {str(e)}", None

# --- DÉFINITION DE LA CLASSE AIAgent (DOIT ÊTRE AVANT L'INSTANCE AGENTS) ---
class AIAgent:
    """Agent IA utilisant l'API Gemini"""
    
    def __init__(self, name, role, personality):
        self.name = name
        self.role = role
        self.personality = personality
    
    def generate_response(self, message):
        """Génère une réponse en utilisant Gemini"""
        
        api_key = api_manager.get_api_key('gemini')
        if not api_key:
            return self._fallback_response()
        
        system_instruction = f"""Tu es {self.name}, {self.role}.
Personnalité: {self.personality}
Réponds de manière naturelle et personnalisée selon ton rôle.
Garde tes réponses concises et utiles (maximum 150 mots)."""
        
        try:
            url = GEMINI_API_URL.format(GEMINI_MODEL, api_key)
            
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": system_instruction}]},
                    {"role": "user", "parts": [{"text": message}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": 250,
                    "temperature": 0.7
                }
            }
            
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    generated_text = result['candidates'][0]['content']['parts'][0]['text']
                    return {
                        'agent': self.name,
                        'response': generated_text.strip(),
                        'provider': f'Google Gemini ({GEMINI_MODEL.split("-")[-1]})',
                        'success': True
                    }
            
            error_msg = response.json().get('error', {}).get('message', f'Erreur Gemini non détaillée: {response.status_code}')
            logger.error(f"Erreur Gemini pour {self.name}: {error_msg}")
            
            return self._fallback_response(error_msg=error_msg)
            
        except Exception as e:
            logger.error(f"Erreur non gérée lors de l'appel Gemini: {e}")
            return self._fallback_response(error_msg=str(e))

    def _fallback_response(self, error_msg=None):
        """Réponse de fallback lorsque l'API Gemini n'est pas disponible ou échoue"""
        fallback_responses = {
            'kai': "Je suis Kai, votre assistant IA. Pour que je puisse vous aider, veuillez configurer la clé API Gemini dans les paramètres.",
            'alex': "Je suis Alex. Mon accès à l'IA est désactivé. Veuillez configurer l'API Gemini pour débloquer mes conseils de productivité.",
            'lina': "Je suis Lina. Je ne peux pas analyser votre situation sans l'API Gemini. Configurez la clé pour commencer à travailler !",
            'marco': "Je suis Marco. Je suis en mode démo. Configurer la clé Gemini me permettra de générer des idées créatives.",
            'sofia': "Je suis Sofia. Mon planning est en attente. Veuillez configurer l'API Gemini pour optimiser votre organisation."
        }
        
        reason = "Clé API Gemini non configurée."
        if error_msg:
            reason = f"Erreur API: {error_msg}"
        
        return {
            'agent': self.name,
            'response': f"{fallback_responses.get(self.name.lower(), fallback_responses['kai'])} ({reason})",
            'provider': 'Mode Démo (Gemini non configuré)',
            'success': False
        }


# Instance globale du gestionnaire d'APIs
api_manager = APIManager()

# Création des agents (UTILISE AIAgent)
agents = {
    'alex': AIAgent(
        "Alex", 
        "Assistant productivité et gestion",
        "Expert en organisation, efficace et méthodique."
    ),
    'lina': AIAgent(
        "Lina",
        "Experte LinkedIn et réseautage professionnel", 
        "Professionnelle, stratégique et connectée."
    ),
    'marco': AIAgent(
        "Marco",
        "Spécialiste des réseaux sociaux et marketing",
        "Créatif, tendance et engageant."
    ),
    'sofia': AIAgent(
        "Sofia",
        "Organisatrice de calendrier et planification",
        "Précise, organisée et anticipatrice."
    ),
    'kai': AIAgent(
        "Kai",
        "Assistant conversationnel général",
        "Amical, curieux et adaptable."
    )
}

# Routes principales
@app.route('/')
def index():
    """Page d'accueil"""
    return render_template('chat.html')

@app.route('/settings')
def settings():
    """Page de configuration"""
    return render_template('settings.html')

@app.route('/api/save_key', methods=['POST'])
def save_api_key():
    """Sauvegarde la clé API Gemini uniquement (sensibilité à la casse corrigée)"""
    try:
        data = request.get_json()
        
        # Conversion en minuscules pour la robustesse (CORRECTION DE LA CASSE)
        provider = data.get('provider', '').lower() 
        api_key = data.get('api_key')
        
        if provider != 'gemini':
             return jsonify({
                 'success': False, 
                 'message': 'Seul le fournisseur "gemini" est supporté dans cette version. (Le champ "Service API" doit contenir "gemini")'
             })

        if not provider or not api_key:
            return jsonify({'success': False, 'message': 'Clé API requise'})
        
        success = api_manager.save_api_key(provider, api_key)
        
        if success:
            return jsonify({'success': True, 'message': f'Clé {provider} sauvegardée. Veuillez cliquer sur "Tester l\'API" pour vérifier.'})
        else:
            return jsonify({'success': False, 'message': 'Erreur lors de la sauvegarde'})
            
    except Exception as e:
        logger.error(f"Erreur sauvegarde clé: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/test_apis', methods=['POST'])
def test_apis():
    """Test l'API Gemini configurée"""
    try:
        success, message, _ = api_manager.test_gemini_api()
        
        return jsonify({
            'success': True,
            'results': {
                'gemini': {
                    'success': success,
                    'message': message,
                    'tested_at': datetime.now().isoformat()
                }
            },
            'summary': {
                'total': 1,
                'working': 1 if success else 0,
                'failed': 0 if success else 1
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur test APIs: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get_api_status', methods=['GET'])
def get_api_status():
    """Récupère le statut de l'API Gemini uniquement"""
    try:
        status_data = api_manager.get_api_status('gemini')
        
        return jsonify({
            'success': True,
            'apis': {
                'gemini': status_data
            },
            'total_configured': 1 if status_data['configured'] else 0
        })
        
    except Exception as e:
        logger.error(f"Erreur statut APIs: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/chat', methods=['POST'])
def chat():
    """Endpoint de chat avec les agents"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        agent_name = data.get('agent', 'kai').lower()
        
        if not message:
            return jsonify({'success': False, 'message': 'Message vide'})
        
        if agent_name not in agents:
            agent_name = 'kai'
        
        agent = agents[agent_name]
        response_data = agent.generate_response(message)
        
        return jsonify({
            'success': True,
            'agent': response_data['agent'],
            'response': response_data['response'],
            'provider': response_data['provider'],
            'api_working': response_data['success']
        })
        
    except Exception as e:
        logger.error(f"Erreur chat: {e}")
        return jsonify({
            'success': False, 
            'message': f'Erreur lors du traitement: {str(e)}'
        })

if __name__ == '__main__':
    try:
        logger.info("Démarrage de WaveAI...")
        
        # Initialisation de la DB est ici
        api_manager.init_database()
        logger.info("Système initialisé avec succès")
        
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        logger.error(f"Erreur critique au démarrage: {e}")
        raise
