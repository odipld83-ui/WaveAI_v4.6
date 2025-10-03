import os
import json
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from google import genai
from google.genai import types
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime
import pytz

app = Flask(__name__)
# Secret de session Flask (CHANGEZ-MOI POUR LA PROD !)
app.secret_key = 'super_secret_key_pour_la_session' 

# =========================================================================
# 1. CONFIGURATION DES CLÉS & SCOPES OAuth
# =========================================================================

# CLÉ GEMINI - À REMPLACER
GEMINI_API_KEY = "VOTRE_CLE_API_GEMINI"

# Fichier de secrets pour l'ID Client et Secret (doit être créé)
CLIENT_SECRETS_FILE = "client_secrets.json"

# Scopes pour les outils :
# Modification de Gmail (lecture, écriture, suppression)
GMAIL_SCOPE = ['https://www.googleapis.com/auth/gmail.modify']
# Événements du calendrier (lecture, écriture, suppression)
CALENDAR_SCOPE = ['https://www.googleapis.com/auth/calendar.events'] 

# Fichiers de jetons (un par service)
GMAIL_TOKEN_FILE = 'token_gmail.json'
CALENDAR_TOKEN_FILE = 'token_calendar.json'

# Initialisation du client Gemini
try:
    # Le client ne sera utilisé que si la clé est valide
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    print(f"Erreur d'initialisation de l'API Gemini: {e}")
    client = None

# =========================================================================
# 2. OUTILS (FUNCTIONS) POUR LES AGENTS
# =========================================================================

# --- Outil 1 : Date et Heure Actuelles (pour TOUS les agents) ---
def get_current_datetime():
    """
    Retourne la date et l'heure actuelles (Heure de Paris) au format ISO 8601.
    Utiliser pour répondre aux questions sur l'heure, la date ou le jour actuel.
    """
    tz = pytz.timezone('Europe/Paris')
    current_time = datetime.now(tz).isoformat()
    # Retourne toujours une chaîne JSON pour le modèle
    return json.dumps({"current_datetime": current_time, "timezone": "Europe/Paris"})

# --- Fonctions Utilitaires OAuth (Vérification du statut) ---

def check_gmail_status():
    """Vérifie si le jeton Gmail existe et est valide."""
    if os.path.exists(GMAIL_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, GMAIL_SCOPE)
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(GMAIL_TOKEN_FILE, 'w') as token:
                        token.write(creds.to_json())
                else:
                    return False
            return True
        except Exception:
            return False
    return False

def check_calendar_status():
    """Vérifie si le jeton Google Calendar existe et est valide."""
    if os.path.exists(CALENDAR_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(CALENDAR_TOKEN_FILE, CALENDAR_SCOPE)
            if not creds.valid:
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(CALENDAR_TOKEN_FILE, 'w') as token:
                        token.write(creds.to_json())
                else:
                    return False
            return True
        except Exception:
            return False
    return False


# --- Fonctions Gmail (pour Alex) ---
def search_gmail(query: str):
    """Recherche les 5 derniers emails dans Gmail de l'utilisateur."""
    if not check_gmail_status():
        return json.dumps({"status": "error", "message": "Jeton Gmail expiré ou manquant. L'utilisateur doit se connecter via /authorize_gmail."})
    
    try:
        creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, GMAIL_SCOPE)
        service = build('gmail', 'v1', credentials=creds)
        
        # NOTE: Ceci est une implémentation simulée.
        # En production, vous feriez l'appel API réel ici.
        results = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return json.dumps({"status": "success", "emails": "Aucun email trouvé correspondant à la requête."})
            
        # Simplification de la réponse pour le modèle
        return json.dumps({"status": "success", "count": len(messages), "emails_summary": f"Emails trouvés : {len(messages)}. Requête utilisée : {query}"})
        
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Erreur lors de l'accès à Gmail: {e}"})

