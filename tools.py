#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOOLS.PY - Fonctions externes utilisées par les agents Gemini
Version: Gmail API OAuth 2.0 (Réel)
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta
import base64
from email.mime.text import MIMEText

# Librairies Google API
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Configuration du logging
logger = logging.getLogger(__name__)

# --- Configuration Gmail API ---
TOKEN_FILE = 'token_gmail.json'
# On utilise les scopes de Gmail pour la portabilité
GMAIL_SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
]

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
        
        # Le jeton d'accès (token) peut être nul dans notre fichier, 
        # mais le refresh_token est présent.
        # On force le rafraîchissement si le jeton n'est pas encore valide ou a expiré.
        if not creds.valid or not creds.token:
            if creds.refresh_token:
                logger.info("Rafraîchissement du jeton d'accès Gmail...")
                creds.refresh(Request())
            else:
                logger.error("Jeton de rafraîchissement (refresh_token) manquant ou invalide.")
                return None
        
        # Sauvegarde le jeton d'accès (token) rafraîchi dans le fichier pour les prochaines exécutions
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
        # Construit et retourne l'objet de service
        service = build('gmail', 'v1', credentials=creds)
        return service
        
    except Exception as e:
        logger.error(f"Erreur lors de la construction du service Gmail: {e}")
        return None

def create_message(sender, to, subject, message_text):
    """Crée le corps de l'e-mail au format MIME."""
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    # Encodage en Base64 URL Safe, requis par l'API Gmail
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}

# --- Outils Utilisés par les Agents ---

def add_calendar_event(title: str, date_str: str, duration_hours: float, notes: str) -> str:
    """
    Ajoute un événement au calendrier Google. Utile pour planifier des réunions, rappels ou tâches.
    :param title: Titre de l'événement (ex: "Réunion client").
    :param date_str: Date et heure de début au format YYYY-MM-DD HH:MM (ex: "2024-10-25 14:30").
    :param duration_hours: Durée de l'événement en heures (ex: 1.5).
    :param notes: Description ou notes de l'événement.
    :return: Confirmation de la planification ou message d'erreur.
    """
    # NOTE: L'implémentation de l'API Google Calendar n'est pas encore faite,
    # c'est pour l'instant une simulation.
    try:
        start_datetime = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        end_datetime = start_datetime + timedelta(hours=duration_hours)
        
        return f"Événement de calendrier SIMULÉ planifié ! Titre: {title}, de {start_datetime.strftime('%Y-%m-%d %H:%M')} à {end_datetime.strftime('%Y-%m-%d %H:%M')} (Durée: {duration_hours}h). Note: {notes}. REMARQUE: Nécessite l'intégration Google Calendar API."
    except ValueError:
        return f"Erreur de format de date. Utilisez le format YYYY-MM-DD HH:MM pour la date de début."


def check_priority_mail(query: str) -> str:
    """
    Vérifie les e-mails récents (dans la boîte de réception) qui correspondent à un critère de recherche spécifique.
    Utiliser des mots-clés pertinents (ex: 'urgent', 'facture', 'client A').
    :param query: Requête de recherche Gmail (ex: 'is:unread subject:urgent').
    :return: Un résumé du nombre d'e-mails trouvés ou un extrait.
    """
    service = get_gmail_service()
    if not service:
        return "Erreur d'authentification: Le service Gmail n'est pas disponible. Vérifiez le fichier token_gmail.json."

    try:
        # Recherche des messages
        # On utilise 'maxResults=5' pour ne pas surcharger l'API
        response = service.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = response.get('messages', [])
        
        if not messages:
            return f"Aucun e-mail trouvé pour la requête '{query}'."

        count = len(messages)
        first_subject = ""
        
        # Récupère le sujet du premier message pour donner un aperçu
        first_message_id = messages[0]['id']
        first_message_data = service.users().messages().get(userId='me', id=first_message_id, format='metadata', metadataHeaders=['Subject']).execute()
        
        headers = first_message_data.get('payload', {}).get('headers', [])
        for header in headers:
            if header['name'] == 'Subject':
                first_subject = header['value']
                break

        return f"J'ai trouvé {count} e-mails correspondant à la requête '{query}'. Le sujet du plus récent est: '{first_subject}'."
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des mails: {e}")
        return f"Une erreur technique est survenue lors de la vérification des e-mails: {str(e)}"


def schedule_email_alert(recipient: str, subject: str, body: str, scheduled_date_str: str) -> str:
    """
    Planifie l'envoi d'un e-mail à une date future. Si la date est passée ou immédiate, l'e-mail est envoyé immédiatement via Gmail API.
    :param recipient: Adresse e-mail du destinataire (ex: 'client@exemple.com').
    :param subject: Sujet de l'e-mail (ex: 'Rappel de renouvellement de licence').
    :param body: Corps du message (ex: 'Votre licence expire le...').
    :param scheduled_date_str: Date et heure d'envoi de l'e-mail au format YYYY-MM-DD HH:MM.
    :return: Confirmation de la planification ou de l'envoi.
    """
    try:
        scheduled_date = datetime.strptime(scheduled_date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return f"Erreur de format de date. Utilisez le format YYYY-MM-DD HH:MM pour la date d'envoi planifiée."
    
    # On considère immédiat si l'heure planifiée est dans le passé ou dans les 2 minutes
    if scheduled_date < (datetime.now() + timedelta(minutes=2)):
        
        service = get_gmail_service()
        if not service:
            return "Erreur d'authentification: Le service Gmail n'est pas disponible pour l'envoi immédiat. Vérifiez le fichier token_gmail.json."

        try:
            # Récupérer l'adresse de l'utilisateur connecté (le 'sender')
            profile = service.users().getProfile(userId='me').execute()
            sender_email = profile['emailAddress']
            
            # Créer et envoyer le message
            message = create_message(sender_email, recipient, subject, body)
            service.users().messages().send(userId='me', body=message).execute()
            
            logger.info(f"E-mail immédiat envoyé à {recipient} (Sujet: {subject})")
            return f"E-mail envoyé IMMÉDIATEMENT à {recipient} (Sujet: {subject}) via l'API Gmail depuis {sender_email}."
            
        except Exception as e:
            logger.error(f"Échec de l'envoi immédiat de l'e-mail via Gmail API: {e}")
            return f"Échec de l'envoi immédiat via l'API Gmail : {str(e)}. Vérifiez le statut de l'API."

    else:
        # Stockage dans la base de données pour envoi différé (au prochain démarrage)
        try:
            conn = sqlite3.connect('waveai.db')
            cursor = conn.cursor()
            
            # Assurer que la table existe (même si elle est dans app.py, on est plus sécurisé ici)
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
            return f"La tâche d'envoi d'e-mail à {recipient} (Sujet: {subject}) a été planifiée pour le {scheduled_date_str} et sera envoyée au prochain cycle de vérification du serveur. Le processus de planification est réussi."
            
        except Exception as e:
            logger.error(f"Erreur lors de la planification de la tâche dans la DB: {e}")
            return f"Une erreur s'est produite lors de l'enregistrement de la tâche planifiée : {str(e)}"


AVAILABLE_TOOLS = {
    'add_calendar_event': add_calendar_event,
    'check_priority_mail': check_priority_mail,
    'schedule_email_alert': schedule_email_alert
