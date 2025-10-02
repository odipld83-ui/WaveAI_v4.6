#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WORKER.PY - Lanceur de la tâche d'envoi d'e-mails planifiés.
"""
import logging
from tools import run_scheduled_sender

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    logger.info("Démarrage du worker d'envoi d'e-mails planifiés...")
    run_scheduled_sender()
    logger.info("Fin du cycle de vérification du worker.")