# --- Fonctions Calendar (pour Sofia) ---
def create_calendar_event(summary: str, description: str, start_datetime: str, end_datetime: str):
    """Crée un événement dans le calendrier principal de l'utilisateur.
    Les dates doivent être au format ISO 8601 (ex: 2024-10-03T10:00:00)."""
    if not check_calendar_status():
        return json.dumps({"status": "error", "message": "Jeton Calendar expiré ou manquant. L'utilisateur doit se connecter via /authorize_calendar."})

    try:
        creds = Credentials.from_authorized_user_file(CALENDAR_TOKEN_FILE, CALENDAR_SCOPE)
        service = build('calendar', 'v3', credentials=creds)

        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_datetime, 
                'timeZone': 'Europe/Paris', # Assurez-vous d'utiliser le bon fuseau horaire
            },
            'end': {
                'dateTime': end_datetime,
                'timeZone': 'Europe/Paris',
            },
        }

        # Crée l'événement sur le calendrier 'primary' (principal)
        event = service.events().insert(calendarId='primary', body=event).execute()
        return json.dumps({"status": "success", "message": f"Événement créé avec succès: {summary}", "htmlLink": event.get('htmlLink')})

    except Exception as e:
        return json.dumps({"status": "error", "message": f"Erreur lors de la création de l'événement: {e}"})

# Définition de TOUS les outils Python
PYTHON_TOOLS = [search_gmail, create_calendar_event, get_current_datetime]
TOOL_NAMES = [t.__name__ for t in PYTHON_TOOLS]

# =========================================================================
# 3. FLUX OAUTH (GMAIL & CALENDAR)
# =========================================================================

# --- Fonction utilitaire pour le flux OAuth ---
def get_oauth_flow(scopes, redirect_route):
    """Crée l'objet Flow pour le service donné."""
    return Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=scopes,
        # url_for est essentiel pour générer l'URL complète
        redirect_uri=url_for(redirect_route, _external=True) 
    )

# --- Routes OAuth Gmail (Alex) ---

@app.route('/authorize_gmail')
def authorize_gmail():
    flow = get_oauth_flow(GMAIL_SCOPE, 'callback_gmail')
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/callback_gmail')
def callback_gmail():
    if 'state' not in session or session['state'] != request.args.get('state'):
        return "Erreur d'état (CSRF potential)", 400

    flow = get_oauth_flow(GMAIL_SCOPE, 'callback_gmail')
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        return f"Erreur lors de la récupération du jeton: {e}", 500
    
    credentials = flow.credentials
    with open(GMAIL_TOKEN_FILE, 'w') as token:
        token.write(credentials.to_json())
    
    return "Connexion Gmail réussie ! Alex peut maintenant lire et modifier vos emails. <a href='/'>Retour au Chat</a>"

# --- Routes OAuth Calendar (Sofia) ---

@app.route('/authorize_calendar')
def authorize_calendar():
    flow = get_oauth_flow(CALENDAR_SCOPE, 'callback_calendar')
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/callback_calendar')
def callback_calendar():
    if 'state' not in session or session['state'] != request.args.get('state'):
        return "Erreur d'état (CSRF potential)", 400

    flow = get_oauth_flow(CALENDAR_SCOPE, 'callback_calendar')
    try:
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        return f"Erreur lors de la récupération du jeton: {e}", 500
    
    credentials = flow.credentials
    with open(CALENDAR_TOKEN_FILE, 'w') as token:
        token.write(credentials.to_json())
    
    return "Connexion Google Agenda réussie ! Sofia peut maintenant gérer vos événements. <a href='/'>Retour au Chat</a>"


# =========================================================================
# 4. AGENTS, CHAT ET LOGIQUE PRINCIPALE
# =========================================================================

# Définition des agents
AGENT_PROMPTS = {
    'kai': "Tu es Kai, un assistant général amical et utile. Ton rôle est de répondre aux questions en utilisant tes capacités de recherche sur Internet et de vérifier l'heure actuelle si nécessaire. Réponds brièvement et clairement.",
    'alex': "Tu es Alex, un assistant spécialisé en productivité. Ton rôle principal est de gérer les emails. Utilise les outils disponibles pour rechercher et modifier les messages Gmail sur demande. Réponds de manière professionnelle.",
    'sofia': "Tu es Sofia, une organisatrice de calendrier très efficace. Ton rôle est de gérer l'emploi du temps de l'utilisateur. Utilise l'outil `Calendar` pour ajouter des événements à l'agenda de l'utilisateur quand il le demande. Réponds de manière précise sur les dates et heures.",
    # ... autres agents ...
}

