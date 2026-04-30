import ollama
import json
import re
import platform
import threading
import urllib.request
from json import JSONDecodeError
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.prompt import construire_prompt
from tools import OUTILS

console = Console()

OS = platform.system()
HOME = Path.home()

MODELE_CLOUD = "qwen3.5:cloud"
MODELE_LOCAL = "phi3:mini"
MAX_MESSAGES_HISTORIQUE = 20
INTERVALLE_VEILLE_PROACTIVE = 60

def est_connecte() -> bool:
    try:
        urllib.request.urlopen("https://ollama.com", timeout=3).close()
        return True
    except Exception:
        return False

def choisir_modele() -> str:
    modele = MODELE_CLOUD if est_connecte() else MODELE_LOCAL
    console.print(f"[dim]→ modèle : {modele}[/dim]")
    return modele

def initialiser() -> dict:
    memoire = normaliser_memoire(charger_memoire())
    if "utilisateur" not in memoire:
        console.print(Panel(
            "Bienvenue. Je suis Jarvis, votre assistant local et compagnon cognitif.\nJe vais apprendre à vous connaître et à vous assister.",
            style="bold cyan"
        ))
        nom = console.input("[bold green]Comment vous appelez-vous ?[/bold green] ").strip()
        langue = console.input("[bold green]Langue préférée ? (français/english) >[/bold green] ").strip() or "français"
        memoire["utilisateur"] = {
            "nom": nom,
            "os": OS,
            "home": str(HOME),
            "langue": langue,
        }
        memoire["notes"] = []
        memoire["preferences"] = {}
        memoire["historique_actions"] = []
        sauvegarder_memoire(memoire)
        console.print(f"[cyan]Bonjour {nom}. Je me souviendrai de vous.[/cyan]\n")
    sauvegarder_memoire(memoire)
    return memoire

def extraire_json_objets(texte: str) -> list[dict]:
    objets = []
    decodeur = json.JSONDecoder()
    positions = [m.start() for m in re.finditer(r"\{", texte)]
    for position in positions:
        try:
            objet, _ = decodeur.raw_decode(texte[position:])
        except JSONDecodeError:
            continue
        if isinstance(objet, dict):
            objets.append(objet)
    return objets

def executer_outil(reponse: str) -> str | None:
    objets = extraire_json_objets(reponse)
    if not objets:
        return None
    resultats = []
    for data in objets:
        try:
            outil = data.get("outil")
            args = data.get("args", {})
            if not outil:
                continue
            if outil not in OUTILS:
                resultats.append(f"Outil inconnu : {outil}")
                continue
            if not isinstance(args, dict):
                resultats.append(f"Arguments invalides pour {outil}.")
                continue
            resultats.append(str(OUTILS[outil](**args)))
        except TypeError as e:
            resultats.append(f"Arguments invalides pour {data.get('outil')} : {e}")
        except Exception as e:
            resultats.append(f"Erreur outil {data.get('outil')} : {e}")
    return "\n".join(resultats) if resultats else None

def limiter_historique(historique: list) -> None:
    if len(historique) <= MAX_MESSAGES_HISTORIQUE + 1:
        return
    systeme = historique[:1]
    recents = historique[-MAX_MESSAGES_HISTORIQUE:]
    historique[:] = systeme + recents

def parler(message: str, historique: list) -> str:
    historique.append({"role": "user", "content": message})
    modele = choisir_modele()
    try:
        reponse = ollama.chat(model=modele, messages=historique)
    except Exception:
        if modele == MODELE_LOCAL:
            raise
        console.print(f"[yellow]Modele cloud indisponible, bascule vers {MODELE_LOCAL}.[/yellow]")
        reponse = ollama.chat(model=MODELE_LOCAL, messages=historique)
    contenu = reponse["message"]["content"]
    historique.append({"role": "assistant", "content": contenu})
    limiter_historique(historique)
    resultat = executer_outil(contenu)
    reponse_finale = resultat if resultat else contenu
    OUTILS["enregistrer_echange"](message, reponse_finale)
    return reponse_finale

def afficher_evenements(force: bool = False, niveau: str = "normal"):
    resultat = OUTILS["bilan_proactif"](force=force, niveau=niveau)
    if not resultat.startswith("Aucun"):
        console.print(Panel(resultat, title="Jarvis proactif", style="yellow"))

def veille_proactive(stop_event: threading.Event):
    while not stop_event.wait(INTERVALLE_VEILLE_PROACTIVE):
        try:
            afficher_evenements(force=False, niveau="normal")
        except Exception as e:
            console.print(f"[dim yellow]Veille proactive indisponible : {e}[/dim yellow]")

def main():
    memoire = initialiser()
    nom = memoire["utilisateur"]["nom"]
    prompt = construire_prompt(memoire)
    historique = [{"role": "system", "content": prompt}]
    console.print(Panel(
        f"JARVIS — Agent local de {nom}\nAssistant, majordome numérique et compagnon cognitif\nTape 'exit' pour quitter.",
        style="bold cyan"
    ))
    afficher_evenements(force=False, niveau="silencieux")
    stop_event = threading.Event()
    veille = threading.Thread(target=veille_proactive, args=(stop_event,), daemon=True)
    veille.start()
    while True:
        try:
            user_input = console.input("[bold green]Toi >[/bold green] ").strip()
            if not user_input:
                continue
            if user_input.lower() == "exit":
                console.print("[cyan]Jarvis hors ligne.[/cyan]")
                stop_event.set()
                break
            with console.status("[cyan]Jarvis réfléchit...[/cyan]", spinner="dots"):
              reponse = parler(user_input, historique)
            console.print(Panel(reponse, title="Jarvis", style="cyan"))
        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break

if __name__ == "__main__":
    main()
