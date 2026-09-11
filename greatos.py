# greatos.py
"""Point d'entrée unifié et Noyau (Kernel) de GreatOS.

Orchestre les 8 modules fondamentaux du Cahier des Charges GreatOS :
1. jarvis               : Interface conversationnelle & Voix
2. core_intellect       : Cerveau décisionnel & Cascade LLM
3. context_engine       : Conscience contextuelle & Mémoire
4. taskflow             : Automatisation des workflows & Outils
5. progress_tracker     : Suivi des objectifs & KPIs
6. datashield           : Sécurité multicouche & DEFCON
7. syncsphere           : Sauvegarde & Synchronisation locale
8. interface_morphique  : UI adaptative (FastAPI, Web, HUD)
"""

import sys
from pathlib import Path

# Assurer que la racine du projet est dans sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datashield.defcon import defcon, DefconLevel
from progress_tracker.goals import goal_manager
from syncsphere.snapshot import snapshot_manager
from jarvis.agent import executer_interaction_utilisateur, initialiser, parler
from core_intellect.intellect import interpreter_objectif
from context_engine.memory import charger_memoire
from context_engine.system_monitor import generer_rapport_systeme


class GreatOSKernel:
    """Noyau central de GreatOS unifiant les 8 modules."""

    def __init__(self):
        self.version = "GreatOS 1.0-alpha (PersonalOS V3)"
        self.defcon = defcon
        self.goals = goal_manager
        self.sync = snapshot_manager

    def demarrer(self):
        """Initialise la mémoire et prépare le système."""
        return initialiser()

    def executer(self, message: str) -> str:
        """Exécute une intention utilisateur via l'agent Jarvis."""
        memoire = charger_memoire()
        historique = []
        resultat = executer_interaction_utilisateur(message, historique, memoire)
        if resultat:
            return resultat[0]
        return "Aucune réponse produite."

    def rapport_etat(self) -> dict:
        """Génère un diagnostic complet des 8 modules."""
        sys_rep = generer_rapport_systeme()
        stats_goals = self.goals.lister_objectifs()
        return {
            "os": "GreatOS",
            "version": self.version,
            "defcon": self.defcon.current_level.name,
            "systeme": sys_rep,
            "objectifs_actifs": len(stats_goals),
            "snapshots_disponibles": len(self.sync.lister_snapshots()),
        }


kernel = GreatOSKernel()


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "status":
            import pprint
            pprint.pprint(kernel.rapport_etat())
            return
        elif cmd == "snapshot":
            snap = kernel.sync.creer_snapshot()
            print(f"Snapshot GreatOS créé avec succès : {snap}")
            return
        elif cmd == "ask":
            query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Bonjour Jarvis"
            print(kernel.executer(query))
            return

    print(f"=== GreatOS Kernel {kernel.version} ===")
    print("Usage: python greatos.py [status|snapshot|ask <message>]")


if __name__ == "__main__":
    main()
