import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
import requests
import psycopg2 # Nécessite 'psycopg2-binary' dans requirements.txt
from contextlib import contextmanager

# Importez AVAILABLE_TOOLS (assurez-vous que tools.py est présent et contient ce dict)
try:
    from tools import AVAILABLE_TOOLS 
except ImportError:
    # Utilisation d'un dictionnaire vide si tools.py n'est pas trouvé
    AVAILABLE_TOOLS = {}

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Lit la clé secrète depuis l'environnement (SECRET_KEY)
app.secret_key = os.environ.get('SECRET_KEY', 'waveai-secret-key-2024')

# --- Configuration PostgreSQL ---
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logger.error("La variable d'environnement DATABASE_URL n'est pas définie.")

@contextmanager
def get_db_connection():
    """Fournit une connexion à la base de données PostgreSQL."""
    if not DATABASE_URL:
        # Lève une erreur pour signaler l'absence de DB_URL (critique pour Render)
        raise Exception("DATABASE_URL non défini.")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
    finally:
        if conn:
            conn.close()

# --- Configuration de l'API Gemini ---
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent" 

class APIManager:
    """Gestionnaire pour la clé Gemini et autres services."""
    
    def __init__(self):
        # La base de données est initialisée une fois au démarrage
        pass
        
    def init_database(self):
        """Initialise la base de données PostgreSQL (tables)."""
        if not DATABASE_URL:
            logger.error("Initialisation DB échouée: DATABASE_URL non défini.")
            return

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Table pour les clés API
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

                # S'assurer que 'gemini' est au moins présent si la clé est dans l'ENV
                gemini_key_from_env = os.environ.get('GEMINI_API_KEY')
                if gemini_key_from_env:
                    cursor.execute(
                        """
                        INSERT INTO api_keys (provider, api_key, is_active, last_tested, test_status)
                        VALUES ('gemini', %s, TRUE, NOW(), 'untested')
                        ON CONFLICT (provider) DO UPDATE
                        SET api_key = EXCLUDED.api_key;
                        """,
                        (gemini_key_from_env,)
                    )

                # Table pour les tâches planifiées (si non gérée par tools.py)
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
                logger.info("Base de données PostgreSQL initialisée avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données PostgreSQL: {e}")
            raise e

    def get_api_key(self, provider):
        """Récupère la clé API la plus récente pour un fournisseur."""
        # Priorité à la variable d'environnement pour la clé principale (Gemini)
        if provider.lower() == 'gemini':
            env_key = os.environ.get('GEMINI_API_KEY')
            if env_key:
                return env_key
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT api_key FROM api_keys WHERE provider = %s AND is_active = TRUE ORDER BY created_at DESC LIMIT 1",
                    (provider.lower(),)
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Erreur DB lors de la récupération de la clé pour {provider}: {e}")
            return None

api_manager = APIManager()


class Agent:
    """Classe de base pour tous les agents IA."""
    
    def __init__(self, name, system_prompt, model=GEMINI_MODEL, tools=None):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools if tools is not None else AVAILABLE_TOOLS

    def generate_response(self, user_message):
        api_key = api_manager.get_api_key('gemini')
        if not api_key:
            return {
                'success': False,
                'agent': self.name,
                'response': "ERREUR: Clé API Gemini manquante ou invalide. Veuillez configurer la clé sur la page /settings.",
                'provider': 'None',
                'api_working': False
            }

        url = GEMINI_API_URL.format(self.model)
        
        content = [
            {"role": "user", "parts": [{"text": user_message}]}
        ]
        
        headers = {
            "Content-Type": "application/json"
        }

        request_body = {
            "contents": content,
            "config": {
                "systemInstruction": self.system_prompt
            }
        }
        
        # NOTE: La gestion complète des outils est plus complexe. Ici, seul l'appel simple est effectué.

        full_url = f"{url}?key={api_key}"
        
        try:
            response = requests.post(full_url, headers=headers, json=request_body)
            response.raise_for_status()
            data = response.json()
            
            if data and 'candidates' in data and data['candidates']:
                text_response = data['candidates'][0]['content']['parts'][0]['text']
                
                return {
                    'success': True,
                    'agent': self.name,
                    'response': text_response,
                    'provider': 'Gemini',
                    'api_working': True
                }
            
            return {
                'success': False,
                'agent': self.name,
                'response': "La réponse de l'IA est vide ou n'a pas le format attendu.",
                'provider': 'Gemini',
                'api_working': True
            }
            
        except requests.exceptions.HTTPError as errh:
            logger.error(f"Erreur HTTP Gemini: {errh}")
            return {
                'success': False,
                'agent': self.name,
                'response': f"Erreur HTTP: {errh}. Clé API peut-être invalide ou épuisée.",
                'provider': 'Gemini',
                'api_working': False
            }
        except Exception as e:
            logger.error(f"Erreur lors de l'appel à l'API Gemini: {e}")
            return {
                'success': False,
                'agent': self.name,
                'response': f"Erreur inattendue: {str(e)}",
                'provider': 'Gemini',
                'api_working': False
            }


