import shlex
import subprocess
from core.paths import OS


def executer_commande_direct(commande: str) -> str:
    if not commande or not commande.strip():
        return "Commande vide."

    try:
        if OS == "Windows":
            resultat = subprocess.run(
                commande,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:
            args = shlex.split(commande, posix=True)
            resultat = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        output = resultat.stdout or resultat.stderr
        return output.strip() if output else "Commande executee sans sortie."
    except subprocess.TimeoutExpired:
        return "Timeout — commande trop longue."
    except Exception as e:
        return f"Erreur : {e}"