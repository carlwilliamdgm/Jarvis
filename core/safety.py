from pathlib import Path

from core.paths import ALLOWED_ROOTS, HOME, JARVIS_DIR

DANGEROUS_ACTIONS = {"supprimer", "vider_temp", "vider_corbeille", "executer_commande", "organiser_dossier"}

COMMANDES_AUTORISEES = {
    "python", "pip", "git", "where", "whoami", "hostname",
    "ipconfig", "ollama", "powershell", "mkdir", "rmdir",
    "del", "copy", "move", "echo", "type", "dir", "ls"
}


def chemin_autorise(chemin: str, doit_exister: bool = False) -> Path:
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

    if not any(path == root or root in path.parents for root in ALLOWED_ROOTS):
        racines = ", ".join(str(root) for root in ALLOWED_ROOTS)
        raise ValueError(f"Chemin refuse hors zone autorisee : {path}. Zones autorisees : {racines}")

    return path


def racine_trop_large(path: Path) -> bool:
    return path == HOME or path == JARVIS_DIR or path in ALLOWED_ROOTS