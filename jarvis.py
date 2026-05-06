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
from together import Together as TogetherClient
from rich.console import Console
from rich.panel import Panel
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.prompt import construire_prompt_action, construire_prompt_conversation
from tools import OUTILS

console = Console()

OS = platform.system()
HOME = Path.home()

MODELES_GROQ = ["mixtral-8x7b-32768"]  # Ultra-rapide MoE (Mixture of Experts) sur Groq
MODELES_TOGETHER = ["meta-llama/Llama-3.1-8B-Instruct-Turbo"]  # Modèle 8B rapide et efficace
MODELE_LOCAL = "phi3:mini"
MAX_MESSAGES_HISTORIQUE = 20
INTERVALLE_VEILLE_PROACTIVE = 300

MOTS_ACTION = [
    "fais", "crée", "supprime", "liste", "organise", "exécute", "commande", 
    "dossier", "fichier", "mémoire", "note", "préférence", "automatisation", 
    "rappel", "surveillance", "creer", "lire", "audit", "scan", "vider", 
    "ajouter", "noter", "memoriser", "nettoyer", "liberer", "optimise",
    "renomme", "deplace", "copie", "synchronise", "planifie", "rappelle"
]

MOTS_OPTIMISATION = ["optimise", "libère", "nettoie", "libere", "nettoyer"]

def detecter_intention(message: str) -> bool:
    """
    Détecte si le message contient une intention d'action.
    Retourne True si c'est une action, False si c'est juste de la conversation.
    """
    message_lower = message.lower()
    # Chercher les mots-clés d'action
    if any(mot in message_lower for mot in MOTS_ACTION):
        return True
    # Patterns supplémentaires qui indiquent une action
    if any(pattern in message_lower for pattern in [
        "peux-tu", "peux tu", "pourrais-tu", "pourrais tu", 
        "would you", "can you", "please", "s'il te plaît",
        " fais ", " crée ", " supprime ", " ouvre ",
        "? oui" # question + réponse anticipée
    ]):
        return True
    return False

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

def chat_with_together(modele, messages):
    """Appel à Together AI pour modèles cloud gratuits."""
    try:
        client = TogetherClient()
        # Convertir les messages pour Together
        together_messages = []
        for m in messages:
            together_messages.append({"role": m["role"], "content": m["content"]})
        
        response = client.chat.completions.create(
            model=modele,
            messages=together_messages,
            max_tokens=1024,
            temperature=0.7
        )
        return {"message": {"content": response.choices[0].message.content}}
    except Exception as e:
        raise Exception(f"Together error: {e}")

def chat_with_local(modele, messages):
    """Appel à Ollama pour modèle local avec gestion d'erreur."""
    try:
        return ollama.chat(model=modele, messages=messages, options={"think": False})
    except Exception as e:
        raise Exception(f"Ollama non disponible: {e}. Assurez-vous que le service est démarré.")

def est_connecte() -> bool:
    """Vérifie la connectivité Internet en testant un endpoint fiable."""
    try:
        # Tester avec Google DNS qui est ultra-fiable
        urllib.request.urlopen("https://www.google.com", timeout=3).close()
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

def extraire_json_objets(texte: str, verbose: bool = False) -> list[dict]:
    """
    Extrait les objets JSON du texte.
    Valide strictement que chaque objet a "outil" et "args" avec "args" dict.
    Retourne une liste d'objets JSON valides.
    verbose=True pour afficher les avertissements de validation.
    """
    objets = []
    decodeur = json.JSONDecoder()
    positions = [m.start() for m in re.finditer(r"\{", texte)]
    
    for position in positions:
        try:
            objet, _ = decodeur.raw_decode(texte[position:])
        except JSONDecodeError:
            continue
            
        if not isinstance(objet, dict):
            continue
            
        # Validation stricte
        if "outil" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'outil' : {objet}[/yellow]")
            continue
        if "args" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'args' : {objet}[/yellow]")
            continue
        if not isinstance(objet["args"], dict):
            if verbose:
                console.print(f"[yellow]⚠️  'args' n'est pas un dictionnaire : {objet}[/yellow]")
            continue
            
        objets.append(objet)
    
    return objets

def valider_reponse_json(reponse: str) -> bool:
    """
    Valide que la réponse contient au moins un JSON valide avec "outil" et "args".
    Retourne True si valide, False sinon.
    """
    objets = extraire_json_objets(reponse)
    return len(objets) > 0

