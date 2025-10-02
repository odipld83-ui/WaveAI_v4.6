#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WaveAI - Système d'Agents IA (Google Gemini ONLY)
Version: GEMINI ONLY - Stabilité maximale et correction JSON finale
"""

import os
import sqlite3
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
# Importer les outils réels (même si non utilisés directement ici)
from tools import AVAILABLE_TOOLS # Assurez-vous que tools.py est dans le même dossier

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Lit la clé secrète depuis l'environnement (SECRET_KEY)
app.secret_key = os.environ.get('SECRET_KEY', 'waveai-secret-key-2024')

# Configuration de la base de données (simplifiée)
DATABASE_PATH = 'waveai.db'

# Configuration de l'API Gemini
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}"

class APIManager:
    """Gestionnaire simplifié pour la clé Gemini"""
    
    def __init__(self):
        self.init_database()
        self.test_results = {}
        
    def init_database(self):
        """Initialise la base de données SQLite (pour le statut et les logs)"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Table pour la clé API Gemini
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY,
                    provider TEXT UNIQUE NOT NULL,
                    api_key TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    last_tested TIMESTAMP,
                    test_status TEXT DEFAULT 'untested'
                )
            ''')
            
            # Table pour les tâches planifiées (utilisée par tools.py pour Gmail et Calendar)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    recipient TEXT,
                    subject TEXT,
                    body TEXT,
                    title TEXT,
                    notes TEXT,
                    duration_hours REAL,
                    scheduled_date TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Base de données initialisée avec succès")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
    
    def save_api_key(self, provider, api_key):
        """Sauvegarde la clé API Gemini"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO api_keys (provider, api_key, is_active)
                VALUES (?, ?, 1)
            ''', (provider, api_key))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Clé API sauvegardée pour {provider}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de la clé {provider}: {e}")
            return False
    
    def get_api_key(self, provider='gemini'):
        """
        Récupère la clé API Gemini.
        PRIORITÉ : 1. Variable d'Environnement (GEMINI_API_KEY) > 2. Base de Données
        """
        if provider == 'gemini':
            # 1. Tenter de lire depuis la variable d'environnement (Render)
            env_key = os.getenv('GEMINI_API_KEY')
            if env_key:
                return env_key
        
        # 2. Lire depuis la base de données (clé entrée via l'interface)
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT api_key FROM api_keys 
                WHERE provider = ? AND is_active = 1
            ''', (provider,))
            
            result = cursor.fetchone()
            conn.close()
            
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la clé {provider}: {e}")
            return None
    
    def get_api_status(self, provider='gemini'):
        """Récupère le statut de l'API Gemini"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT api_key, test_status, last_tested 
                FROM api_keys 
                WHERE provider = ?
            ''', (provider,))
            
            result = cursor.fetchone()
            conn.close()
            
            key_from_db = result[0] if result else None
            status = result[1] if result else 'missing'
            last_tested = result[2] if result else None

            # Vérifier l'ENV
            key_from_env = os.getenv('GEMINI_API_KEY')
            
            is_configured = (key_from_db is not None) or (key_from_env is not None)
            key_to_display = key_from_db if key_from_db else key_from_env

            return {
                'configured': is_configured,
                'key_preview': key_to_display[:8] + '...' if key_to_display and len(key_to_display) > 8 else (key_to_display if key_to_display else 'N/A'),
                'status': status,
                'last_tested': last_tested,
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
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE api_keys 
                SET test_status = ?, last_tested = CURRENT_TIMESTAMP
                WHERE provider = ?
            ''', (status, provider))
            
            conn.commit()
            conn.close()
            
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
            
            # Le test fonctionne avec cette structure generationConfig
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
                
                # --- CORRECTION DE L'ERREUR 'parts' pour le TEST ---
                if 'candidates' in result and result['candidates']:
                    candidate = result['candidates'][0]
                    content = candidate.get('content')
                    
                    if content and 'parts' in content and content['parts']:
                        text = content['parts'][0].get('text', '').strip().upper()
                        
                        if 'OK' in text or 'OK' == text:
                            self.log_test_result('gemini', 'success')
                            return True, "API Gemini fonctionnelle.", None
                    # --- FIN DE CORRECTION ---
                
                # Échec du test malgré le statut 200
                self.log_test_result('gemini', 'error')
                return False, f"API Gemini : Réponse inattendue. {response.text}", None

            else:
                error_msg = response.json().get('error', {}).get('message', 'Erreur HTTP inconnue')
                logger.error(f"Erreur API Gemini ({response.status_code}): {error_msg}")
                self.log_test_result('gemini', 'error')
                return False, f"Erreur API Gemini ({response.status_code}): {error_msg}", None
            
        except requests.exceptions.Timeout:
            self.log_test_result('gemini', 'error')
            return False, "Délai d'attente de l'API Gemini dépassé.", None
        except Exception as e:
            logger.error(f"Erreur lors du test Gemini: {e}")
            self.log_test_result('gemini', 'error')
            return False, f"Erreur non gérée lors du test Gemini: {str(e)}", None

# Instance globale du gestionnaire d'APIs
api_manager = APIManager()

# --- Fonctions Outils pour les Agents ---

def generate_tool_config():
    """Génère la liste des outils disponibles pour l'API Gemini (Alex et Sofia)"""
    tool_config = {
        "tools": [
            {
                "function_declarations": [
                    {
                        "name": tool_name,
                        "description": tool_func.__doc__.strip(),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                # Extrait les propriétés (arguments) à partir des annotations de type de la fonction
                                **{
                                    param: {"type": "string"}
                                    for param, type_hint in tool_func.__annotations__.items()
                                    if param != 'return'
                                }
                            },
                            # CORRECTION CLÉ : Exclure 'return' de la liste des arguments requis
                            "required": [
                                param for param in tool_func.__annotations__.keys()
                                if param != 'return'
                            ]
                        }
                    } 
                    for tool_name, tool_func in AVAILABLE_TOOLS.items()
                ]
            }
        ]
    }
    return tool_config

def execute_function(function_name, **kwargs):
    """Exécute la fonction Python demandée par l'IA."""
    if function_name in AVAILABLE_TOOLS:
        try:
            # Conversion des arguments en types attendus si nécessaire (non fait ici pour simplification)
            result = AVAILABLE_TOOLS[function_name](**kwargs)
            logger.info(f"Outil {function_name} exécuté avec succès.")
            return result
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de l'outil {function_name}: {e}")
            return f"Erreur lors de l'exécution de l'outil {function_name}: {str(e)}"
    return f"Outil inconnu: {function_name}"

# --- Définition de la Classe AIAgent ---

class AIAgent:
    """Agent IA utilisant l'API Gemini"""
    
    def __init__(self, name, role, personality, use_tools=False):
        self.name = name
        self.role = role
        self.personality = personality
        self.use_tools = use_tools
        self.tools_config = generate_tool_config() if use_tools else None
    
    def generate_response(self, message):
        """Génère une réponse en utilisant Gemini"""
        
        api_key = api_manager.get_api_key('gemini')
        if not api_key:
            return self._fallback_response()
        
        # Contexte personnalisé pour l'agent (System Instruction)
        system_instruction = f"""Tu es {self.name}, {self.role}.
Personnalité: {self.personality}
Réponds de manière naturelle et personnalisée selon ton rôle.
Garde tes réponses concises et utiles (maximum 150 mots)."""
        
        try:
            url = GEMINI_API_URL.format(GEMINI_MODEL, api_key)
            
            # Contenu de la requête
            contents = [
                # Instruction système passée comme premier message utilisateur
                {"role": "user", "parts": [{"text": system_instruction}]},
                # Message de l'utilisateur
                {"role": "user", "parts": [{"text": message}]}
            ]
            
            payload = {
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": 250,
                    "temperature": 0.7
                }
            }
            
            # Ajout des outils si l'agent les utilise
            if self.use_tools and self.tools_config:
                payload.update(self.tools_config)

            # --- PREMIER APPEL API (POUR LA REQUÊTE OU L'APPEL DE FONCTION) ---
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code != 200:
                 error_msg = response.json().get('error', {}).get('message', f'Erreur Gemini non détaillée: {response.status_code}')
                 logger.error(f"Erreur Gemini PREMIER APPEL pour {self.name}: {error_msg}")
                 return self._fallback_response(error_msg=error_msg)

            result = response.json()
            
            # --- CORRECTION DE L'ERREUR 'parts' pour l'AGENT ---
            if 'candidates' in result and result['candidates']:
                candidate = result['candidates'][0]
                content = candidate.get('content')
                
                # GESTION DE L'APPEL DE FONCTION
                if 'functionCall' in candidate:
                    func_call = candidate['functionCall']
                    function_name = func_call['name']
                    args = dict(func_call.get('args', {}))
                    
                    # Exécuter l'outil
                    tool_result = execute_function(function_name, **args)
                    
                    # --- DEUXIÈME APPEL API (POUR RAPPORTER LE RÉSULTAT) ---
                    
                    # 1. Ajouter l'appel de fonction à l'historique
                    contents.append({
                        "role": "model",
                        "parts": [{"functionCall": func_call}]
                    })
                    
                    # 2. Ajouter le résultat de l'outil
                    contents.append({
                        "role": "function",
                        "parts": [{"functionResponse": {"name": function_name, "response": {"result": tool_result}}}]
                    })
                    
                    # 3. Mettre à jour le payload pour le deuxième appel
                    payload['contents'] = contents
                    
                    response_2 = requests.post(url, json=payload, timeout=30)
                    
                    if response_2.status_code != 200:
                         error_msg = response_2.json().get('error', {}).get('message', f'Erreur Gemini non détaillée: {response_2.status_code}')
                         logger.error(f"Erreur Gemini DEUXIÈME APPEL pour {self.name}: {error_msg}")
                         return self._fallback_response(error_msg=f"Échec de la réponse après l'outil : {error_msg}")
                         
                    result_2 = response_2.json()
                    
                    # Extraction du texte final
                    final_candidate = result_2['candidates'][0]
                    final_content = final_candidate.get('content')
                    
                    if final_content and 'parts' in final_content and final_content['parts']:
                        generated_text = final_content['parts'][0].get('text', '')
                        
                        return {
                            'agent': self.name,
                            'response': generated_text.strip(),
                            'provider': f'Google Gemini ({GEMINI_MODEL.split("-")[-1]} + Outils)',
                            'success': True
                        }
                    
                    # Échec de l'extraction de la réponse finale
                    return self._fallback_response(error_msg="L'outil a été appelé, mais la réponse finale est vide.")


                # GESTION DE LA RÉPONSE TEXTE NORMALE
                if content and 'parts' in content and content['parts']:
                    generated_text = content['parts'][0].get('text', '')
                
                    if generated_text:
                        return {
                            'agent': self.name,
                            'response': generated_text.strip(),
                            'provider': f'Google Gemini ({GEMINI_MODEL.split("-")[-1]})',
                            'success': True
                        } 
                
                # Si 'candidates' est là mais que la structure interne est mauvaise
                error_msg = "Erreur de parsing de la réponse (parties manquantes dans le candidat)."
                logger.error(f"Erreur de parsing pour {self.name}: {error_msg}")
                return self._fallback_response(error_msg=error_msg)
            # --- FIN DE CORRECTION ---
            
            # Si l'API renvoie un bloc vide sans erreur apparente (très rare)
            error_msg = "Réponse Gemini vide ou inattendue."
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
            # Nettoyer l'erreur d'outils pour l'utilisateur
            if "* GenerateContentRequest.tools" in error_msg:
                 reason = "Erreur API : Configuration des outils invalide. Veuillez contacter l'administrateur."
            else:
                 reason = f"Erreur API: {error_msg}"
        
        return {
            'agent': self.name,
            'response': f"{fallback_responses.get(self.name.lower(), fallback_responses['kai'])} ({reason})",
            'provider': 'Mode Démo (Gemini non configuré)',
            'success': False
        }

# Création des agents (Alex et Sofia utilisent les outils)
agents = {
    'alex': AIAgent(
        "Alex", 
        "Assistant productivité et gestion",
        "Expert en organisation, efficace et méthodique, capable de gérer les e-mails et le calendrier.",
        use_tools=True 
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
        "Précise, organisée et anticipatrice.",
        use_tools=True 
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
    """Sauvegarde la clé API Gemini uniquement"""
    try:
        data = request.get_json()
        provider = data.get('provider')
        api_key = data.get('api_key')
        
        if provider != 'gemini':
             return jsonify({'success': False, 'message': 'Seul le fournisseur "gemini" est supporté dans cette version.'})

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
        
        api_manager.init_database()
        logger.info("Système initialisé avec succès")
        
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        logger.error(f"Erreur critique au démarrage: {e}")
        raise
