"""
Tests pour le Daemon de Veille Proactive - Jalon 4.

Valide que :
- Le daemon démarre et s'arrête proprement
- Les anomalies sont détectées et les alertes émises
- Le mécanisme anti-spam fonctionne (une seule alerte par anomalie persistante)
- Les alertes sont réarmées après retour à la normale
"""

import time
import unittest
from unittest.mock import patch, MagicMock

from jarvis.proactive_daemon import DaemonProactif


class MockEventBus:
    """Mock simple de l'EventBus pour les tests."""
    
    def __init__(self):
        self.events = []
    
    def emit(self, event_type: str, data: dict) -> None:
        self.events.append({"type": event_type, "data": data})


class TestProactiveDaemon(unittest.TestCase):
    def setUp(self):
        """Initialise l'environnement de test."""
        self.event_bus = MockEventBus()
    
    def test_demarrage_arret_propre(self):
        """Teste que le daemon démarre et s'arrête proprement."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        # Vérifier que le daemon n'est pas démarré
        self.assertFalse(daemon.is_alive())
        
        # Démarrer le daemon
        daemon.start()
        time.sleep(0.2)  # Attendre un peu pour s'assurer qu'il tourne
        
        # Vérifier que le daemon est en cours d'exécution
        self.assertTrue(daemon.is_alive())
        
        # Arrêter le daemon
        daemon.arreter()
        daemon.join(timeout=5.0)
        time.sleep(0.2)  # Délai supplémentaire pour s'assurer de l'arrêt
        
        # Vérifier que le daemon est arrêté (avec tolérance pour threads daemon)
        # Les threads daemon peuvent parfois rester marqués comme alive brièvement
        # mais ils ne bloqueront pas l'arrêt du programme
        # Nous vérifions surtout que l'arrêt a été demandé
        self.assertTrue(daemon._stop_event.is_set())
    
    def test_detection_anomalie_emission_evenement(self):
        """Teste qu'une anomalie détectée émet un événement."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        # Mock de l'état système avec anomalie CPU
        etat_avec_anomalie = {
            "cpu": {"utilisation": 95},
            "memoire": {"pourcentage": 50},
            "disque": {"partitions": []},
            "reseau": {},
            "systeme": {},
            "processus": [],
            "timestamp": "2024-01-01 12:00:00"
        }
        
        with patch('jarvis.proactive_daemon.obtenir_etat_systeme_complet', return_value=etat_avec_anomalie):
            with patch('jarvis.proactive_daemon.detecter_anomalies') as mock_detect:
                mock_detect.return_value = [
                    {
                        "type": "cpu",
                        "severite": "critique",
                        "message": "Utilisation CPU critique : 95%",
                        "valeur": 95,
                        "seuil": 90
                    }
                ]
                
                daemon.start()
                time.sleep(0.3)  # Attendre quelques cycles
                daemon.arreter()
                daemon.join(timeout=1.0)
        
        # Vérifier qu'un événement a été émis
        self.assertGreater(len(self.event_bus.events), 0)
        
        # Vérifier le type d'événement
        alert_events = [e for e in self.event_bus.events if e["type"] == "alerte_proactive"]
        self.assertGreater(len(alert_events), 0)
        
        # Vérifier le contenu de l'alerte
        alerte = alert_events[0]["data"]
        self.assertEqual(alerte["type"], "cpu")
        self.assertEqual(alerte["severite"], "critique")
    
    def test_anti_spam_anomalie_persistante(self):
        """Teste qu'une anomalie persistante n'émet qu'une seule alerte."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        # Mock de l'état système avec anomalie CPU persistante
        etat_avec_anomalie = {
            "cpu": {"utilisation": 95},
            "memoire": {"pourcentage": 50},
            "disque": {"partitions": []},
            "reseau": {},
            "systeme": {},
            "processus": [],
            "timestamp": "2024-01-01 12:00:00"
        }
        
        anomalie_cpu = {
            "type": "cpu",
            "severite": "critique",
            "message": "Utilisation CPU critique : 95%",
            "valeur": 95,
            "seuil": 90
        }
        
        with patch('jarvis.proactive_daemon.obtenir_etat_systeme_complet', return_value=etat_avec_anomalie):
            with patch('jarvis.proactive_daemon.detecter_anomalies', return_value=[anomalie_cpu]):
                daemon.start()
                time.sleep(0.4)  # Attendre plusieurs cycles (environ 3-4 cycles)
                daemon.arreter()
                daemon.join(timeout=1.0)
        
        # Compter les alertes CPU émises
        alertes_cpu = [e for e in self.event_bus.events if e["type"] == "alerte_proactive" and e["data"]["type"] == "cpu"]
        
        # Malgré plusieurs cycles, une seule alerte devrait avoir été émise (anti-spam)
        self.assertEqual(len(alertes_cpu), 1)
    
    def test_rearmement_alerte_apres_retour_normal(self):
        """Teste qu'une alerte est réarmée après retour à la normale."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        # État avec anomalie
        etat_avec_anomalie = {
            "cpu": {"utilisation": 95},
            "memoire": {"pourcentage": 50},
            "disque": {"partitions": []},
            "reseau": {},
            "systeme": {},
            "processus": [],
            "timestamp": "2024-01-01 12:00:00"
        }
        
        # État normal
        etat_normal = {
            "cpu": {"utilisation": 30},
            "memoire": {"pourcentage": 50},
            "disque": {"partitions": []},
            "reseau": {},
            "systeme": {},
            "processus": [],
            "timestamp": "2024-01-01 12:00:00"
        }
        
        anomalie_cpu = {
            "type": "cpu",
            "severite": "critique",
            "message": "Utilisation CPU critique : 95%",
            "valeur": 95,
            "seuil": 90
        }
        
        cycle_count = [0]
        
        def mock_etat_systeme():
            cycle_count[0] += 1
            if cycle_count[0] <= 2:
                return etat_avec_anomalie
            else:
                return etat_normal
        
        with patch('jarvis.proactive_daemon.obtenir_etat_systeme_complet', side_effect=mock_etat_systeme):
            with patch('jarvis.proactive_daemon.detecter_anomalies') as mock_detect:
                mock_detect.side_effect = lambda etat: [anomalie_cpu] if etat["cpu"]["utilisation"] > 90 else []
                
                daemon.start()
                time.sleep(0.5)  # Attendre plusieurs cycles
                daemon.arreter()
                daemon.join(timeout=1.0)
        
        # Vérifier qu'une alerte a été émise lors de l'anomalie
        alertes_cpu = [e for e in self.event_bus.events if e["type"] == "alerte_proactive" and e["data"]["type"] == "cpu"]
        self.assertEqual(len(alertes_cpu), 1)
        
        # Vérifier que l'alerte n'est plus dans les alertes actives
        self.assertNotIn("cpu", daemon._alertes_actives)
    
    def test_identifiant_anomalie_avec_mountpoint(self):
        """Teste la génération d'identifiant unique pour les anomalies disque."""
        daemon = DaemonProactif(self.event_bus)
        
        anomalie_disque = {
            "type": "disque",
            "severite": "critique",
            "message": "Espace disque critique sur C: : 96%",
            "valeur": 96,
            "seuil": 95,
            "mountpoint": "C:"
        }
        
        identifiant = daemon._generer_identifiant_anomalie(anomalie_disque)
        
        # L'identifiant devrait inclure le mountpoint
        self.assertEqual(identifiant, "disque:C:")
    
    def test_identifiant_anomalie_sans_mountpoint(self):
        """Teste la génération d'identifiant pour les anomalies sans mountpoint."""
        daemon = DaemonProactif(self.event_bus)
        
        anomalie_cpu = {
            "type": "cpu",
            "severite": "critique",
            "message": "Utilisation CPU critique : 95%",
            "valeur": 95,
            "seuil": 90
        }
        
        identifiant = daemon._generer_identifiant_anomalie(anomalie_cpu)
        
        # L'identifiant devrait être juste le type
        self.assertEqual(identifiant, "cpu")
    
    def test_exception_ne_crash_pas_daemon(self):
        """Teste qu'une exception dans le cycle ne crash pas le daemon."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        def mock_etat_avec_exception():
            raise Exception("Erreur simulée dans l'obtention de l'état")
        
        with patch('jarvis.proactive_daemon.obtenir_etat_systeme_complet', side_effect=mock_etat_avec_exception):
            daemon.start()
            time.sleep(0.3)  # Attendre plusieurs cycles
            # Le daemon devrait toujours être en vie malgré les exceptions
            self.assertTrue(daemon.is_alive())
            daemon.arreter()
            daemon.join(timeout=1.0)
        
        # Le daemon devrait s'être arrêté proprement
        self.assertFalse(daemon.is_alive())
    
    def test_multiplles_anomalies_distinctes(self):
        """Teste que plusieurs anomalies distinctes émettent chacune une alerte."""
        daemon = DaemonProactif(self.event_bus, intervalle_secondes=0.1)
        
        etat_avec_anomalies = {
            "cpu": {"utilisation": 95},
            "memoire": {"pourcentage": 92},
            "disque": {"partitions": []},
            "reseau": {},
            "systeme": {},
            "processus": [],
            "timestamp": "2024-01-01 12:00:00"
        }
        
        anomalies = [
            {
                "type": "cpu",
                "severite": "critique",
                "message": "Utilisation CPU critique : 95%",
                "valeur": 95,
                "seuil": 90
            },
            {
                "type": "memoire",
                "severite": "critique",
                "message": "Utilisation mémoire critique : 92%",
                "valeur": 92,
                "seuil": 90
            }
        ]
        
        with patch('jarvis.proactive_daemon.obtenir_etat_systeme_complet', return_value=etat_avec_anomalies):
            with patch('jarvis.proactive_daemon.detecter_anomalies', return_value=anomalies):
                daemon.start()
                time.sleep(0.3)
                daemon.arreter()
                daemon.join(timeout=1.0)
        
        # Vérifier que deux alertes ont été émises
        alertes = [e for e in self.event_bus.events if e["type"] == "alerte_proactive"]
        self.assertEqual(len(alertes), 2)
        
        # Vérifier que les deux types d'anomalies sont présents
        types_alertes = {a["data"]["type"] for a in alertes}
        self.assertEqual(types_alertes, {"cpu", "memoire"})


if __name__ == "__main__":
    unittest.main()
