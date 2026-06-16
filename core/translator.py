"""Core Translator - Anticipation des intentions connues.

Dictionnaire bilingue français/anglais qui mappe le langage naturel
vers des intentions/commandes pré-résolues.

Si match fort → Core Intellect reçoit l'intention déjà résolue, le LLM valide uniquement.
Apprentissage continu : Core Intellect peut proposer des ajouts pour couvrir de nouveaux patterns.

Principe : Le traducteur pré-résout les intentions connues pour accélérer le traitement
et réduire la charge cognitive du LLM sur les tâches courantes.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.paths import JARVIS_DIR


# ============================================================================
# DICTIONNAIRE BILINGUE FRANÇAIS / ANGLAIS
# ============================================================================

TRADUCTEUR: Dict[str, Dict[str, str]] = {
    # === APPLICATIONS WINDOWS ===
    "ouvrir_chrome": {
        "fr": ["ouvre chrome", "lance chrome", "ouvrir chrome", "lancer chrome", "démarrer chrome", "demarrer chrome", "chrome"],
        "en": ["open chrome", "launch chrome", "start chrome", "chrome"],
        "intention": {"outil": "executer_commande", "args": {"commande": "start chrome.exe"}},
    },
    "fermer_chrome": {
        "fr": ["ferme chrome", "fermer chrome", "quitter chrome", "close chrome"],
        "en": ["close chrome", "quit chrome", "exit chrome"],
        "intention": {"outil": "executer_commande", "args": {"commande": "taskkill /f /im chrome.exe"}},
    },
    "ouvrir_firefox": {
        "fr": ["ouvre firefox", "lance firefox", "ouvrir firefox", "lancer firefox", "firefox"],
        "en": ["open firefox", "launch firefox", "start firefox", "firefox"],
        "intention": {"outil": "executer_commande", "args": {"commande": "start firefox.exe"}},
    },
    "ouvrir_edge": {
        "fr": ["ouvre edge", "lance edge", "ouvrir edge", "lancer edge", "edge", "microsoft edge"],
        "en": ["open edge", "launch edge", "start edge", "edge", "microsoft edge"],
        "intention": {"outil": "executer_commande", "args": {"commande": "start msedge.exe"}},
    },
    "ouvrir_explorateur": {
        "fr": ["ouvre l'explorateur", "ouvre explorateur", "lance explorateur", "explorateur de fichiers", "file explorer"],
        "en": ["open explorer", "launch explorer", "file explorer", "open file explorer"],
        "intention": {"outil": "executer_commande", "args": {"commande": "explorer.exe"}},
    },
    "ouvrir_terminal": {
        "fr": ["ouvre terminal", "ouvre cmd", "ouvre invite de commande", "lance terminal", "cmd", "invite de commande"],
        "en": ["open terminal", "open cmd", "launch cmd", "command prompt", "cmd"],
        "intention": {"outil": "executer_commande", "args": {"commande": "cmd.exe"}},
    },
    "ouvrir_powershell": {
        "fr": ["ouvre powershell", "lance powershell", "powershell"],
        "en": ["open powershell", "launch powershell", "powershell"],
        "intention": {"outil": "executer_powershell", "args": {"commande": "Start-Process powershell"}},
    },
    "ouvrir_notepad": {
        "fr": ["ouvre notepad", "lance notepad", "bloc notes", "notepad"],
        "en": ["open notepad", "launch notepad", "notepad"],
        "intention": {"outil": "executer_commande", "args": {"commande": "notepad.exe"}},
    },

    # === SYSTÈME ===
    "verifier_cpu": {
        "fr": ["cpu", "processeur", "utilisation cpu", "utilisation processeur", "charge cpu", "charge processeur"],
        "en": ["cpu", "processor", "cpu usage", "processor usage", "cpu load"],
        "intention": {"outil": "executer_powershell", "args": {"commande": "Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average | Select-Object -ExpandProperty Average"}},
    },
    "verifier_ram": {
        "fr": ["ram", "mémoire", "mémoire vive", "utilisation ram", "utilisation mémoire", "ram usage"],
        "en": ["ram", "memory", "ram usage", "memory usage"],
        "intention": {"outil": "executer_powershell", "args": {"commande": "Get-WmiObject Win32_OperatingSystem | Select-Object @{Name='MemoryUsage';Expression={[math]::round(($_.TotalVisibleMemorySize - $_.FreePhysicalMemory)*100/ $_.TotalVisibleMemorySize)}}"}},
    },
    "verifier_disque": {
        "fr": ["disque", "stockage", "espace disque", "espace disque libre", "disk space", "storage"],
        "en": ["disk", "storage", "disk space", "free disk space"],
        "intention": {"outil": "audit_stockage", "args": {}},
    },
    "liste_processus": {
        "fr": ["liste processus", "processus", "tâches", "tasks", "running processes"],
        "en": ["list processes", "processes", "tasks", "running processes"],
        "intention": {"outil": "executer_commande", "args": {"commande": "tasklist"}},
    },
    "tuer_processus": {
        "fr": ["tuer processus", "kill process", "terminer processus", "stop process"],
        "en": ["kill process", "terminate process", "stop process"],
        "intention": None,  # Nécessite argument (PID ou nom)
    },

    # === FICHIERS ET DOSSIERS ===
    "creer_dossier": {
        "fr": ["crée dossier", "créer dossier", "crée un dossier", "créer un dossier", "nouveau dossier", "create folder", "create directory"],
        "en": ["create folder", "create directory", "new folder", "make folder"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "creer_fichier": {
        "fr": ["crée fichier", "créer fichier", "crée un fichier", "créer un fichier", "nouveau fichier", "create file"],
        "en": ["create file", "new file", "make file"],
        "intention": None,  # Nécessite argument (chemin, contenu)
    },
    "lire_fichier": {
        "fr": ["lis fichier", "lire fichier", "ouvre fichier", "ouvrir fichier", "read file", "open file"],
        "en": ["read file", "open file", "view file"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "lister_dossier": {
        "fr": ["liste dossier", "lister dossier", "contenu dossier", "list folder", "folder contents", "dir"],
        "en": ["list folder", "folder contents", "dir", "ls"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "supprimer_fichier": {
        "fr": ["supprime fichier", "supprimer fichier", "efface fichier", "effacer fichier", "delete file", "remove file"],
        "en": ["delete file", "remove file", "erase file"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "supprimer_dossier": {
        "fr": ["supprime dossier", "supprimer dossier", "efface dossier", "effacer dossier", "delete folder", "remove folder"],
        "en": ["delete folder", "remove folder", "erase folder"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "copier_fichier": {
        "fr": ["copie fichier", "copier fichier", "copy file"],
        "en": ["copy file"],
        "intention": None,  # Nécessite arguments (source, destination)
    },
    "deplacer_fichier": {
        "fr": ["déplace fichier", "déplacer fichier", "move file"],
        "en": ["move file"],
        "intention": None,  # Nécessite arguments (source, destination)
    },
    "renommer_fichier": {
        "fr": ["renomme fichier", "renommer fichier", "rename file"],
        "en": ["rename file"],
        "intention": None,  # Nécessite arguments (chemin, nouveau nom)
    },

    # === STOCKAGE ===
    "audit_stockage": {
        "fr": ["audit stockage", "audit de stockage", "analyse stockage", "analyse de stockage", "storage audit", "disk audit"],
        "en": ["storage audit", "disk audit", "analyze storage"],
        "intention": {"outil": "audit_stockage", "args": {}},
    },
    "vider_temp": {
        "fr": ["vide temp", "vider temp", "nettoie temp", "nettoyer temp", "fichiers temporaires", "clear temp", "clean temp"],
        "en": ["clear temp", "clean temp", "temporary files"],
        "intention": {"outil": "vider_temp", "args": {}},
    },
    "vider_corbeille": {
        "fr": ["vide corbeille", "vider corbeille", "empty recycle bin", "clear recycle bin"],
        "en": ["empty recycle bin", "clear recycle bin"],
        "intention": {"outil": "vider_corbeille", "args": {}},
    },
    "fichiers_lourds": {
        "fr": ["fichiers lourds", "gros fichiers", "top fichiers", "largest files", "heavy files"],
        "en": ["largest files", "heavy files", "big files", "top files"],
        "intention": {"outil": "top_fichiers_lourds", "args": {"n": 10, "complet": False, "max_secondes": 15}},
    },
    "optimiser_stockage": {
        "fr": ["optimise stockage", "optimiser stockage", "nettoie stockage", "nettoyer stockage", "optimize storage"],
        "en": ["optimize storage", "clean storage"],
        "intention": {"outil": "terminer_tache", "args": {"resume": "Optimisation stockage: vide_temp → vider_corbeille → audit_stockage"}},
    },

    # === MÉMOIRE ET NOTES ===
    "noter": {
        "fr": ["note", "note ça", "noter", "sauvegarde note", "enregistre note", "note down", "save note"],
        "en": ["note", "note this", "save note", "remember"],
        "intention": None,  # Nécessite argument (contenu)
    },
    "lire_notes": {
        "fr": ["lire notes", "voir notes", "affiche notes", "mes notes", "read notes", "view notes", "show notes", "my notes"],
        "en": ["read notes", "view notes", "show notes", "my notes"],
        "intention": {"outil": "lire_notes", "args": {}},
    },
    "memoriser_contexte": {
        "fr": ["mémorise", "mémoriser", "sauvegarde contexte", "enregistre contexte", "remember", "save context"],
        "en": ["remember", "save context", "memorize"],
        "intention": None,  # Nécessite arguments (catégorie, clé, valeur)
    },
    "lire_contexte": {
        "fr": ["lire contexte", "voir contexte", "affiche contexte", "read context", "view context", "show context"],
        "en": ["read context", "view context", "show context"],
        "intention": None,  # Nécessite argument (catégorie optionnel)
    },
    "oublier_contexte": {
        "fr": ["oublie contexte", "oublier contexte", "supprime contexte", "forget context", "delete context"],
        "en": ["forget context", "delete context"],
        "intention": None,  # Nécessite arguments (catégorie, clé)
    },
    "preferences": {
        "fr": ["préférences", "préférence", "preferences", "pref"],
        "en": ["preferences", "prefs", "settings"],
        "intention": {"outil": "lire_preferences", "args": {}},
    },
    "memoriser_preference": {
        "fr": ["mémorise préférence", "mémoriser préférence", "save preference", "set preference"],
        "en": ["save preference", "set preference"],
        "intention": None,  # Nécessite arguments (clé, valeur)
    },

    # === RAPPELS ===
    "ajouter_rappel": {
        "fr": ["rappel", "ajoute rappel", "ajouter rappel", "nouveau rappel", "crée rappel", "reminder", "add reminder", "new reminder"],
        "en": ["reminder", "add reminder", "new reminder", "set reminder"],
        "intention": None,  # Nécessite arguments (message, heure)
    },
    "lire_rappels": {
        "fr": ["lire rappels", "voir rappels", "affiche rappels", "mes rappels", "read reminders", "view reminders", "show reminders", "my reminders"],
        "en": ["read reminders", "view reminders", "show reminders", "my reminders"],
        "intention": {"outil": "lire_rappels", "args": {}},
    },
    "supprimer_rappel": {
        "fr": ["supprime rappel", "supprimer rappel", "efface rappel", "delete reminder", "remove reminder"],
        "en": ["delete reminder", "remove reminder"],
        "intention": None,  # Nécessite argument (rappel_id)
    },
    "verifier_rappels": {
        "fr": ["vérifier rappels", "verifier rappels", "rappels dus", "check reminders", "due reminders"],
        "en": ["check reminders", "due reminders"],
        "intention": {"outil": "verifier_rappels", "args": {}},
    },

    # === AUTOMATISATIONS ===
    "ajouter_automatisation": {
        "fr": ["automatisation", "ajoute automatisation", "ajouter automatisation", "nouvelle automatisation", "automation", "add automation", "new automation"],
        "en": ["automation", "add automation", "new automation", "schedule"],
        "intention": None,  # Nécessite arguments (nom, outil, args, recurrence, heure)
    },
    "lister_automatisations": {
        "fr": ["lister automatisations", "voir automatisations", "automatisations actives", "list automations", "view automations", "active automations"],
        "en": ["list automations", "view automations", "active automations"],
        "intention": {"outil": "lister_automatisations", "args": {}},
    },
    "executer_automatisation": {
        "fr": ["exécuter automatisation", "executer automatisation", "lancer automatisation", "run automation", "execute automation"],
        "en": ["run automation", "execute automation", "launch automation"],
        "intention": None,  # Nécessite argument (automation_id ou nom)
    },

    # === SURVEILLANCE DOSSIERS ===
    "surveillance_dossiers": {
        "fr": ["surveillance dossiers", "surveillance de dossiers", "watchers", "folder surveillance", "folder watchers"],
        "en": ["folder surveillance", "folder watchers", "watchers"],
        "intention": {"outil": "lister_surveillance_dossiers", "args": {}},
    },
    "ajouter_surveillance": {
        "fr": ["ajoute surveillance", "ajouter surveillance", "nouvelle surveillance", "add surveillance", "new surveillance", "add watcher"],
        "en": ["add surveillance", "new surveillance", "add watcher"],
        "intention": None,  # Nécessite arguments (chemin, recurrence, heure)
    },
    "proposer_surveillance": {
        "fr": ["proposer surveillance", "suggérer surveillance", "suggest surveillance", "propose surveillance"],
        "en": ["suggest surveillance", "propose surveillance"],
        "intention": {"outil": "proposer_surveillance_dossiers", "args": {}},
    },

    # === ORGANISATION ===
    "analyser_organisation": {
        "fr": ["analyser organisation", "analyse organisation", "analyser dossier", "analyse dossier", "analyze organization", "analyze folder"],
        "en": ["analyze organization", "analyze folder", "check organization"],
        "intention": None,  # Nécessite argument (chemin)
    },
    "organiser_dossier": {
        "fr": ["organiser dossier", "ranger dossier", "organize folder", "organize directory", "tidy folder"],
        "en": ["organize folder", "organize directory", "tidy folder"],
        "intention": None,  # Nécessite argument (chemin)
    },

    # === COMMANDES PERSONNALISÉES ===
    "commandes_personnalisees": {
        "fr": ["commandes personnalisées", "mes commandes", "raccourcis", "custom commands", "my commands", "shortcuts"],
        "en": ["custom commands", "my commands", "shortcuts"],
        "intention": {"outil": "lister_commandes_personnalisees", "args": {}},
    },
    "ajouter_commande": {
        "fr": ["ajoute commande", "ajouter commande", "nouvelle commande", "add command", "new command"],
        "en": ["add command", "new command", "create command"],
        "intention": None,  # Nécessite arguments (nom, commande, description)
    },
    "executer_commande_perso": {
        "fr": ["exécuter commande", "executer commande", "lancer commande", "run command", "execute command"],
        "en": ["run command", "execute command", "launch command"],
        "intention": None,  # Nécessite argument (nom)
    },

    # === DATE ET HEURE ===
    "heure": {
        "fr": ["heure", "quelle heure", "il est quelle heure", "time", "what time", "current time"],
        "en": ["time", "what time", "current time"],
        "intention": {"outil": "executer_commande", "args": {"commande": "echo %time%"}},
    },
    "date": {
        "fr": ["date", "quelle date", "quel jour", "today", "what date", "what day"],
        "en": ["date", "what date", "what day", "today"],
        "intention": {"outil": "executer_commande", "args": {"commande": "echo %date%"}},
    },

    # === BILAN PROACTIF ===
    "bilan": {
        "fr": ["bilan", "état", "status", "rapport", "overview", "status report"],
        "en": ["status", "overview", "report", "status report"],
        "intention": {"outil": "bilan_proactif", "args": {"force": False, "niveau": "normal"}},
    },
    "bilan_complet": {
        "fr": ["bilan complet", "état complet", "full status", "complete overview"],
        "en": ["full status", "complete overview", "detailed report"],
        "intention": {"outil": "bilan_proactif", "args": {"force": True, "niveau": "complet"}},
    },

    # === NOTIFICATIONS ===
    "notifier": {
        "fr": ["notifie", "notification", "alerte", "notify", "notification", "alert"],
        "en": ["notify", "notification", "alert"],
        "intention": None,  # Nécessite arguments (titre, message, urgence)
    },
}


# ============================================================================
# FONCTIONS DE TRADUCTION
# ============================================================================

def traduire_message(message: str, langue: str = "fr") -> Optional[Tuple[str, Dict]]:
    """
    Traduit un message en intention pré-résolue si match fort trouvé.
    
    Args:
        message: Le message de l'utilisateur
        langue: La langue du message ("fr" ou "en")
    
    Returns:
        Tuple (cle_intention, dict_intention) si match fort, None sinon
    """
    message_lower = message.lower().strip()
    
    for cle, data in TRADUCTEUR.items():
        patterns = data.get(langue, [])
        
        for pattern in patterns:
            # Match exact (pour les commandes courtes)
            if message_lower == pattern.lower():
                if data["intention"]:
                    return (cle, data["intention"].copy())
            
            # Match partiel (pour les phrases plus longues)
            if pattern.lower() in message_lower:
                if data["intention"]:
                    return (cle, data["intention"].copy())
    
    return None


def match_fort(message: str, langue: str = "fr") -> bool:
    """
    Détermine si le message a un match fort avec une intention connue.
    
    Un match fort est défini comme:
    - Le message contient un pattern exact ou très proche
    - Le pattern n'est pas ambigu (pas de mots-clés conversationnels)
    """
    message_lower = message.lower().strip()
    
    # Mots-clés conversationnels qui réduisent la force du match
    mots_conversationnels = {
        "fr": ["pourquoi", "comment", "qu'est-ce", "explique", "dis-moi", "raconte", "merci", "qui es-tu", "es-tu"],
        "en": ["why", "how", "what is", "explain", "tell me", "thanks", "who are you", "are you"],
    }
    
    # Si le message contient un mot conversationnel, ce n'est pas un match fort
    for mot in mots_conversationnels.get(langue, []):
        if mot in message_lower:
            return False
    
    # Chercher un match
    for cle, data in TRADUCTEUR.items():
        patterns = data.get(langue, [])
        
        for pattern in patterns:
            # Match exact = fort
            if message_lower == pattern.lower():
                return True
            
            # Match au début = fort
            if message_lower.startswith(pattern.lower()):
                return True
    
    return False


def proposer_ajout(message: str, langue: str = "fr") -> Optional[Dict]:
    """
    Propose un ajout au traducteur pour un pattern non couvert.
    
    Cette fonction est appelée par Core Intellect quand il détecte un pattern
    récurrent qui n'est pas couvert par le traducteur actuel.
    
    Args:
        message: Le message non couvert
        langue: La langue du message
    
    Returns:
        Dict avec la proposition d'ajout, ou None si pas de proposition pertinente
    """
    # Cette fonction sera enrichie par Core Intellect avec l'apprentissage continu
    # Pour l'instant, elle retourne None
    return None


def ajouter_traduction(cle: str, patterns_fr: List[str], patterns_en: List[str], intention: Dict) -> bool:
    """
    Ajoute une nouvelle entrée au traducteur.
    
    Cette fonction nécessite une confirmation de Carl-William avant écriture.
    
    Args:
        cle: La clé unique pour l'intention
        patterns_fr: Liste de patterns en français
        patterns_en: Liste de patterns en anglais
        intention: Dict avec "outil" et "args"
    
    Returns:
        True si ajout réussi, False sinon
    """
    # Cette fonction nécessite une confirmation utilisateur
    # Pour l'instant, elle retourne False (sécurité)
    # L'ajout réel se fera via l'outil modifier_traducteur() dans tools.py
    return False


def lire_traducteur() -> Dict:
    """
    Retourne le traducteur complet pour lecture libre.
    
    Returns:
        Le dictionnaire TRADUCTEUR complet
    """
    return TRADUCTEUR.copy()


def obtenir_stats_traducteur() -> Dict:
    """
    Retourne des statistiques sur le traducteur.
    
    Returns:
        Dict avec nombre d'entrées, patterns par langue, etc.
    """
    total_entrees = len(TRADUCTEUR)
    total_patterns_fr = sum(len(data.get("fr", [])) for data in TRADUCTEUR.values())
    total_patterns_en = sum(len(data.get("en", [])) for data in TRADUCTEUR.values())
    
    entrees_avec_intention = sum(1 for data in TRADUCTEUR.values() if data["intention"])
    entrees_sans_intention = total_entrees - entrees_avec_intention
    
    return {
        "total_entrees": total_entrees,
        "total_patterns_fr": total_patterns_fr,
        "total_patterns_en": total_patterns_en,
        "entrees_avec_intention": entrees_avec_intention,
        "entrees_sans_intention": entrees_sans_intention,
    }
