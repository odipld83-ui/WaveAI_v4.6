#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WaveAI - Système d'Agents IA (Hugging Face GRATUIT uniquement)
Version: HF ONLY FINAL - Stabilité sur Render - CORRIGÉ
"""

import os
import sqlite3
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import requests
from functools import wraps

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Lit la clé secrète depuis l'environnement (SECRET_KEY)
app.secret_key = os.environ.get('SECRET_KEY', 'waveai-secret-key-2024')

# Configuration de la base de données
DATABASE_PATH = 'waveai.db'

class APIManager:
    """Gestionnaire centralisé de l'API Hugging Face avec persistance et tests"""
    
    def __init__(self):
        self.init_database()
        self.test_results = {}
        # Modèles Hugging Face de fallback (du plus accessible au moins accessible)
        self.hf_models = [
            {
                'name': 'microsoft/DialoGPT-medium',
                'url': 'https://api-inference.huggingface.co/models/microsoft/DialoGPT-medium',
                'description': 'DialoGPT Medium - Conversationnel'
            },
            {
                'name': 'facebook/blenderbot-400M-distill',
                'url': 'https://api-inference.huggingface.co/models/facebook/blenderbot-400M-distill',
                'description': 'BlenderBot - Conversationnel'
            },
            {
                'name': 'microsoft/DialoGPT-small',
                'url': 'https://api-inference.huggingface.co/models/microsoft/DialoGPT-small',
                'description': 'DialoGPT Small - Léger'
            },
            {
                'name': 'gpt2',
                'url': 'https://api-inference.huggingface.co/models/gpt2',
                'description': 'GPT-2 - Génération de texte'
            },
            {
                'name': 'google/flan-t5-base',
                'url': 'https://api-inference.huggingface.co/models/google/flan-t5-base',
                'description': 'FLAN-T5 Base - Question-réponse'
            }
        ]
    
    def init_database(self):
        """Initialise la base de données SQLite"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Table pour les clés API (Gardée pour Hugging Face uniquement)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY,
                    provider TEXT UNIQUE NOT NULL,
                    api_key TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_tested TIMESTAMP,
                    test_status TEXT DEFAULT 'untested',
                    working_model TEXT
                )
            ''')
            
            # Table pour les logs de tests
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_logs (
                    id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    test_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_data TEXT,
                    error_message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Base de données initialisée avec succès")
            
        except Exception as e:
            # CORRECTION : Indentation correcte et bloc non vide
            logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
            raise
    
    def save_api_key(self, provider, api_key):
        """Sauvegarde une clé API dans la base de données (pour affichage/test)"""
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
    
    def get_api_key(self, provider):
        """
        Récupère la clé API Hugging Face.
        PRIORITÉ : 1. Variable d'Environnement (HUGGINGFACE_TOKEN) > 2. Base de Données
        """
        if provider == 'huggingface':
            # 1. Tenter de lire depuis la variable d'environnement (Render)
            env_key = os.getenv('HUGGINGFACE_TOKEN')
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
    
    def get_all_api_keys(self):
        """Récupère toutes les clés API actives (ici, seulement HF)"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Ne récupérer que Hugging Face
            cursor.execute('''
                SELECT provider, api_key, test_status, last_tested, working_model 
                FROM api_keys 
                WHERE provider = 'huggingface' AND is_active = 1
            ''')
            
            results = cursor.fetchall()
            conn.close()
            
            keys = {}
            for row in results:
                keys[row[0]] = {
                    'key': row[1],
                    'status': row[2],
                    'last_tested': row[3],
                    'working_model': row[4]
                }
            
            return keys
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des clés: {e}")
            return {}
    
    def log_test_result(self, provider, test_type, status, response_data=None, error_message=None, working_model=None):
        """Enregistre le résultat d'un test d'API"""
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO test_logs (provider, test_type, status, response_data, error_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (provider, test_type, status, json.dumps(response_data) if response_data else None, error_message))
            
            # Mettre à jour le statut dans api_keys
            cursor.execute('''
                UPDATE api_keys 
                SET test_status = ?, last_tested = CURRENT_TIMESTAMP, working_model = ?
                WHERE provider = ?
            ''', (status, working_model, provider))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du test {provider}: {e}")
            
    def test_huggingface_api(self, api_key):
        """Test complet de l'API Hugging Face avec modèles de fallback"""
        headers = {"Authorization": f"Bearer {api_key}"}
        
        for model_info in self.hf_models:
            try:
                logger.info(f"Test du modèle HF: {model_info['name']}")
                
                # Adapter le payload selon le modèle
                if 'gpt2' in model_info['name'].lower() or 'dialo' in model_info['name'].lower():
                    payload = {
                        "inputs": "Bonjour, comment allez-vous?",
                        "parameters": {"max_new_tokens": 50, "temperature": 0.7}
                    }
                elif 'flan-t5' in model_info['name'].lower():
                    payload = {
                        "inputs": "Question: Qui êtes-vous? Réponse:",
                        "parameters": {"max_new_tokens": 50}
                    }
                elif 'blenderbot' in model_info['name'].lower():
                    payload = {
                        "inputs": "Bonjour",
                        "parameters": {"max_new_tokens": 50}
                    }
                
                response = requests.post(
                    model_info['url'], 
                    headers=headers, 
                    json=payload, 
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    generated_text = ""
                    if isinstance(result, list) and len(result) > 0:
                        if 'generated_text' in result[0]:
                            generated_text = result[0]['generated_text']
                        elif 'response' in result[0]:
                            generated_text = result[0]['response']
                    
                    if generated_text and len(generated_text.strip()) > 5:
                        test_data = {
                            'model': model_info['name'],
                            'description': model_info['description'],
                            'test_response': generated_text[:100],
                            'response_type': type(result).__name__
                        }
                        
                        self.log_test_result('huggingface', 'complete', 'success', test_data, working_model=model_info['name'])
                        return True, f"Hugging Face API fonctionnelle ({model_info['description']})", test_data
                
                elif response.status_code == 503:
                    logger.info(f"Modèle {model_info['name']} en cours de chargement, test du suivant...")
                    continue
                else:
                    logger.warning(f"Modèle {model_info['name']} échoué: {response.status_code}")
                    continue
                    
            except Exception as e:
                logger.warning(f"Erreur avec modèle {model_info['name']}: {e}")
                continue
        
        # Aucun modèle n'a fonctionné
        error_msg = f"Aucun des {len(self.hf_models)} modèles Hugging Face n'est accessible. Vérifiez votre token ou réessayez plus tard."
        self.log_test_result('huggingface', 'complete', 'error', error_message=error_msg)
        return False, error_msg, None
    
    def run_all_tests(self):
        """Exécute les tests pour l'API Hugging Face uniquement."""
        results = {}
        # On utilise la clé la plus fiable (ENV ou DB)
        hf_key = self.get_api_key('huggingface')
        
        if hf_key:
            logger.info(f"Lancement du test pour Hugging Face...")
            
            success, message, data = self.test_huggingface_api(hf_key)
            
            results['huggingface'] = {
                'success': success,
                'message': message,
                'data': data,
                'tested_at': datetime.now().isoformat()
            }
        else:
            logger.warning("Clé Hugging Face non trouvée. Test non exécuté.")
        
        self.test_results = results
        return results

# Instance globale du gestionnaire d'APIs
api_manager = APIManager()

class AIAgent:
    """Agent IA avec intégration API Hugging Face et fallback intelligent"""
    
    def __init__(self, name, role, personality):
        self.name = name
        self.role = role
        self.personality = personality
    
    def generate_response(self, message, user_context=None):
        """Génère une réponse en utilisant Hugging Face (le seul supporté)"""
        
        # Contexte personnalisé pour l'agent
        system_prompt = f"""Tu es {self.name}, {self.role}.
Personnalité: {self.personality}
Réponds de manière naturelle et personnalisée selon ton rôle.
Garde tes réponses concises et utiles (max 200 mots).
Message utilisateur: {message}"""
        
        # 1. Essayer Hugging Face
        hf_key = api_manager.get_api_key('huggingface')
        if hf_key:
            # Récupérer le modèle qui fonctionne depuis la DB (mis à jour par le test)
            api_keys = api_manager.get_all_api_keys()
            working_model = api_keys.get('huggingface', {}).get('working_model')
            
            if working_model:
                try:
                    headers = {"Authorization": f"Bearer {hf_key}"}
                    
                    # Trouver l'URL du modèle qui fonctionne
                    model_url = None
                    for model_info in api_manager.hf_models:
                        if model_info['name'] == working_model:
                            model_url = model_info['url']
                            break
                    
                    if model_url:
                        # Adapter le prompt selon le modèle
                        final_prompt = f"{system_prompt}\n\n{message}"
                        if 'flan-t5' in working_model.lower():
                            final_prompt = f"Question: {final_prompt} Réponse:"
                        
                        payload = {
                            "inputs": final_prompt,
                            "parameters": {"max_new_tokens": 150, "temperature": 0.7}
                        }
                        
                        response = requests.post(model_url, headers=headers, json=payload, timeout=30)
                        
                        if response.status_code == 200:
                            result = response.json()
                            generated_text = ""
                            
                            if isinstance(result, list) and len(result) > 0:
                                generated_text = result[0].get('generated_text', '')
                            elif isinstance(result, dict):
                                generated_text = result.get('generated_text', '')
                            
                            if generated_text:
                                # Nettoyer la réponse
                                if final_prompt in generated_text:
                                    generated_text = generated_text.replace(final_prompt, '').strip()
                                
                                return {
                                    'agent': self.name,
                                    'response': generated_text,
                                    'provider': f'Hugging Face ({working_model.split("/")[-1]})',
                                    'success': True
                                }
                
                except Exception as e:
                    logger.error(f"Erreur Hugging Face pour {self.name}: {e}")
        
        # 2. Aucune API disponible - réponse de fallback intelligente
        fallback_responses = {
            'kai': "Je suis Kai, votre assistant IA. Pour que je puisse vous aider avec de vraies réponses intelligentes, veuillez configurer la clé API Hugging Face dans les paramètres. En attendant, je peux vous guider vers la configuration !",
            'alex': "Je suis Alex, spécialiste de la productivité. J'ai besoin de mon API Hugging Face pour vous donner des conseils personnalisés. Rendez-vous dans les paramètres !",
            'lina': "Je suis Lina, experte LinkedIn. J'ai besoin de mon API Hugging Face pour analyser votre situation. Configurez la clé API pour commencer !",
            'marco': "Je suis Marco, spécialiste des réseaux sociaux. J'ai besoin de mon API Hugging Face pour générer des idées créatives. Direction les paramètres !",
            'sofia': "Je suis Sofia, votre organisatrice personnelle. J'ai besoin de mon API Hugging Face pour optimiser votre planning. Allez dans les paramètres !"
        }
        
        return {
            'agent': self.name,
            'response': fallback_responses.get(self.name.lower(), fallback_responses['kai']),
            'provider': 'Mode Démo (Hugging Face non configuré)',
            'success': False
        }

# Création des agents (inchangé)
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
    """Sauvegarde la clé API Hugging Face uniquement"""
    try:
        data = request.get_json()
        provider = data.get('provider')
        api_key = data.get('api_key')
        
        if provider != 'huggingface':
             return jsonify({'success': False, 'message': 'Seul le fournisseur "huggingface" est supporté dans cette version.'})

        if not provider or not api_key:
            return jsonify({'success': False, 'message': 'Clé API requise'})
        
        # La clé est sauvegardée dans la DB locale pour l'affichage/test
        success = api_manager.save_api_key(provider, api_key)
        
        if success:
            return jsonify({'success': True, 'message': f'Clé {provider} sauvegardée. Veuillez cliquer sur "Tester les APIs" pour vérifier.'})
        else:
            return jsonify({'success': False, 'message': 'Erreur lors de la sauvegarde'})
            
    except Exception as e:
        logger.error(f"Erreur sauvegarde clé: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/test_apis', methods=['POST'])
def test_apis():
    """Test l'API Hugging Face configurée"""
    try:
        # La fonction run_all_tests ne teste plus que HF
        results = api_manager.run_all_tests()
        
        return jsonify({
            'success': True,
            'results': results,
            'summary': {
                'total': len(results),
                'working': sum(1 for r in results.values() if r['success']),
                'failed': sum(1 for r in results.values() if not r['success'])
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur test APIs: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get_api_status', methods=['GET'])
def get_api_status():
    """Récupère le statut de l'API Hugging Face uniquement"""
    try:
        api_keys = api_manager.get_all_api_keys()
        
        status = {}
        provider = 'huggingface'
        
        # On vérifie si la clé est dans l'ENV
        is_configured_in_env = api_manager.get_api_key(provider) is not None
        
        if provider in api_keys:
            key_data = api_keys[provider]
            status[provider] = {
                'configured': True,
                # On ne montre pas la clé complète pour des raisons de sécurité
                'key_preview': key_data['key'][:8] + '...' if len(key_data['key']) > 8 else key_data['key'],
                'status': key_data['status'],
                'last_tested': key_data['last_tested'],
                'working_model': key_data.get('working_model', '')
            }
        elif is_configured_in_env:
             # Clé dans l'ENV, mais pas encore testée dans la DB
            status[provider] = {
                'configured': True,
                'key_preview': 'Clé ENV masquée',
                'status': 'untested',
                'last_tested': None,
                'working_model': ''
            }
        else:
            status[provider] = {
                'configured': False,
                'key_preview': 'N/A',
                'status': 'missing',
                'last_tested': None,
                'working_model': ''
            }

        return jsonify({
            'success': True,
            'apis': status,
            'total_configured': 1 if is_configured_in_env or provider in api_keys else 0
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

@app.route('/api/test_agent', methods=['POST'])
def test_agent():
    """Test spécifique d'un agent"""
    try:
        data = request.get_json()
        agent_name = data.get('agent', 'kai').lower()
        
        if agent_name not in agents:
            return jsonify({'success': False, 'message': f'Agent {agent_name} non trouvé'})
        
        test_message = "Bonjour, peux-tu te présenter et expliquer ton rôle ?"
        agent = agents[agent_name]
        response_data = agent.generate_response(test_message)
        
        return jsonify({
            'success': True,
            'agent': agent_name,
            'test_message': test_message,
            'response': response_data['response'],
            'provider': response_data['provider'],
            'api_working': response_data['success']
        })
        
    except Exception as e:
        logger.error(f"Erreur test agent: {e}")
        return jsonify({'success': False, 'message': str(e)})

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
