import shutil

from core.memory import journaliser_action
from core.safety import chemin_autorise, racine_trop_large


def creer_dossier(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin)
        path.mkdir(parents=True, exist_ok=True)
        resultat = f"Dossier cree : {path}"
        journaliser_action("creer_dossier", {"chemin": str(path)}, resultat)
        return resultat
    except Exception as e:
        return f"Erreur : {e}"


def creer_fichier(chemin: str, contenu: str = "") -> str:
    try:
        path = chemin_autorise(chemin)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(contenu)
        resultat = f"Fichier cree : {path}"
        journaliser_action("creer_fichier", {"chemin": str(path)}, resultat)
        return resultat
    except Exception as e:
        return f"Erreur : {e}"


def lire_fichier(chemin: str) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Fichier introuvable : {chemin}"
    except Exception as e:
        return f"Erreur : {e}"


def supprimer_direct(chemin: str) -> str:
    path = chemin_autorise(chemin, doit_exister=True)
    if racine_trop_large(path):
        raise ValueError(f"Suppression refusee pour une racine protegee : {path}")
    if path.is_file():
        path.unlink()
        return f"Fichier supprime : {path}"
    if path.is_dir():
        shutil.rmtree(path)
        return f"Dossier supprime : {path}"
    return f"Introuvable : {path}"

