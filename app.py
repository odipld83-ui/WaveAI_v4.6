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
