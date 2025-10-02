#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOOLS.PY - Fonctions externes utilisées par les agents Gemini
Version: STABLE POSTGRESQL + Worker Logic
"""

import os
import json
import logging
from datetime import datetime, timedelta
import base64
from email.mime.text import MIMEText
import psycopg2 
from urllib.parse import urlparse

# Librairies Google API
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configuration du logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

# --- Configuration Gmail API ---
TOKEN_FILE = 'token_gmail.json'
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
]

# --- Nouvelle Fonction de Connexion DB ---
def get_db_connection():
    """Établit une connexion à PostgreSQL en utilisant DATABASE_URL."""
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        # Laisser l'exception se propager
        raise EnvironmentError("Base de données non configurée.")

    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        sslmode='require' 
    )

# --- Fonctions Utilitaires Gmail API (Le reste du code reste le même) ---
# ... (get_gmail_service, create_message, send_message) ...
def get_gmail_service():
    """
    Charge le jeton d'accès depuis token_gmail.json, rafraîchit
    le jeton si nécessaire, puis retourne l'objet de service Gmail API.
    """
    creds = None
    
    if not os.path.exists(TOKEN_FILE):
        logger.error(f"Fichier de jeton manquant: {TOKEN_FILE}")
        return None

    try:
        # Charge les identifiants depuis le fichier token_gmail.json
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
        
        # Si les identifiants sont invalides ou expirés et qu'un refresh_token est présent, rafraîchir.
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                logger.info("Jeton Gmail expiré. Tentative de rafraîchissement...")
                creds.refresh(Request())
            else:
                logger.error("Jeton Gmail invalide ou sans refresh_token valide.")
                return None
        
        # Sauvegarde du jeton rafraîchi
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
        service = build('gmail', 'v1', credentials=creds)
        return service
        
    except Exception as e:
        logger.error(f"Erreur lors de la construction du service Gmail: {e}")
        return None

def create_message(sender: str, to: str, subject: str, message_text: str) -> dict:
    """Crée un message encodé en base64 pour l'API Gmail."""
    try:
        message = MIMEText(message_text)
        message['to'] = to
        message['from'] = sender
        message['subject'] = subject
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw_message}
    except Exception as e:
        logger.error(f"Erreur lors de la création du message MIME: {e}")
        return None

def send_message(service, user_id, message_body: dict) -> bool:
    """Envoie le message à travers l'API Gmail."""
    try:
        (service.users().messages().send(userId=user_id, body=message_body)
           .execute())
        return True
    except HttpError as error:
        logger.error(f'Une erreur HTTP est survenue lors de l\'envoi: {error}')
        return False
    except Exception as e:
        logger.error(f'Une erreur inconnue est survenue lors de l\'envoi: {e}')
        return False

# --- Fonctions Outils de Productivité (Agent Alex & Sofia) ---

def add_calendar_event(title: str, start_time: str, duration_hours: float, notes: str) -> str:
    """
    Planifie un événement dans le calendrier Google.
    
    Args:
        title: Le titre de l'événement.
        start_time: Date et heure de début de l'événement (ex: '2025-10-05T10:00:00').
        duration_hours: Durée de l'événement en heures (ex: 1.5 pour 1h30).
        notes: Description ou notes de l'événement.
        
    Returns:
        Confirmation ou message d'erreur.
    """
    return f"Fonctionnalité d'ajout d'événement pour {title} planifiée. REMARQUE: L'API Google Calendar n'est pas encore implémentée dans cette version."

def check_priority_mail(query: str) -> str:
    """
    Recherche les e-mails entrants importants (par exemple, de la part d'un contact spécifique ou avec un sujet précis).
    
    Args:
        query: Requête de recherche d'e-mail (ex: 'e-mails non lus de Pierre' ou 'sujet:urgent').
        
    Returns:
        Résumé des e-mails trouvés ou message d'absence d'e-mails.
    """
    return f"Fonctionnalité de vérification des e-mails pour la requête '{query}' en cours de développement."