@app.route('/')
def index():
    # Route principale qui rend le template chat.html
    return render_template('chat.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    message = data.get('message')
    agent_id = data.get('agent', 'kai')
    history = data.get('history', [])

    if not client:
        return jsonify({"success": False, "message": "L'API Gemini n'est pas initialisée (Clé API manquante ou invalide)."}), 500

    # 1. Préparation du modèle et de l'historique
    system_instruction = AGENT_PROMPTS.get(agent_id, AGENT_PROMPTS['kai'])
    
    # Construction de l'historique pour le modèle
    contents = []
    for entry in history:
        role = 'user' if entry['role'] == 'user' else 'model'
        contents.append(types.Content(role=role, parts=[types.Part.from_text(entry['text'])]))
        
    contents.append(types.Content(role='user', parts=[types.Part.from_text(message)]))

    # 2. Détermination des outils disponibles pour l'agent
    
    # TOUS les agents ont accès à l'heure actuelle
    active_tools = [get_current_datetime] 
    enable_google_search = False 
    
    if agent_id == 'kai':
        # Kai a la recherche Google en plus de l'heure
        enable_google_search = True
    elif agent_id == 'alex':
        # Alex a Gmail en plus de l'heure
        active_tools.append(search_gmail)
    elif agent_id == 'sofia':
        # Sofia a Calendar en plus de l'heure
        active_tools.append(create_calendar_event)
    
    # Paramètres d'exécution
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=active_tools if active_tools else None,
        # Activation de la recherche Google uniquement pour l'agent Kai
        google_search=enable_google_search 
    )

    try:
        # Premier appel à l'API Gemini
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=config,
        )

        # 3. Boucle Tool-Calling pour les fonctions Python
        tool_calls = response.function_calls if response.function_calls else []
        tool_response_parts = []
        
        while tool_calls:
            # Ajout des appels d'outils à l'historique pour le prochain appel
            contents.append(response.candidates[0].content)

            # Exécution des appels d'outils Python
            for tool_call in tool_calls:
                function_name = tool_call.name
                
                # Vérification de l'outil et exécution
                if function_name not in TOOL_NAMES:
                    tool_output = json.dumps({"status": "error", "message": f"Outil Python non reconnu: {function_name}"})
                else:
                    func = next(t for t in PYTHON_TOOLS if t.__name__ == function_name)
                    
                    # Exécuter la fonction Python
                    tool_output = func(**dict(tool_call.args))

                tool_response_parts.append(types.Part.from_function_response(
                    name=function_name,
                    response={"result": tool_output}
                ))

            # Ajout des réponses des outils à l'historique
            contents.append(types.Content(role="tool", parts=tool_response_parts))

            # Deuxième appel (ou plus) pour obtenir la réponse textuelle
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=config,
            )
            tool_calls = response.function_calls if response.function_calls else []

        # 4. Nettoyage de l'historique pour l'envoyer au frontend
        new_history = []
        for content in contents[:-1]: 
            if content.role in ['user', 'model']:
                text = content.parts[0].text
                new_history.append({'role': content.role, 'text': text})
        
        # 5. Réponse finale
        return jsonify({
            "success": True,
            "agent": agent_id,
            "response": response.text,
            "api_working": True,
            "provider": "Gemini",
            "history": new_history
        })

    except Exception as e:
        print(f"Erreur API Gemini: {e}")
        return jsonify({"success": False, "message": f"Erreur de l'API: {e}"}), 500

@app.route('/api/get_api_status')
def get_api_status():
    """Vérifie l'état des connexions API pour l'affichage dans le chat."""
    status = 0
    
    if os.path.exists(CLIENT_SECRETS_FILE):
        if check_gmail_status():
            status += 1
        if check_calendar_status():
            status += 1
            
    return jsonify({
        "success": True, 
        "total_configured": status, 
    })

@app.route('/api/test_apis', methods=['POST'])
def test_apis():
    """Teste si les connexions Gmail et Calendar sont actives (utilisé par le front-end)."""
    total = 2
    working = 0

    if check_gmail_status():
        working += 1
    
    if check_calendar_status():
        working += 1

    return jsonify({
        "success": True,
        "summary": {
            "total": total,
            "working": working
        }
    })

# =========================================================================
# 5. EXÉCUTION
# =========================================================================

if __name__ == '__main__':
    # Initialisation du fichier client_secrets si manquant pour les tests
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print("!!! ATTENTION !!! Le fichier 'client_secrets.json' est manquant.")
        print("Veuillez le créer avec vos identifiants Google Cloud pour les fonctionnalités Gmail/Calendar.")
        
    # Ceci n'est utilisé que pour le développement local, Gunicorn s'en charge en production.
    app.run(debug=True)
