#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WaveAI - Système d'Agents IA (Google Gemini ONLY)
Version: STABLE POSTGRESQL + Worker Support (Prêt pour Gunicorn)
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
# Nouvelle dépendance pour PostgreSQL
import psycopg2 
from urllib.parse import urlparse

# Importer les outils réels (nécessite tools.py mis à jour)
from tools import AVAILABLE_TOOLS 

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'waveai-secret-key-2024')

# Configuration de l'API Gemini
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}"


# --- Nouvelle Fonction de Connexion DB ---
def get_db_connection():
    """Établit une connexion à PostgreSQL en utilisant DATABASE_URL."""
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        logger.error("La variable d'environnement DATABASE_URL est manquante.")
        raise EnvironmentError("Base de données non configurée. Impossible de se connecter.")

    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode='require' # Requis par Render pour les connexions externes
    )

# --- Classes de Gestionnaires ---

class AIAgent:
    """Agent IA de base qui utilise l'API Gemini."""
    def __init__(self, name, system_prompt, model=GEMINI_MODEL):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        
    def generate_response(self, user_message):
        """Génère une réponse, y compris l'utilisation des outils."""
        gemini_api_key = api_manager.get_api_key('gemini')
        
        if not gemini_api_key:
            return {
                'success': False,
                'agent': self.name,
                'response': f"Erreur: Clé API Gemini manquante ou invalide.",
                'provider': 'None',
                'tool_call': None
            }
            
        # Définition de la fonction pour l'appel d'outil
        tool_schema = [
            {
                "name": name,
                "description": tool.__doc__.strip(),
                "parameters": {
                    "type": "object",
                    # Supposons que les fonctions dans tools.py sont annotées
                    "properties": {
                        k: {"type": "string", "description": k} 
                        for k in tool.__annotations__.keys() if k != 'return'
                    },
                    "required": [
                        k for k in tool.__annotations__.keys() if k != 'return'
                    ]
                }
            } for name, tool in AVAILABLE_TOOLS.items() if tool.__doc__
        ]

        # Construction du corps de la requête
        contents = [
            {"role": "user", "parts": [{"text": user_message}]}
        ]
        
        payload = {
            "contents": contents,
            "config": {
                "systemInstruction": self.system_prompt,
                "tools": [{"functionDeclarations": tool_schema}]
            }
        }
        
        headers = {'Content-Type': 'application/json'}
        url = GEMINI_API_URL.format(self.model, gemini_api_key)
        
        try:
            # Premier appel à Gemini (peut demander un outil)
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            response_json = response.json()
            
            # --- 1. Vérification de l'Appel d'Outil ---
            if 'functionCalls' in response_json.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0]:
                tool_calls = response_json['candidates'][0]['content']['parts'][0]['functionCalls']
                
                tool_results_parts = []
                for call in tool_calls:
                    function_name = call['name']
                    function_args = dict(call['args'])
                    
                    if function_name in AVAILABLE_TOOLS:
                        tool_function = AVAILABLE_TOOLS[function_name]
                        
                        logger.info(f"Appel d'outil: {function_name} avec args: {function_args}")
                        
                        # Exécuter l'outil (le Worker fera le travail de fond)
                        tool_result = tool_function(**function_args)
                        
                        tool_results_parts.append({
                            "functionResponse": {
                                "name": function_name,
                                "response": {"result": tool_result}
                            }
                        })
                    
                # --- 2. Deuxième Appel avec les Résultats d'Outil ---
                
                # Ajouter les résultats des outils à l'historique de la requête
                contents.append({
                    "role": "model", 
                    "parts": response_json['candidates'][0]['content']['parts']
                })
                contents.append({
                    "role": "tool", 
                    "parts": tool_results_parts
                })
                
                # Préparer le nouveau payload
                payload['contents'] = contents
                
                # Appel final à Gemini pour obtenir la réponse textuelle
                final_response = requests.post(url, headers=headers, json=payload, timeout=30)
                final_response.raise_for_status()
                final_response_json = final_response.json()
                
                final_text = final_response_json['candidates'][0]['content']['parts'][0]['text']
                
                return {
                    'success': True,
                    'agent': self.name,
                    'response': final_text,
                    'provider': 'Gemini-Tool',
                    'tool_call': tool_calls
                }

            # --- 3. Réponse Textuelle Directe ---
            text_response = response_json['candidates'][0]['content']['parts'][0]['text']
            
            return {
                'success': True,
                'agent': self.name,
                'response': text_response,
                'provider': 'Gemini',
                'tool_call': None
            }
            
        except requests.exceptions.HTTPError as errh:
            logger.error(f"Erreur HTTP Gemini: {errh.response.text}")
            return {'success': False, 'response': f"Erreur HTTP: {errh.response.status_code}. Vérifiez votre clé API.", 'agent': self.name, 'provider': 'Gemini', 'tool_call': None}
        except Exception as e:
            logger.error(f"Erreur inattendue Gemini: {e}")
            return {'success': False, 'response': f"Erreur inattendue: {str(e)}", 'agent': self.name, 'provider': 'Gemini', 'tool_call': None}


