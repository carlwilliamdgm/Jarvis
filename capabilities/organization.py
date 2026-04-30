import shutil
from pathlib import Path

from core.safety import chemin_autorise, racine_trop_large

DOSSIERS_ORGANISATION = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac"},
    "Video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".ps1", ".cmd"},
    "Installateurs": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm"},
}


def categorie_fichier(path: Path) -> str:
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
    if racine_trop_large(dossier):
        return f"Organisation refusee pour une racine trop large : {dossier}"

    deplacements = []
    for item in dossier.iterdir():
        if not item.is_file():
            continue
        categorie = categorie_fichier(item)
        cible_dir = dossier / categorie
        cible_dir.mkdir(exist_ok=True)
        cible = chemin_unique(cible_dir / item.name)
        shutil.move(str(item), str(cible))
        deplacements.append(f"{item.name} -> {categorie}")

    if not deplacements:
        return f"Aucun fichier a organiser dans {dossier}."
    return "Organisation terminee :\n" + "\n".join(deplacements[:100])

