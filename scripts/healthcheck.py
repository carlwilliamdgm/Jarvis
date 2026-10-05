#!/usr/bin/env python3
"""GreatOS Healthcheck — vérifie l'état du système avant démarrage."""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = "✅"
WARN = "⚠️"
FAIL = "❌"

def check(label, condition, fatal=False):
    icon = OK if condition else (FAIL if fatal else WARN)
    print(f"{icon} {label}")
    return condition

def main():
    print("=== GreatOS Healthcheck ===")
    all_ok = True

    # Fichiers critiques
    for f in ['greatos.py', 'greatos_contracts.py', 'greatos_capabilities.py', 'requirements.txt']:
        ok = check(f"Fichier critique : {f}", (ROOT / f).exists(), fatal=True)
        all_ok = all_ok and ok

    # Runtime dir
    check("Dossier runtime/", (ROOT / 'runtime').exists())

    # Modules importables
    modules = [
        'datashield.defcon',
        'progress_tracker.goals',
        'syncsphere.snapshot',
        'core_intellect.intellect',
        'context_engine.memory',
        'taskflow.tools',
        'greatos_contracts',
        'greatos_capabilities',
    ]
    for mod in modules:
        try:
            __import__(mod)
            check(f"Module : {mod}", True)
        except ImportError as e:
            check(f"Module : {mod} — {e}", False, fatal=True)
            all_ok = False

    # Variables d'environnement (présence sans valeur)
    for var in ['GROQ_API_KEY', 'OPENROUTER_API_KEY']:
        present = bool(os.environ.get(var))
        check(f"Env var : {var}", present)

    print()
    print("=== Résultat ===")
    if all_ok:
        print(f"{OK} Système opérationnel")
        return 0
    else:
        print(f"{FAIL} Des problèmes critiques ont été détectés")
        return 1

if __name__ == '__main__':
    sys.exit(main())
