import shlex
import subprocess
from pathlib import Path

from core.paths import OS
from core.safety import COMMANDES_AUTORISEES


def executer_commande_direct(commande: str) -> str:
    args = shlex.split(commande, posix=(OS != "Windows"))
    if not args:
        return "Commande vide."

    executable = Path(args[0]).name.lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in COMMANDES_AUTORISEES:
        return f"Commande refusee : {args[0]}. Commandes autorisees : {', '.join(sorted(COMMANDES_AUTORISEES))}"

    resultat = subprocess.run(
        args,
        shell=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = resultat.stdout or resultat.stderr
    return output.strip() if output else "Commande executee sans sortie."

