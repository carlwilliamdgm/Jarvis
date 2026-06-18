#capabilities/files.py

import shutil
from core.memory import journaliser_action
from core.safety import chemin_autorise


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


def lire_fichier(chemin: str, max_caracteres: int = 200_000) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        max_caracteres = max(1_000, min(int(max_caracteres), 2_000_000))
        with open(path, "r", encoding="utf-8") as f:
            contenu = f.read(max_caracteres + 1)
        if len(contenu) > max_caracteres:
            return contenu[:max_caracteres] + f"\n\n[Lecture tronquee a {max_caracteres} caracteres.]"
        return contenu
    except FileNotFoundError:
        return f"Fichier introuvable : {chemin}"
    except Exception as e:
        return f"Erreur : {e}"


def lister_dossier(chemin: str, limite: int = 200) -> str:
    try:
        path = chemin_autorise(chemin, doit_exister=True)
        if not path.is_dir():
            return f"Ce chemin n'est pas un dossier : {path}"
        limite = max(1, min(int(limite), 1000))
        items = sorted(path.iterdir())
        if not items:
            return f"Dossier vide : {path}"
        lignes = [f"Contenu de {path} :"]
        dossiers = [i for i in items if i.is_dir()]
        fichiers = [i for i in items if i.is_file()]
        affiches = 0
        for d in dossiers:
            if affiches >= limite:
                break
            lignes.append(f"  📁 {d.name}")
            affiches += 1
        for f in fichiers:
            if affiches >= limite:
                break
            taille = f.stat().st_size
            taille_str = f"{round(taille/1024/1024, 1)} MB" if taille > 1024*1024 else f"{round(taille/1024, 1)} KB"
            lignes.append(f"  📄 {f.name} ({taille_str})")
            affiches += 1
        if len(items) > affiches:
            lignes.append(f"  ... {len(items) - affiches} element(s) supplementaire(s) non affiches")
        lignes.append(f"\n{len(dossiers)} dossier(s), {len(fichiers)} fichier(s)")
        return "\n".join(lignes)
    except Exception as e:
        return f"Erreur : {e}"


def supprimer_direct(chemin: str) -> str:
    path = chemin_autorise(chemin, doit_exister=True)
    if path.is_file():
        path.unlink()
        resultat = f"Fichier supprime : {path}"
        journaliser_action("supprimer", {"chemin": str(path)}, resultat)
        return resultat
    if path.is_dir():
        shutil.rmtree(path)
        resultat = f"Dossier supprime : {path}"
        journaliser_action("supprimer", {"chemin": str(path)}, resultat)
        return resultat
    return f"Introuvable : {path}"