def executer_outil(reponse: str) -> str | None:
    objets = extraire_json_objets(reponse, verbose=True)
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
    tentatives = 0
    max_tentatives = 2
    
    while tentatives < max_tentatives:
        tentatives += 1
        connecte = est_connecte()
        
        if connecte:
            if tentatives == 1:
                console.print(f"[dim]→ Internet connecté. Tentative modèles cloud...[/dim]")
            else:
                console.print(f"[dim yellow]→ Retry modèles cloud (tentative {tentatives})...[/dim yellow]")
            
            # Essayer Groq
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(MODELES_GROQ)) as executor:
                futures = {executor.submit(chat_with_cloud, modele, historique): modele for modele in MODELES_GROQ}
                for future in concurrent.futures.as_completed(futures):
                    modele = futures[future]
                    try:
                        reponse = future.result()
                        console.print(f"[dim green]✓ Groq réussi : {modele}[/dim green]")
                        break
                    except Exception as e:
                        console.print(f"[dim yellow]✗ Groq {modele} indisponible : {str(e)[:80]}[/dim yellow]")
                        continue
            
            # Si Groq échoue, essayer Together
            if reponse is None:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(MODELES_TOGETHER)) as executor:
                    futures = {executor.submit(chat_with_together, modele, historique): modele for modele in MODELES_TOGETHER}
                    for future in concurrent.futures.as_completed(futures):
                        modele = futures[future]
                        try:
                            reponse = future.result()
                            console.print(f"[dim green]✓ Together réussi : {modele}[/dim green]")
                            break
                        except Exception as e:
                            console.print(f"[dim yellow]✗ Together {modele} indisponible : {str(e)[:80]}[/dim yellow]")
                            continue
        else:
            if tentatives == 1:
                console.print(f"[dim yellow]⚠️  Pas d'Internet détecté. Utilisation du modèle local.[/dim yellow]")
        
        # Fallback sur modèle local
        if reponse is None:
            if tentatives == 1:
                console.print(f"[dim]→ Utilisation du modèle local : {MODELE_LOCAL}[/dim]")
            else:
                console.print(f"[dim yellow]→ Retry {MODELE_LOCAL} (tentative {tentatives})...[/dim yellow]")
            try:
                reponse = chat_with_local(MODELE_LOCAL, historique)
            except Exception as e:
                console.print(f"[red]✗ Erreur modèle local : {e}[/red]")
                if tentatives < max_tentatives:
                    continue
                reponse = {"message": {"content": f"Erreur : {e}"}}
        
        if reponse is None:
            continue
            
        contenu = reponse["message"]["content"]
        
        # Valider la réponse si c'est une action
        if intention_action:
            if valider_reponse_json(contenu):
                break  # JSON valide, on sort
            elif tentatives < max_tentatives:
                console.print(f"[yellow]⚠️  Réponse invalide (pas de JSON). Nouvelle tentative...[/yellow]")
                historique.append({"role": "assistant", "content": contenu})
                historique.append({
                    "role": "user", 
                    "content": "Votre réponse précédente n'était pas en JSON. Veuillez UNIQUEMENT répondre avec du JSON au format : {\"outil\": \"nom\", \"args\": {...}}"
                })
                reponse = None
                continue
        else:
            # Conversation valide, on sort
            break
    
    if reponse is None:
        reponse = {"message": {"content": "Erreur : Impossible d'obtenir une réponse du modèle."}}
    
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
                console.print("[dim]→ Exécution des outils...[/dim]")
                resultat = executer_outil(reponse)
                if resultat:
                    reponse = resultat
                else:
                    # Vérifier s'il y avait du JSON
                    if valider_reponse_json(reponse):
                        reponse = f"[yellow]⚠️  Outils exécutés mais pas de résultat retourné.[/yellow]\n{reponse}"
                    else:
                        reponse = (
                            "[red]❌ Erreur : Je n'ai pas pu exécuter cette action car je n'ai pas généré la commande correcte.[/red]\n"
                            "[dim]Conseil : Reformulez votre demande ou essayez avec d'autres mots.[/dim]"
                        )
            
            OUTILS["enregistrer_echange"](user_input, reponse)
            console.print(Panel(reponse, title=f"Jarvis — {horodatage}", style="cyan"))

        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break

if __name__ == "__main__":
    main()
