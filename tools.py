#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools.py - Fichier de déclaration des fonctions (Function Calling) pour les agents WaveAI.

Contient la logique métier (base de données, Gmail, etc.) qui peut être appelée par l'agent Gemini.
"""

import os
import json
import logging
from datetime import datetime, timezone
import base64
from email.mime.text import MIMEText
from typing import List, Dict, Any, Union

# **IMPORTS GMAIL CRITIQUES**
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    # Ce bloc sera exécuté si les bibliothèques Google sont manquantes
    print("ATTENTION: Les bibliothèques Google (google-auth-oauthlib, google-api-python-client) ne sont pas installées. Les outils Gmail ne fonctionneront pas.")
    # Définir des valeurs par défaut pour éviter les plantages
    Credentials = None
    build = lambda *args, **kwargs: None
    HttpError = Exception


# -- Configuration et Logging --
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Si vous utilisez un client ID/Secret pour l'authentification (ce qui est recommandé pour OAuth)
CLIENT_SECRET_FILE = 'client_secret.json'
TOKEN_FILE = 'token_gmail.json'
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# -- Base de données (PostgreSQL) - Similaire à app.py --
import psycopg2
from urllib.parse import urlparse

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Crée et retourne une connexion à la base de données PostgreSQL."""
    if not DATABASE_URL:
        # Dans un contexte tools.py, on peut juste retourner None si l'app.py gère le fallback
        raise Exception("DATABASE_URL non défini dans tools.py.")
    
    result = urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    return conn

# -- GESTION DE L'AUTHENTIFICATION GMAIL --

def load_gmail_credentials() -> Union[Credentials, None]:
    """Charge les identifiants depuis token_gmail.json, ou démarre le flux OAuth si nécessaire."""
    creds = None
    
    # Le fichier token_gmail.json stocke les jetons d'accès et de rafraîchissement de l'utilisateur.
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.error(f"Erreur lors du chargement des jetons depuis {TOKEN_FILE}: {e}")
            creds = None

    # Si les identifiants existent mais sont invalides ou expirés, et qu'il y a un jeton de rafraîchissement
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Sauvegarde des jetons rafraîchis pour le prochain démarrage
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
            logger.info("Jetons Gmail rafraîchis et sauvegardés.")
            
        except Exception as e:
            logger.error(f"Échec du rafraîchissement des jetons Gmail. L'utilisateur doit se réauthentifier. Erreur: {e}")
            return None # Échec du rafraîchissement
            
    # Si les identifiants sont manquants ou invalides et qu'ils ne peuvent pas être rafraîchis
    if not creds or not creds.valid:
        logger.warning("Jeton Gmail invalide ou manquant. L'envoi d'e-mail échouera.")
        # Dans un environnement de serveur, on ne peut pas démarrer le flux d'authentification ici.
        # L'application doit avoir une route /auth/gmail pour gérer cela.
        return None 

    return creds

def create_message_base64(to, subject, message_text):
    """Crée un message MIME et l'encode en base64 pour l'API Gmail."""
    message = MIMEText(message_text, 'html')
    # Gmail API utilise 'me' comme expéditeur (l'utilisateur authentifié)
    message['to'] = to 
    message['subject'] = subject
    # L'API Gmail attend un message RFC 2822
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}


# -- DÉCLARATION DES FONCTIONS D'OUTILS --

def schedule_email_alert(recipient_email: str, subject: str, body: str, scheduled_date_str: str) -> str:
    """
    Planifie l'envoi d'un e-mail à une date et heure spécifique.
    
    Args:
        recipient_email (str): L'adresse e-mail du destinataire.
        subject (str): Le sujet de l'e-mail.
        body (str): Le corps de l'e-mail (peut contenir du HTML simple).
        scheduled_date_str (str): La date et l'heure de l'envoi (Format: YYYY-MM-DD HH:MM).
        
    Returns:
        str: Un message confirmant la planification ou une erreur.
    """
    try:
        # Convertir la chaîne de date en objet datetime
        scheduled_date = datetime.strptime(scheduled_date_str, '%Y-%m-%d %H:%M')
        
        # ⚠️ Vérification : Si l'envoi est immédiat ou pour une date dans le futur proche (< 5 min), l'envoyer immédiatement
        # Note : Dans cette architecture simple, nous planifions tout en DB ou envoyons immédiatement si 'maintenant'
        if scheduled_date < datetime.now() + timezone.timedelta(minutes=5):
            return send_email_immediate(recipient_email, subject, body)
        
        # 1. Connexion à la DB
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 2. Insertion dans la table des tâches
            cursor.execute(
                """
                INSERT INTO scheduled_tasks (task_type, recipient, subject, body, scheduled_date, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                RETURNING id;
                """,
                ('email', recipient_email, subject, body, scheduled_date)
            )
            task_id = cursor.fetchone()[0]
            conn.commit()
            
            # 3. Confirmation
            return f"L'e-mail a été planifié avec succès pour le {scheduled_date_str} (UTC). Identifiant de la tâche : {task_id}"

    except ValueError:
        # Erreur de format de date
        return f"Erreur: Le format de la date doit être 'YYYY-MM-DD HH:MM'. Vous avez fourni : {scheduled_date_str}"
    except Exception as e:
        logger.error(f"Erreur DB lors de la planification de l'e-mail: {e}")
        return "Erreur interne: Impossible d'enregistrer la tâche dans la base de données. Veuillez vérifier la connexion DB."


