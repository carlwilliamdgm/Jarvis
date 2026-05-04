import concurrent.futures
import json
import ollama
import platform
import re
import threading
import urllib.request
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from groq import Groq as GroqClient
from rich.console import Console
from rich.panel import Panel
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.prompt import construire_prompt_action, construire_prompt_conversation
from tools import OUTILS

console = Console()

OS = platform.system()
HOME = Path.home()

MODELES_CLOUD = ["llama-3.1-70b-versatile"]
MODELE_LOCAL = "phi3:mini"
MAX_MESSAGES_HISTORIQUE = 20
INTERVALLE_VEILLE_PROACTIVE = 300

MOTS_ACTION = ["fais", "crée", "supprime", "liste", "organise", "exécute", "commande", "dossier", "fichier", "mémoire", "note", "préférence", "automatisation", "rappel", "surveillance"]

MOTS_OPTIMISATION = ["optimise", "libère", "nettoie", "libere", "nettoyer"]

def chat_with_cloud(modele, messages):
    """Appel à Groq pour modèles cloud gratuits."""
    try:
        client = GroqClient()
        # Convertir les messages pour Groq
        groq_messages = []
        system_msg = ""
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                groq_messages.append({"role": m["role"], "content": m["content"]})
        
        response = client.chat.completions.create(
            model=modele,
            messages=groq_messages,
            system=system_msg,
            max_tokens=1024,
            temperature=0.7
        )
        return {"message": {"content": response.choices[0].message.content}}
    except Exception as e:
        raise Exception(f"Groq error: {e}")

def chat_with_local(modele, messages):
    """Appel à Ollama pour modèle local."""
    return ollama.chat(model=modele, messages=messages, options={"think": False})

def detecter_intention(message: str) -> bool:
    """Retourne True si c'est une action, False si conversation."""
    message_lower = message.lower()
    return any(mot in message_lower for mot in MOTS_ACTION)

def est_connecte() -> bool:
    try:
        urllib.request.urlopen("https://api.groq.com", timeout=3).close()
        return True
    except Exception:
        return False

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

def parler(message: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """Parle en utilisant le modèle cloud d'abord, puis fallback sur local."""
    historique.append({"role": "user", "content": message})
    
    intention_action = detecter_intention(message)
    
    # Ajuster le prompt système selon l'intention
    if intention_action:
        historique[0]["content"] = construire_prompt_action(memoire)
    else:
        historique[0]["content"] = construire_prompt_conversation(memoire)
    
    reponse = None
    
    # Essayer les modèles cloud en parallèle
    if est_connecte():
        console.print(f"[dim]→ tentative modèles cloud...[/dim]")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(MODELES_CLOUD)) as executor:
            futures = {executor.submit(chat_with_cloud, modele, historique): modele for modele in MODELES_CLOUD}
            for future in concurrent.futures.as_completed(futures):
                modele = futures[future]
                try:
                    reponse = future.result()
                    console.print(f"[dim]→ modèle cloud réussi : {modele}[/dim]")
                    break
                except Exception as e:
                    console.print(f"[dim yellow]→ {modele} indisponible ({e})[/dim yellow]")
                    continue
    
    # Fallback sur modèle local
    if reponse is None:
        console.print(f"[dim]→ bascule vers {MODELE_LOCAL}[/dim]")
        try:
            reponse = chat_with_local(MODELE_LOCAL, historique)
        except Exception as e:
            console.print(f"[yellow]Erreur modèle local : {e}[/yellow]")
            reponse = {"message": {"content": f"Erreur : {e}"}}

    contenu = reponse["message"]["content"]
    historique.append({"role": "assistant", "content": contenu})
    limiter_historique(historique)
    return contenu, intention_action

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
    prompt = construire_prompt_action(memoire)
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

            if any(mot in user_input.lower() for mot in MOTS_OPTIMISATION):
                user_input += "\nEnchaîne obligatoirement sans confirmation : vider_temp, vider_corbeille, puis audit_stockage."

            horodatage = datetime.now().strftime("%H:%M:%S")
            with console.status("[cyan]Jarvis réfléchit...[/cyan]", spinner="dots"):
                reponse, intention_action = parler(user_input, historique, memoire)
            if intention_action:
                resultat = executer_outil(reponse)
                reponse = resultat if resultat else reponse
            OUTILS["enregistrer_echange"](user_input, reponse)
            console.print(Panel(reponse, title=f"Jarvis — {horodatage}", style="cyan"))

        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break

if __name__ == "__main__":
    main()
