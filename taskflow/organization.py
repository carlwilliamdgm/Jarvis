#capabilities/organization.py

import shutil
from pathlib import Path

from datashield.safety import chemin_autorise

DOSSIERS_ORGANISATION = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac"},
    "Video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".ps1", ".cmd"},
    "Installateurs": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm"},
}


FICHIERS_PROTEGES = {
    "memory.json",
    "memory.db",
    "goals.json",
    "voice_state.json",
    "stark_actif.json",
    "browser_overlay_state.json",
    "browser_sessions_state.json",
    "browser_sessions.json",
    "requirements.txt",
    "pytest.ini",
    "greatos.py",
    "jarvis.cmd",
    "jarvis_hidden.ps1",
    "monitor.py",
    "install_web_search.py",
    "update_scheduled_task.ps1",
    "ARCHITECTURE.md",
    "README.md",
    "JARVIS_GC.md",
    "PREMIER_LANCEMENT.md",
    "WEB_SEARCH_CONFIG.md",
}


def est_fichier_protege(path: Path) -> bool:
    """Empêche le déplacement des fichiers vitaux du système GreatOS."""
    if path.name.lower() in {f.lower() for f in FICHIERS_PROTEGES}:
        return True
    if path.suffix.lower() == ".gos":
        return True
    return False


def categorie_fichier(path: Path) -> str:
    if est_fichier_protege(path):
        return "Protege"
    extension = path.suffix.lower()
    for categorie, extensions in DOSSIERS_ORGANISATION.items():
        if extension in extensions:
            return categorie
    return "Autres"


def analyser_organisation(chemin: str) -> str:
    try:
        dossier = chemin_autorise(chemin, doit_exister=True)
        if not dossier.is_dir():
            return f"Ce chemin n'est pas un dossier : {dossier}"

        categories = {}
        ignores = 0
        for item in dossier.iterdir():
            if not item.is_file():
                ignores += 1
                continue
            categorie = categorie_fichier(item)
            if categorie == "Protege":
                ignores += 1
                continue
            categories[categorie] = categories.get(categorie, 0) + 1

        if not categories:
            return f"Aucun fichier a organiser dans {dossier}."

        lignes = [f"Plan d'organisation pour {dossier} :"]
        for categorie, nombre in sorted(categories.items()):
            lignes.append(f"- {categorie}: {nombre} fichier(s)")
        if ignores:
            lignes.append(f"- Ignored: {ignores} element(s) non fichier")
        lignes.append("Pour appliquer ce plan, utilisez organiser_dossier(chemin).")
        return "\n".join(lignes)
    except Exception as e:
        return f"Erreur : {e}"


def chemin_unique(destination: Path) -> Path:
    if not destination.exists():
        return destination
    compteur = 1
    while True:
        candidat = destination.with_name(f"{destination.stem} ({compteur}){destination.suffix}")
        if not candidat.exists():
            return candidat
        compteur += 1


def organiser_dossier_direct(chemin: str) -> str:
    dossier = chemin_autorise(chemin, doit_exister=True)
    if not dossier.is_dir():
        return f"Ce chemin n'est pas un dossier : {dossier}"

    deplacements = []
    for item in dossier.iterdir():
        if not item.is_file():
            continue
        categorie = categorie_fichier(item)
        if categorie == "Protege":
            continue
        cible_dir = dossier / categorie
        cible_dir.mkdir(exist_ok=True)
        cible = chemin_unique(cible_dir / item.name)
        shutil.move(str(item), str(cible))
        deplacements.append(f"{item.name} -> {categorie}")

    if not deplacements:
        return f"Aucun fichier a organiser dans {dossier}."
    return "Organisation terminee :\n" + "\n".join(deplacements[:100])