def send_email_immediate(recipient: str, subject: str, body: str) -> str:
    """
    ENVOI CRITIQUE : Tente d'envoyer l'e-mail immédiatement via l'API Gmail.

    Args:
        recipient (str): Adresse e-mail du destinataire.
        subject (str): Sujet de l'e-mail.
        body (str): Corps de l'e-mail.

    Returns:
        str: Message de succès ou d'erreur détaillé pour le débogage.
    """
    creds = load_gmail_credentials()
    
    if not creds:
        # Le chargement des jetons a échoué (Jeton manquant/expiré/non rafraîchi)
        return "Échec de l'envoi: Les jetons d'authentification Gmail sont invalides ou manquants. L'utilisateur doit se réauthentifier via la console (fichier token_gmail.json)."

    try:
        service = build('gmail', 'v1', credentials=creds)
        message = create_message_base64(recipient, subject, body)

        # Envoi de l'e-mail
        service.users().messages().send(userId='me', body=message).execute()

        logger.info(f"E-mail envoyé immédiatement à {recipient}. Sujet: {subject}")
        return "L'e-mail a été envoyé avec succès immédiatement."
        
    except HttpError as e:
        # ⚠️ GESTION SPÉCIFIQUE DES ERREURS API GMAIL
        error_details = json.loads(e.content.decode())
        error_message = error_details.get('error', {}).get('message', 'Erreur HTTP inconnue de l\'API Gmail.')
        
        logger.error(f"Échec de l'envoi immédiat de l'e-mail (Gmail API): {error_message}")
        return f"Échec de l'envoi: Erreur de l'API Gmail (Code {e.resp.status}): {error_message}. Vérifiez le destinataire et le statut de votre jeton Gmail."

    except Exception as e:
        # ⚠️ GESTION DES ERREURS GÉNÉRALES (Connexion, etc.)
        logger.error(f"Échec de l'envoi immédiat de l'e-mail. Erreur non gérée: {e}")
        return f"Échec de l'envoi: Erreur inattendue ({type(e).__name__}): {str(e)}. Vérifiez les logs."

# -- DÉCLARATION DU CONTRAT API POUR GEMINI --

def get_tool_specs():
    """Retourne les spécifications de fonctions au format Google pour le Function Calling."""
    
    # Le rôle des autres outils est gardé abstrait car ils n'ont pas été modifiés.
    # Seul schedule_email_alert est détaillé ici.

    return [
        {
            "name": "schedule_email_alert",
            "description": "Planifie l'envoi d'un e-mail via Gmail à une date et heure précise (ou immédiatement si l'heure est 'maintenant'). L'agent doit fournir la date et l'heure au format YYYY-MM-DD HH:MM.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "recipient_email": {
                        "type": "string",
                        "description": "L'adresse e-mail complète du destinataire. Ex: 'jean.dupont@societe.com'"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Le sujet de l'e-mail."
                    },
                    "body": {
                        "type": "string",
                        "description": "Le corps de l'e-mail. Doit être complet et professionnel."
                    },
                    "scheduled_date_str": {
                        "type": "string",
                        "description": "La date et l'heure de l'envoi. Format requis: YYYY-MM-DD HH:MM (ex: 2025-12-31 10:30). L'agent doit utiliser l'heure actuelle du système fournie dans son prompt si l'utilisateur demande d'envoyer 'maintenant'."
                    }
                },
                "required": ["recipient_email", "subject", "body", "scheduled_date_str"]
            }
        },
        # TODO: Ajoutez ici les spécifications de vos autres outils (LinkedIn, Calendrier, etc.)
        # Exemple d'un outil fictif
        {
            "name": "find_linkedin_contact",
            "description": "Recherche et retourne un contact sur LinkedIn basé sur un nom et un rôle (outil de Lina).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "string", "description": "Nom complet du contact à rechercher."},
                    "role": {"type": "string", "description": "Rôle ou entreprise pour affiner la recherche."},
                },
                "required": ["name"]
            }
        }
    ]

# -- MAPPAGE DES OUTILS --
AVAILABLE_TOOLS = {
    "schedule_email_alert": schedule_email_alert,
    # Exemple d'un outil fictif
    # La fonction réelle doit exister
    "find_linkedin_contact": lambda name, role="": f"Recherche LinkedIn pour {name} ({role}) en cours..." 
}
