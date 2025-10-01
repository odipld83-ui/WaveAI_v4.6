#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_gmail.py - Script utilitaire pour gérer le flux OAuth 2.0 pour l'API Gmail.
Génère le fichier 'token_gmail.json' requis pour que Alex fonctionne.
"""

import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Si vous modifiez ces scopes, supprimez 'token_gmail.json' et relancez.
# Gmail Read/Write, Send, et Modify (pour le cas où Alex aurait besoin de marquer comme lu)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly'
]

CREDENTIALS_FILE = 'credentials_gmail.json'
TOKEN_FILE = 'token_gmail.json'

def get_gmail_service():
    """
    Vérifie l'existence d'un jeton d'accès (token_gmail.json) ou lance le flux OAuth 2.0 
    pour obtenir les identifiants d'Alex.

    Returns:
        Un objet de service Gmail API (Resource) authentifié.
    """
    creds = None
    
    # 1. Vérifie si le jeton existe déjà
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # 2. Si le jeton n'existe pas, ou s'il a expiré
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Tente de rafraîchir le jeton s'il est expiré
            creds.refresh(Request())
        else:
            # Lance le flux d'authentification interactif
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Le fichier des identifiants Google '{CREDENTIALS_FILE}' est manquant. "
                    "Téléchargez-le depuis Google Cloud Console et renommez-le."
                )
                
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            # L'IA ouvrira un navigateur, demandera l'autorisation, puis générera le jeton.
            # L'utilisation d'allow_credentials_file_save=True est essentielle pour Render/portabilité.
            creds = flow.run_local_server(port=0) 
        
        # Sauvegarde le nouveau jeton pour les prochaines exécutions
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
            
    # Construit et retourne l'objet de service pour les appels d'API
    service = build('gmail', 'v1', credentials=creds)
    return service

if __name__ == '__main__':
    try:
        service = get_gmail_service()
        print(f"Authentification Gmail réussie. Service construit: {service.__class__.__name__}")
        
        # Test rapide : affiche le profil de l'utilisateur
        profile = service.users().getProfile(userId='me').execute()
        print(f"Connecté avec l'e-mail: {profile['emailAddress']}")
        
    except FileNotFoundError as e:
        print(f"ERREUR : {e}")
    except Exception as e:
        print(f"ERREUR lors de l'authentification : {e}")
        print("Veuillez vérifier vos identifiants et les scopes de l'API.")