def schedule_email_alert(recipient: str, subject: str, body: str, scheduled_date_str: str) -> str:
    """
    Planifie l'envoi d'un e-mail pour une date et heure future. Si la date est immédiatement proche, l'e-mail est envoyé directement.
    
    Args:
        recipient: Adresse e-mail du destinataire.
        subject: Sujet de l'e-mail.
        body: Corps de l'e-mail.
        scheduled_date_str: Date et heure de l'envoi (format ISO 8601, ex: '2025-10-05T10:00:00').
        
    Returns:
        Confirmation de planification ou d'envoi immédiat.
    """
    try:
        scheduled_date = datetime.fromisoformat(scheduled_date_str)
        now = datetime.now()
        
        # 1. Tenter l'envoi immédiat si l'heure est dans le passé ou dans les 5 prochaines minutes.
        if scheduled_date <= now + timedelta(minutes=5):
            service = get_gmail_service()
            if not service:
                return "Échec de l'envoi immédiat : Le service Gmail n'a pas pu être initialisé. Vérifiez votre fichier token_gmail.json."

            message_body = create_message('me', recipient, subject, body)
            
            if message_body and send_message(service, 'me', message_body):
                return f"E-mail à {recipient} (Sujet: {subject}) envoyé immédiatement avec succès."
            else:
                logger.warning("L'envoi immédiat a échoué. Planification de la tâche dans la DB.")
                pass # Poursuivre vers la planification en DB
                
        # 2. Planification en DB (PostgreSQL)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # NOTE: Utilisation de %s pour les paramètres et le type TIMESTAMP de PSQL
        cursor.execute('''
            INSERT INTO scheduled_tasks (task_type, recipient, subject, body, scheduled_date)
            VALUES (%s, %s, %s, %s, %s)
        ''', ('email_alert', recipient, subject, body, scheduled_date.isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Tâche e-mail planifiée pour {scheduled_date_str}")
        return f"La tâche d'envoi d'e-mail à {recipient} (Sujet: {subject}) a été planifiée pour le {scheduled_date_str} et sera envoyée au prochain cycle de vérification du serveur. Le processus de planification est réussi."
        
    except Exception as e:
        logger.error(f"Erreur lors de la planification de la tâche : {e}")
        return f"Une erreur s'est produite lors de l'enregistrement de la tâche planifiée : {str(e)}"

# --- Fonction pour le Worker d'Arrière-Plan (CRON) ---

def run_scheduled_sender():
    """
    Fonction à exécuter périodiquement par un worker d'arrière-plan.
    Elle lit la DB PostgreSQL et envoie les messages planifiés.
    """
    logger.info("Démarrage du cycle de vérification des e-mails planifiés.")
    
    # Tentative d'initialisation du service Gmail
    service = get_gmail_service()
    if not service:
        logger.error("Impossible d'obtenir le service Gmail pour le worker. Vérifiez le token.")
        return
        
    # Tentative de connexion PostgreSQL
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
    except Exception as e:
        logger.error(f"Erreur de connexion PostgreSQL pour le worker: {e}")
        return


    # Sélectionner les tâches en attente qui sont passées
    now = datetime.now().isoformat()
    cursor.execute('''
        SELECT id, recipient, subject, body 
        FROM scheduled_tasks 
        WHERE task_type = 'email_alert' AND status = 'pending' AND scheduled_date <= %s
    ''', (now,))
    
    tasks = cursor.fetchall()

    if tasks:
        logger.info(f"Traitement de {len(tasks)} e-mails planifiés en attente...")
        
    for task_id, recipient, subject, body in tasks:
        message_body = create_message('me', recipient, subject, body)
        
        if message_body:
            sent = send_message(service, 'me', message_body)
            
            if sent:
                # Mettre à jour le statut dans la DB si l'envoi réussit
                cursor.execute('''
                    UPDATE scheduled_tasks 
                    SET status = 'sent', sent_at = NOW()
                    WHERE id = %s
                ''', (task_id,))
                conn.commit()
                logger.info(f"E-mail planifié ID {task_id} envoyé avec succès à {recipient}.")
            else:
                # L'envoi a échoué. On ne change pas le statut pour réessayer plus tard.
                logger.warning(f"Échec d'envoi de l'e-mail planifié ID {task_id}.")

    conn.close()
    logger.info("Fin du cycle de vérification des e-mails planifiés.")


# --- Mapping des Outils pour Gemini ---

AVAILABLE_TOOLS = {
    'add_calendar_event': add_calendar_event,
    'check_priority_mail': check_priority_mail,
    'schedule_email_alert': schedule_email_alert
}
