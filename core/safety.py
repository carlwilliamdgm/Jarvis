from pathlib import Path
from core.paths import HOME, JARVIS_DIR


# Actions nécessitant confirmation — uniquement l'irréversible
DANGEROUS_ACTIONS = {"supprimer"}


def chemin_autorise(chemin: str, doit_exister: bool = False) -> Path:
    """Valide et retourne le chemin. Vérifie l'existence si demandé."""
    if not chemin or not str(chemin).strip():
        raise ValueError("Chemin vide.")

    path = Path(chemin).expanduser()
    if not path.is_absolute():
        path = JARVIS_DIR / path

    if doit_exister:
        path = path.resolve(strict=True)
    else:
        parent = path.parent.resolve(strict=False)
        path = parent / path.name

    return path


def racine_trop_large(path: Path) -> bool:
    return path == HOME or path == JARVIS_DIR