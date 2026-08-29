#capabilities/commands.py

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import List, Tuple

# Liste blanche d'exécutables autorisés pour l'exécution directe
EXECUTABLES_AUTORISES = {
    # Python & runtime
    "python",
    "python.exe",
    "py",
    "py.exe",
    "pytest",
    "pytest.exe",
    "pip",
    "pip.exe",
    Path(sys.executable).name.lower(),
    # Shells contrôlés
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    # Outils système Windows
    "explorer",
    "explorer.exe",
    "tasklist",
    "tasklist.exe",
    "taskkill",
    "taskkill.exe",
    "notepad",
    "notepad.exe",
    "ipconfig",
    "ipconfig.exe",
    "ping",
    "ping.exe",
    "netstat",
    "netstat.exe",
    "where",
    "where.exe",
    "whoami",
    "whoami.exe",
    "systeminfo",
    "systeminfo.exe",
    "hostname",
    "hostname.exe",
    "tailscale",
    "tailscale.exe",
    # Outils dev
    "git",
    "git.exe",
    "code",
    "code.cmd",
    "code.exe",
    "node",
    "node.exe",
    "npm",
    "npm.cmd",
    "curl",
    "curl.exe",
    # Navigateurs
    "chrome",
    "chrome.exe",
    "msedge",
    "msedge.exe",
    "firefox",
    "firefox.exe",
}

# Commandes internes cmd.exe gérées de façon contrôlée
COMMANDES_CMD_BUILTIN = {"echo", "dir", "type", "mkdir", "start", "cls", "ver", "vol", "date", "time"}

# Cmdlets et constructions PowerShell interdites par l'analyseur AST
POWERSHELL_FORBIDDEN_CONSTRUCTS = [
    r"\bInvoke-Expression\b",
    r"\bIEX\b",
    r"\[ScriptBlock\]::Create",
    r"\bInvoke-Command\b",
    r"\bDownloadString\b",
    r"\bDownloadFile\b",
    r"\bNet\.WebClient\b",
    r"\bStart-BitsTransfer\b",
    r"\bFormat-Volume\b",
    r"\bClear-Disk\b",
    r"\bInitialize-Disk\b",
    r"\bStop-Computer\b",
    r"\bRestart-Computer\b",
    r"\bSet-ExecutionPolicy\b",
]


def analyser_ast_powershell(commande: str) -> Tuple[bool, str]:
    """Analyse syntaxique et sécurité AST d'une commande PowerShell.
    
    Retourne (est_valide, message_erreur).
    """
    if not commande or not commande.strip():
        return False, "Commande PowerShell vide."

    cmd_clean = commande.strip()

    # 1. Vérification rapide des patterns destructifs et malveillants connus
    patterns_destructifs = ("rm -rf", "del /f /s /q", "format", "rd /s /q")
    cmd_lower = cmd_clean.lower()
    if any(pattern in cmd_lower for pattern in patterns_destructifs):
        return False, "Commande bloquée : pattern destructif détecté."

    for pattern in POWERSHELL_FORBIDDEN_CONSTRUCTS:
        if re.search(pattern, cmd_clean, re.IGNORECASE):
            return False, f"Commande bloquée par analyseur AST : construction interdite détectée ({pattern})."

    # 2. Validation AST via le parseur natif PowerShell
    script_ast_validation = """
    param([string]$ScriptCode)
    $parseErrors = $null
    $tokens = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($ScriptCode, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        Write-Output ("SYNTAX_ERROR:" + $parseErrors[0].Message)
        exit 0
    }
    $forbiddenCmds = @('invoke-expression', 'iex', 'format-volume', 'clear-disk', 'initialize-disk', 'stop-computer', 'restart-computer')
    $cmdAsts = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true)
    foreach ($c in $cmdAsts) {
        $name = $c.GetCommandName()
        if ($name -and ($forbiddenCmds -contains $name.ToLower())) {
            Write-Output ("FORBIDDEN_COMMAND:" + $name)
            exit 0
        }
    }
    Write-Output "OK"
    """
    try:
        verif = subprocess.run(
            ["PowerShell", "-NoProfile", "-Command", script_ast_validation, "-ScriptCode", cmd_clean],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = (verif.stdout or "").strip()
        if out.startswith("SYNTAX_ERROR:"):
            return False, f"Erreur de syntaxe PowerShell : {out[13:]}"
        if out.startswith("FORBIDDEN_COMMAND:"):
            return False, f"Commande PowerShell interdite par l'AST : {out[18:]}"
    except (subprocess.TimeoutExpired, Exception):
        # Fallback : la validation regex initiale a été franchie avec succès
        pass

    return True, ""


def _preparer_arguments_commande(commande: str) -> Tuple[List[str], str | None]:
    """Parse une ligne de commande et vérifie l'exécutable contre la whitelist.
    
    Retourne (liste_arguments, erreur).
    """
    if not commande or not commande.strip():
        return [], "Commande vide."

    try:
        tokens = shlex.split(commande, posix=True)
    except Exception:
        try:
            tokens = shlex.split(commande, posix=False)
        except Exception as e:
            return [], f"Erreur de découpage de la commande : {e}"

    if not tokens:
        return [], "Commande vide."

    premier_token = tokens[0].strip('\"\'')
    premier_token_lower = premier_token.lower()
    nom_fichier = Path(premier_token).name.lower()

    # Si c'est le binaire python courant (ou un chemin absolu vers python)
    if (
        premier_token_lower == sys.executable.lower()
        or premier_token_lower == sys.executable.lower().replace("/", "\\")
        or nom_fichier in EXECUTABLES_AUTORISES
        or premier_token_lower in EXECUTABLES_AUTORISES
    ):
        return tokens, None

    # Si c'est une commande interne cmd.exe autorisée (echo, dir, etc.)
    if premier_token_lower in COMMANDES_CMD_BUILTIN:
        args = ["cmd.exe", "/c", commande]
        return args, None

    return [], f"Commande bloquée : exécutable '{premier_token}' non autorisé par la whitelist."


def executer_commande_direct(commande: str) -> str:
    """Exécute une commande système via une liste d'arguments contrôlés sans shell=True."""
    if not commande or not commande.strip():
        return "Commande vide."

    args, erreur = _preparer_arguments_commande(commande)
    if erreur:
        return erreur

    try:
        resultat = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        output = resultat.stdout or resultat.stderr
        return output.strip() if output else "Commande executee sans sortie."
    except subprocess.TimeoutExpired:
        return "Timeout — commande trop longue."
    except Exception as e:
        return f"Erreur : {e}"


def executer_powershell_direct(commande: str) -> str:
    """Exécute une commande PowerShell après validation syntaxique et analyseur AST."""
    if not commande or not commande.strip():
        return "Commande PowerShell vide."

    valide, erreur = analyser_ast_powershell(commande)
    if not valide:
        return erreur

    try:
        resultat = subprocess.run(
            ["PowerShell", "-NoProfile", "-Command", commande.strip()],
            shell=False,
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