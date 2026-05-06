from pathlib import Path
from core.paths import HOME, JARVIS_DIR


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


def niveau_depuis(parent: Path, enfant: Path) -> int | None:
    try:
        relatif = enfant.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return None
    return len(relatif.parts)


def suppression_requiert_confirmation(path: Path) -> bool:
    """Confirme seulement les suppressions de zones larges, racines ou hors espace utilisateur."""
    resolved = path.resolve(strict=False)
    if racine_trop_large(resolved) or resolved == Path(resolved.anchor):
        return True

    niveau_home = niveau_depuis(HOME, resolved)
    if niveau_home is None:
        return True

    racines_utilisateur = {HOME, HOME / "Desktop", HOME / "Documents", HOME / "Downloads"}
    if resolved in {racine.resolve(strict=False) for racine in racines_utilisateur}:
        return True

    return niveau_home <= 1
