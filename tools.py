#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOOLS.PY - Fonctions externes utilisées par les agents Gemini
Version: Gmail API OAuth 2.0 (Réel) - Utilise SQLite pour la planification
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta
import base64
from email.mime.text import MIMEText

# Librairies Google API
# Nécessite google-auth-oauthlib et google-api-python-client
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Configuration du logging
logger = logging.getLogger(__name__)

# --- Configuration Gmail API ---
TOKEN_FILE = 'token_gmail.json' 
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
]

# NOTE: Cette DB est SQLite. Idéalement, elle devrait être Postgre pour la cohérence
DATABASE_PATH = 'waveai.db' 

# --- Fonction Utilitaires pour Gmail ---

def get_gmail_service():
    """
    Charge le jeton d'accès depuis token_gmail.json et rafraîchit
    le jeton si nécessaire, puis retourne l'objet de service Gmail API.
    """
    creds = None
    
    if not os.path.exists(TOKEN_FILE):
        logger.error(f"Fichier de jeton manquant: {TOKEN_FILE}")
        return None

    try:
        # Charge les identifiants depuis le fichier token_gmail.json
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GMAIL_SCOPES)
        
        # Si les identifiants sont valides ou peuvent être rafraîchis
        if not creds.valid:
            if creds.refresh_token:
                logger.info("Jeton Gmail expiré. Tentative de rafraîchissement...")
                creds.refresh(Request())
                # Sauvegarder le nouveau jeton si rafraîchi
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            else:
                logger.error("Jeton Gmail invalide et impossible à rafraîchir (pas de refresh_token).")
                return None
        
        if creds.valid:
            # Construit le service Gmail
            service = build('gmail', 'v1', credentials=creds)
            return service
            
        logger.error("Jeton Gmail invalide après tentative de rafraîchissement.")
        return None

    except Exception as e:
        logger.error(f"Erreur lors de la construction du service Gmail: {e}")
        return None

def create_message(sender, to, subject, message_text):
    """Crée un message pour l'API Gmail."""
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}


# --- Définition des Outils pour les Agents ---

def add_calendar_event(title: str, start_time: str, duration_minutes: int) -> str:
    """
    Planifie un événement dans le calendrier Google.
    
    Args:
        title (str): Titre de l'événement.
        start_time (str): Date et heure de début de l'événement au format ISO 8601 (ex: '2025-10-15T09:00:00').
        duration_minutes (int): Durée de l'événement en minutes (doit être > 0).
    
    Returns:
        str: Message de confirmation ou d'erreur.
    """
    try:
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00')) # Gère le Z pour UTC
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        return (f"L'événement '{title}' a été planifié. Il commencera le "
                f"{start_dt.strftime('%Y-%m-%d à %H:%M')} et se terminera à "
                f"{end_dt.strftime('%H:%M')}. (Simulation, l'intégration complète est requise).")
        
    except ValueError:
        return "Erreur: Le format de l'heure de début doit être ISO 8601 (AAAA-MM-JJTHH:MM:SS)."
    except Exception as e:
        return f"Erreur inattendue lors de la planification de l'événement: {str(e)}"


def check_priority_mail(query: str = 'is:unread category:primary') -> str:
    """
    Vérifie les e-mails dans la boîte de réception Gmail en utilisant une requête de recherche.
    
    Args:
        query (str): La requête de recherche Gmail (ex: 'from:support@domain.com subject:urgent'). 
    
    Returns:
        str: Un résumé des e-mails trouvés ou un message d'absence d'e-mails.
    """
    service = get_gmail_service()
    if not service:
        return "Impossible de se connecter au service Gmail. Veuillez vérifier le fichier token_gmail.json (jeton expiré ou révoqué)."

    try:
        response = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = response.get('messages', [])
        
        if not messages:
            return f"Aucun e-mail trouvé correspondant à la requête '{query}'."
        
        summary = f"J'ai trouvé {len(messages)} e-mail(s) correspondant à la requête '{query}':\n"
        
        for msg in messages:
            msg_id = msg['id']
            message_detail = service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
            
            headers = {h['name']: h['value'] for h in message_detail['payload']['headers']}
            summary += (f" - De: {headers.get('From', 'Inconnu')} | "
                        f"Sujet: {headers.get('Subject', 'Pas de sujet')} | "
                        f"Date: {headers.get('Date', 'N/A')}\n")
                        
        return summary
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des e-mails: {e}")
        return f"Une erreur s'est produite lors de la vérification des e-mails: {str(e)}"


def schedule_email_alert(recipient: str, subject: str, body: str, delay_minutes: int) -> str:
    """
    Planifie l'envoi d'un e-mail après un certain délai.
    
    Args:
        recipient (str): L'adresse e-mail du destinataire.
        subject (str): Le sujet de l'e-mail.
        body (str): Le corps du message.
        delay_minutes (int): Le délai avant l'envoi, en minutes (doit être > 0).
    
    Returns:
        str: Message de confirmation de la planification.
    """
    if delay_minutes <= 0:
        return "Erreur: Le délai en minutes doit être supérieur à zéro."
        
    scheduled_date = datetime.now() + timedelta(minutes=delay_minutes)
    scheduled_date_str = scheduled_date.strftime('%Y-%m-%d %H:%M:%S')

    try:
        # Utilisation de SQLite pour le worker.py
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # S'assurer que la table existe
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY,
                task_type TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                scheduled_date TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        ''')

        cursor.execute('''
            INSERT INTO scheduled_tasks (task_type, recipient, subject, body, scheduled_date)
            VALUES (?, ?, ?, ?, ?)
        ''', ('email_alert', recipient, subject, body, scheduled_date.isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Tâche e-mail planifiée pour {scheduled_date_str}")
        return (f"La tâche d'envoi d'e-mail à {recipient} (Sujet: {subject}) a été planifiée pour le "
                f"{scheduled_date_str}. Le worker d'arrière-plan s'occupera de l'envoi.")
        
    except Exception as e:
        logger.error(f"Erreur lors de la planification de la tâche dans la DB: {e}")
        return f"Une erreur s'est produite lors de l'enregistrement de la tâche planifiée : {str(e)}"


# --- Dictionnaire des Outils ---

AVAILABLE_TOOLS = {
    'add_calendar_event': add_calendar_event,
    'check_priority_mail': check_priority_mail,
    'schedule_email_alert': schedule_email_alert
}