# --- Définition des Agents ---
agents = {
    'kai': Agent(
        name='Kai (Generaliste)',
        system_prompt="Tu es Kai, un assistant IA généraliste. Réponds aux questions de manière concise et amicale. N'utilise aucun outil pour l'instant."
    ),
    # Vous pouvez ajouter d'autres agents ici si nécessaire.
}


# --- Routes Flask ---

@app.route('/')
def home():
    """Page d'accueil."""
    api_key_status = api_manager.get_api_key('gemini') is not None
    # Nécessite un fichier 'templates/index.html'
    return render_template('index.html', api_key_status=api_key_status)

@app.route('/settings')
def settings():
    """Page de gestion des clés API."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Récupère toutes les clés (pour affichage)
            cursor.execute("SELECT provider, is_active, last_tested, test_status, created_at FROM api_keys ORDER BY provider")
            api_keys = cursor.fetchall()
            
            # Mettre en forme les données pour le template
            keys_data = []
            for provider, is_active, last_tested, test_status, created_at in api_keys:
                keys_data.append({
                    'provider': provider.upper(),
                    'is_active': 'Oui' if is_active else 'Non',
                    'last_tested': last_tested.strftime('%Y-%m-%d %H:%M:%S') if last_tested else 'N/A',
                    'test_status': test_status
                })
                
            # Nécessite un fichier 'templates/settings.html'
            return render_template('settings.html', keys=keys_data)
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage des paramètres: {e}")
        return render_template('settings.html', error=f"Erreur DB: {str(e)}. Vérifiez DATABASE_URL.", keys=[])

@app.route('/api/save_key', methods=['POST'])
def save_api_key_endpoint():
    """Endpoint pour enregistrer une clé API."""
    data = request.get_json()
    provider = data.get('provider')
    api_key = data.get('api_key')
    
    if not provider or not api_key:
        return jsonify({'success': False, 'message': 'Provider et Clé API requis.'}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Utiliser ON CONFLICT DO UPDATE pour PostgreSQL (UPSERT)
            cursor.execute(
                """
                INSERT INTO api_keys (provider, api_key, is_active, last_tested, test_status)
                VALUES (%s, %s, TRUE, NOW(), 'untested')
                ON CONFLICT (provider) DO UPDATE
                SET api_key = EXCLUDED.api_key, is_active = TRUE, last_tested = NOW(), test_status = 'untested';
                """,
                (provider.lower(), api_key)
            )
            conn.commit()
            return jsonify({'success': True, 'message': f'Clé {provider.upper()} enregistrée avec succès.'})
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la clé: {e}")
        return jsonify({'success': False, 'message': f'Erreur DB: {str(e)}. Vérifiez DATABASE_URL.'}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """Endpoint de chat avec les agents"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        agent_name = data.get('agent', 'kai').lower()
        
        if not message:
            return jsonify({'success': False, 'message': 'Message vide'}), 400
        
        if agent_name not in agents:
            agent_name = 'kai'
        
        agent = agents[agent_name]
        response_data = agent.generate_response(message)
        
        return jsonify({
            'success': response_data['success'],
            'agent': response_data['agent'],
            'response': response_data['response'],
            'provider': response_data['provider'],
            'api_working': response_data['api_working']
        })
        
    except Exception as e:
        logger.error(f"Erreur chat: {e}")
        return jsonify({
            'success': False, 
            'message': f"Erreur lors du traitement: {str(e)}"
        }), 500

# --- Démarrage ---

# Exécution initiale pour l'initialisation de la DB
try:
    api_manager.init_database()
except Exception as e:
    logger.warning(f"L'initialisation de la DB a échoué: {e}")

if __name__ == '__main__':
    logger.info("Démarrage de WaveAI...")
    # NOTE: Pour le développement local uniquement
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
