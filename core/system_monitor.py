"""System Monitor - Surveillance continue de l'état système."""

import psutil
import platform
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from capabilities import storage


def obtenir_etat_systeme_complet() -> Dict[str, Any]:
    """
    Obtient un état complet du système.
    
    Returns:
        Dict contenant toutes les métriques système.
    """
    return {
        "cpu": _obtenir_info_cpu(),
        "memoire": _obtenir_info_memoire(),
        "disque": _obtenir_info_disque(),
        "reseau": _obtenir_info_reseau(),
        "systeme": _obtenir_info_systeme(),
        "processus": _obtenir_info_processus(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def _obtenir_info_cpu() -> Dict[str, Any]:
    """Obtient les informations CPU."""
    return {
        "utilisation": psutil.cpu_percent(interval=1),
        "coeurs_physiques": psutil.cpu_count(logical=False),
        "coeurs_logiques": psutil.cpu_count(logical=True),
        "frequence": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
        "charge": [x / psutil.cpu_count() * 100 for x in psutil.getloadavg()] if hasattr(psutil, 'getloadavg') else []
    }


def _obtenir_info_memoire() -> Dict[str, Any]:
    """Obtient les informations mémoire."""
    memoire = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    return {
        "totale": memoire.total,
        "disponible": memoire.available,
        "utilisee": memoire.used,
        "pourcentage": memoire.percent,
        "swap_totale": swap.total,
        "swap_utilisee": swap.used,
        "swap_pourcentage": swap.percent
    }


def _obtenir_info_disque() -> Dict[str, Any]:
    """Obtient les informations disque."""
    disques = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disques.append({
                "device": partition.device,
                "mountpoint": partition.mountpoint,
                "type": partition.fstype,
                "totale": usage.total,
                "utilisee": usage.used,
                "libre": usage.free,
                "pourcentage": usage.percent
            })
        except (PermissionError, OSError):
            continue
    
    return {"partitions": disques}


def _obtenir_info_reseau() -> Dict[str, Any]:
    """Obtient les informations réseau."""
    try:
        # Adresses IP
        adresses = []
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    adresses.append({
                        "interface": interface,
                        "adresse": addr.address,
                        "masque": addr.netmask
                    })
        
        # Statistiques réseau
        io = psutil.net_io_counters()
        
        return {
            "adresses": adresses,
            "octets_envoyes": io.bytes_sent,
            "octets_recus": io.bytes_recv,
            "paquets_envoyes": io.packets_sent,
            "paquets_recus": io.packets_recv
        }
    except Exception:
        return {"adresses": [], "erreur": "Impossible d'obtenir les infos réseau"}


def _obtenir_info_systeme() -> Dict[str, Any]:
    """Obtient les informations système."""
    return {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processeur": platform.processor(),
        "hostname": socket.gethostname(),
        "uptime": _obtenir_uptime()
    }


def _obtenir_uptime() -> str:
    """Calcule le temps de fonctionnement du système."""
    try:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        jours = uptime.days
        heures, reste = divmod(uptime.seconds, 3600)
        minutes, secondes = divmod(reste, 60)
        return f"{jours}j {heures}h {minutes}m {secondes}s"
    except Exception:
        return "Inconnu"


def _obtenir_info_processus(limit: int = 10) -> List[Dict[str, Any]]:
    """Obtient les informations des processus les plus gourmands."""
    processus = []
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processus.append({
                    "pid": proc.info['pid'],
                    "nom": proc.info['name'],
                    "cpu": proc.info['cpu_percent'] or 0,
                    "memoire": proc.info['memory_percent'] or 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Trier par utilisation CPU
        processus.sort(key=lambda x: x['cpu'], reverse=True)
        return processus[:limit]
    except Exception:
        return []


def detecter_anomalies(etat_systeme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Détecte les anomalies dans l'état système.
    
    Returns:
        Liste d'anomalies détectées avec leur sévérité.
    """
    anomalies = []
    
    # Anomalies CPU
    cpu = etat_systeme.get("cpu", {})
    utilisation_cpu = cpu.get("utilisation", 0)
    if utilisation_cpu > 90:
        anomalies.append({
            "type": "cpu",
            "severite": "critique",
            "message": f"Utilisation CPU critique : {utilisation_cpu}%",
            "valeur": utilisation_cpu,
            "seuil": 90
        })
    elif utilisation_cpu > 75:
        anomalies.append({
            "type": "cpu",
            "severite": "avertissement",
            "message": f"Utilisation CPU élevée : {utilisation_cpu}%",
            "valeur": utilisation_cpu,
            "seuil": 75
        })
    
    # Anomalies mémoire
    memoire = etat_systeme.get("memoire", {})
    utilisation_memoire = memoire.get("pourcentage", 0)
    if utilisation_memoire > 90:
        anomalies.append({
            "type": "memoire",
            "severite": "critique",
            "message": f"Utilisation mémoire critique : {utilisation_memoire}%",
            "valeur": utilisation_memoire,
            "seuil": 90
        })
    elif utilisation_memoire > 80:
        anomalies.append({
            "type": "memoire",
            "severite": "avertissement",
            "message": f"Utilisation mémoire élevée : {utilisation_memoire}%",
            "valeur": utilisation_memoire,
            "seuil": 80
        })
    
    # Anomalies disque
    disque = etat_systeme.get("disque", {})
    for partition in disque.get("partitions", []):
        utilisation_disque = partition.get("pourcentage", 0)
        if utilisation_disque > 95:
            anomalies.append({
                "type": "disque",
                "severite": "critique",
                "message": f"Espace disque critique sur {partition['mountpoint']} : {utilisation_disque}%",
                "valeur": utilisation_disque,
                "seuil": 95,
                "mountpoint": partition['mountpoint']
            })
        elif utilisation_disque > 85:
            anomalies.append({
                "type": "disque",
                "severite": "avertissement",
                "message": f"Espace disque faible sur {partition['mountpoint']} : {utilisation_disque}%",
                "valeur": utilisation_disque,
                "seuil": 85,
                "mountpoint": partition['mountpoint']
            })
    
    return anomalies


def enregistrer_etat_systeme(etat_systeme: Dict[str, Any]) -> None:
    """
    Enregistre l'état système dans la mémoire pour historique.
    
    Args:
        etat_systeme: L'état système à enregistrer
    """
    data = normaliser_memoire(charger_memoire())
    
    historique_systeme = data.setdefault("historique_systeme", [])
    historique_systeme.append({
        "timestamp": etat_systeme.get("timestamp"),
        "cpu": etat_systeme.get("cpu", {}).get("utilisation", 0),
        "memoire": etat_systeme.get("memoire", {}).get("pourcentage", 0),
        "disque": etat_systeme.get("disque", {}).get("partitions", [{}])[0].get("pourcentage", 0) if etat_systeme.get("disque", {}).get("partitions") else 0
    })
    
    # Garder seulement les 1000 derniers enregistrements
    data["historique_systeme"] = historique_systeme[-1000:]
    
    sauvegarder_memoire(data)


def generer_rapport_systeme() -> str:
    """
    Génère un rapport système complet.
    
    Returns:
        Description textuelle de l'état système.
    """
    etat = obtenir_etat_systeme_complet()
    anomalies = detecter_anomalies(etat)
    
    lignes = ["=== RAPPORT SYSTÈME ==="]
    lignes.append(f"Timestamp : {etat.get('timestamp')}")
    
    # CPU
    cpu = etat.get("cpu", {})
    lignes.append(f"\nCPU : {cpu.get('utilisation', 0):.1f}%")
    lignes.append(f"  Cœurs : {cpu.get('coeurs_physiques', 0)} physiques, {cpu.get('coeurs_logiques', 0)} logiques")
    
    # Mémoire
    memoire = etat.get("memoire", {})
    lignes.append(f"\nMémoire : {memoire.get('pourcentage', 0):.1f}%")
    lignes.append(f"  Totale : {memoire.get('totale', 0) / (1024**3):.1f} GB")
    lignes.append(f"  Utilisée : {memoire.get('utilisee', 0) / (1024**3):.1f} GB")
    
    # Disque
    disque = etat.get("disque", {})
    lignes.append(f"\nDisque :")
    for partition in disque.get("partitions", []):
        lignes.append(f"  {partition['mountpoint']} : {partition['pourcentage']:.1f}%")
        lignes.append(f"    Libre : {partition['libre'] / (1024**3):.1f} GB / {partition['totale'] / (1024**3):.1f} GB")
    
    # Réseau
    reseau = etat.get("reseau", {})
    lignes.append(f"\nRéseau :")
    for addr in reseau.get("adresses", [])[:3]:
        lignes.append(f"  {addr['interface']} : {addr['adresse']}")
    
    # Système
    systeme = etat.get("systeme", {})
    lignes.append(f"\nSystème :")
    lignes.append(f"  OS : {systeme.get('os')} {systeme.get('release')}")
    lignes.append(f"  Uptime : {systeme.get('uptime')}")
    
    # Anomalies
    if anomalies:
        lignes.append(f"\n⚠️  ANOMALIES DÉTECTÉES ({len(anomalies)}) :")
        for anomalie in anomalies:
            severite_emoji = {"critique": "🔴", "avertissement": "🟡"}.get(anomalie.get("severite"), "🟡")
            lignes.append(f"  {severite_emoji} {anomalie['message']}")
    else:
        lignes.append("\n✅ Aucune anomalie détectée")
    
    return "\n".join(lignes)


def surveiller_systeme_continu(duree_secondes: int = 60, intervalle_secondes: int = 5) -> List[Dict[str, Any]]:
    """
    Surveille le système en continu sur une période donnée.
    
    Args:
        duree_secondes: Durée de surveillance en secondes
        intervalle_secondes: Interventre les mesures en secondes
        
    Returns:
        Liste des états système enregistrés
    """
    import time
    
    etats = []
    debut = datetime.now()
    fin = debut + timedelta(seconds=duree_secondes)
    
    while datetime.now() < fin:
        etat = obtenir_etat_systeme_complet()
        etats.append(etat)
        enregistrer_etat_systeme(etat)
        time.sleep(intervalle_secondes)
    
    return etats


def obtenir_tendances_systeme(heures: int = 24) -> Dict[str, Any]:
    """
    Analyse les tendances système sur une période donnée.
    
    Args:
        heures: Nombre d'heures à analyser
        
    Returns:
        Tendances détectées
    """
    data = charger_memoire()
    historique = data.get("historique_systeme", [])
    
    if not historique:
        return {"message": "Pas assez de données pour analyser les tendances"}
    
    # Filtrer les données récentes
    date_limite = datetime.now() - timedelta(hours=heures)
    donnees_recentes = []
    
    for entree in historique:
        try:
            timestamp = datetime.strptime(entree.get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
            if timestamp >= date_limite:
                donnees_recentes.append(entree)
        except (ValueError, TypeError):
            continue
    
    if not donnees_recentes:
        return {"message": f"Aucune donnée disponible pour les {heures} dernières heures"}
    
    # Calculer les moyennes
    cpu_moyen = sum(d.get("cpu", 0) for d in donnees_recentes) / len(donnees_recentes)
    memoire_moyenne = sum(d.get("memoire", 0) for d in donnees_recentes) / len(donnees_recentes)
    disque_moyen = sum(d.get("disque", 0) for d in donnees_recentes) / len(donnees_recentes)
    
    # Détecter les tendances
    premiere_moitie = donnees_recentes[:len(donnees_recentes)//2]
    seconde_moitie = donnees_recentes[len(donnees_recentes)//2:]
    
    cpu_tendance = "stable"
    if premiere_moitie and seconde_moitie:
        cpu_premier = sum(d.get("cpu", 0) for d in premiere_moitie) / len(premiere_moitie)
        cpu_second = sum(d.get("cpu", 0) for d in seconde_moitie) / len(seconde_moitie)
        if cpu_second > cpu_premier + 10:
            cpu_tendance = "en hausse"
        elif cpu_second < cpu_premier - 10:
            cpu_tendance = "en baisse"
    
    return {
        "periode_analysee": f"{heures} heures",
        "nombre_donnees": len(donnees_recentes),
        "cpu_moyen": round(cpu_moyen, 1),
        "memoire_moyenne": round(memoire_moyenne, 1),
        "disque_moyen": round(disque_moyen, 1),
        "cpu_tendance": cpu_tendance,
        "timestamp_analyse": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
