# worker.py
import os
import sqlite3
import logging
from datetime import datetime
import time

# Importer les outils
from tools import get_gmail_service, create_message

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Le chemin de la base de données doit correspondre à celui utilisé par tools.py
DATABASE_PATH = 'waveai.db' 

def process_scheduled_tasks():
    """Vérifie et exécute les tâches d'e-mail planifiées."""
    logger.info("Démarrage du cycle de vérification des e-mails planifiés...")
    
    try:
        # Se connecte à la DB SQLite (utilisée par tools.py)
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Récupère les tâches 'pending' dont la date est passée
        now = datetime.now().isoformat()
        cursor.execute("SELECT id, recipient, subject, body FROM scheduled_tasks WHERE status = 'pending' AND scheduled_date <= ?", (now,))
        tasks = cursor.fetchall()
        
        if not tasks:
            logger.info("Aucune tâche en attente à exécuter.")
            conn.close()
            return
            
        service = get_gmail_service()
        if not service:
            logger.error("Impossible d'obtenir le service Gmail. Les tâches ne peuvent pas être envoyées. Le token est probablement expiré.")
            conn.close()
            return

        for task_id, recipient, subject, body in tasks:
            try:
                logger.info(f"Envoi de l'e-mail planifié ID {task_id} à {recipient}...")
                
                # 1. Créer le message
                message = create_message('me', recipient, subject, body)
                
                # 2. Envoyer le message via l'API Gmail
                service.users().messages().send(userId='me', body=message).execute()
                
                # 3. Mettre à jour le statut dans la DB
                cursor.execute("UPDATE scheduled_tasks SET status = 'sent' WHERE id = ?", (task_id,))
                conn.commit()
                logger.info(f"E-mail planifié ID {task_id} envoyé avec succès à {recipient}.")
                
            except Exception as e:
                logger.error(f"Erreur lors de l'envoi de l'e-mail ID {task_id}: {e}")
                cursor.execute("UPDATE scheduled_tasks SET status = 'failed' WHERE id = ?", (task_id,))
                conn.commit()

        conn.close()
        logger.info("Fin du cycle de vérification du worker.")

    except Exception as e:
        logger.error(f"Erreur critique dans le worker: {e}")

if __name__ == '__main__':
    # Le worker s'exécute une fois pour Render (il est relancé par le service Worker)
    process_scheduled_tasks()