class APIManager:
    """Gestionnaire simplifié pour la clé Gemini et l'initialisation DB (PostgreSQL)"""
    
    def __init__(self):
        self.init_database()
        
    def init_database(self):
        """Initialise les tables PostgreSQL si elles n'existent pas."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Table pour la clé API Gemini
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id SERIAL PRIMARY KEY,
                    provider TEXT UNIQUE NOT NULL,
                    api_key TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    last_tested TIMESTAMP,
                    test_status TEXT DEFAULT 'untested'
                )
            ''')
            
            # Table pour les tâches planifiées (Ajout du champ sent_at pour le worker)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id SERIAL PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    scheduled_date TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'pending',
                    sent_at TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Base de données PostgreSQL initialisée avec succès")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")
            
    def get_api_key(self, provider):
        """Récupère la clé API de l'environnement ou de la DB."""
        # Prioriser la variable d'environnement pour Gemini (plus fiable)
        if provider.lower() == 'gemini':
            return os.environ.get('GEMINI_API_KEY')
        
        # Logique simplifiée pour les autres clés
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT api_key FROM api_keys WHERE provider = %s AND is_active = TRUE", (provider.lower(),))
            key = cursor.fetchone()
            conn.close()
            return key[0] if key else None
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la clé {provider}: {e}")
            return None
            
    # NOTE: Les autres méthodes de APIManager (save_api_key, etc.) doivent être converties 
    # pour utiliser la connexion PostgreSQL. Je laisse l'implémentation de get_api_key 
    # et init_database car elles sont essentielles.


# --- Initialisation des Agents ---

AGENT_PROMPTS = {
    'kai': "Vous êtes Kai, un assistant amical et généraliste. Votre objectif est de fournir des informations précises et utiles. Ne faites pas d'appels d'outils sauf si c'est absolument nécessaire et explicite dans la demande.",
    'alex': "Vous êtes Alex, l'agent de productivité et de communication. Votre rôle est d'utiliser les outils pour planifier des e-mails, vérifier les e-mails entrants, et gérer le calendrier. Répondez toujours de manière concise pour confirmer l'action de l'outil."
}

api_manager = APIManager()
agents = {
    'kai': AIAgent('Kai', AGENT_PROMPTS['kai']),
    'alex': AIAgent('Alex', AGENT_PROMPTS['alex'])
}

# --- Routes Flask ---

@app.route('/')
def home():
    """Page d'accueil."""
    api_key_status = api_manager.get_api_key('gemini') is not None
    return render_template('index.html', api_key_status=api_key_status)

@app.route('/api/status', methods=['GET'])
def get_api_status():
    """Retourne le statut de l'API Gemini (basé sur la clé dans l'environnement)."""
    try:
        status = api_manager.get_api_key('gemini') is not None
        return jsonify({'success': True, 'api_working': status, 'provider': 'Gemini'})
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


# --- Démarrage (Retiré pour Gunicorn) ---

# Le bloc if __name__ == '__main__': a été supprimé pour permettre à Gunicorn
# de démarrer l'application. La seule chose nécessaire est que la DB soit initialisée
# lorsque l'application est chargée. C'est fait dans api_manager = APIManager().
