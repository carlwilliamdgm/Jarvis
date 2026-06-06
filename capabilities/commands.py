import shlex
import subprocess


def executer_commande_direct(commande: str) -> str:
    if not commande or not commande.strip():
        return "Commande vide."

    try:
        resultat = subprocess.run(
            shlex.split(commande),
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


def executer_powershell_direct(commande: str) -> str:
    if not commande or not commande.strip():
        return "Commande PowerShell vide."
    commande = commande.strip()
    commande_lower = commande.lower()
    patterns_destructifs = ("rm -rf", "del /f /s /q", "format", "rd /s /q")
    if any(pattern in commande_lower for pattern in patterns_destructifs):
        return "Commande bloquée : pattern destructif détecté."

    try:
        resultat = subprocess.run(
            ["PowerShell", "-NoProfile", "-Command", commande],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = resultat.stdout or resultat.stderr
        return output.strip() if output else "Commande PowerShell executee sans sortie."
    except subprocess.TimeoutExpired:
        return "Timeout — commande PowerShell trop longue."
    except Exception as e:
        return f"Erreur : {e}"
