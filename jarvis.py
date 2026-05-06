import concurrent.futures
import json
import ollama
import os
import platform
import threading
import urllib.request
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Callable
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

MODELES_GROQ = ["llama-3.3-70b-versatile"]  # Modele Groq actuel, avec free tier selon le compte
MODELES_TOGETHER = ["meta-llama/Llama-3.1-8B-Instruct-Turbo"]  # Modèle 8B rapide et efficace
MODELES_OPENROUTER = ["openrouter/free"]  # Routeur gratuit OpenRouter, limite selon le compte
MODELE_LOCAL = "phi3:mini"
MAX_MESSAGES_HISTORIQUE = 20
INTERVALLE_VEILLE_PROACTIVE = 300
MAX_ETAPES_AGENT = 5

MOTS_ACTION = [
    "fais", "crée", "supprime", "liste", "organise", "exécute", "commande", 
    "dossier", "fichier", "mémoire", "note", "préférence", "automatisation", 
    "rappel", "surveillance", "creer", "lire", "audit", "scan", "vider", 
    "ajouter", "noter", "memoriser", "nettoyer", "liberer", "optimise",
    "renomme", "deplace", "copie", "synchronise", "planifie", "rappelle"
]

MOTS_OPTIMISATION = ["optimise", "libère", "nettoie", "libere", "nettoyer"]
MOTS_COMPLEXES = [
    "analyse", "audite", "audit", "corrige", "debug", "diagnostique", "optimise",
    "refactor", "architecture", "complexe", "plan", "projet", "automatisation",
    "surveillance", "organise", "plusieurs", "étapes", "etapes", "complet",
]
PLAN_OPTIMISATION = (
    "\nEnchaine les actions suivantes dans cet ordre : "
    "vider_temp, vider_corbeille, puis audit_stockage. "
    "Les outils sensibles gereront eux-memes la confirmation Oui/Non."
)

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


def estimer_complexite(message: str, intention_action: bool) -> str:
    message_lower = message.lower()
    score = 0
    if intention_action:
        score += 1
    score += sum(1 for mot in MOTS_COMPLEXES if mot in message_lower)
    if len(message) > 240:
        score += 1
    if any(separateur in message_lower for separateur in [" puis ", " ensuite ", "\n", ";"]):
        score += 1
    if len(extraire_json_objets(message)) > 1:
        score += 1
    return "complexe" if score >= 2 else "simple"

def chat_with_cloud(modele, messages):
    """Appel à Groq pour modèles cloud gratuits."""
    try:
        client = GroqClient()
        groq_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        
        response = client.chat.completions.create(
            model=modele,
            messages=groq_messages,
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


def chat_with_openrouter(modele, messages):
    """Appel OpenRouter via REST, compatible sans dependance supplementaire."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY absente.")

    payload = json.dumps({
        "model": modele,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "max_tokens": 1024,
        "temperature": 0.7,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/jarvis",
            "X-Title": "Jarvis Local",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        return {"message": {"content": data["choices"][0]["message"]["content"]}}
    except Exception as e:
        raise Exception(f"OpenRouter error: {e}")


def chat_with_local(modele, messages):
    """Appel à Ollama pour modèle local avec gestion d'erreur."""
    try:
        return ollama.chat(model=modele, messages=messages, options={"think": False})
    except Exception as e:
        raise Exception(f"Ollama non disponible: {e}. Assurez-vous que le service est démarré.")

def providers_cloud_disponibles() -> list[dict]:
    providers = []
    if os.environ.get("OPENROUTER_API_KEY"):
        providers.append({
            "nom": "OpenRouter",
            "modeles": MODELES_OPENROUTER,
            "fonction": chat_with_openrouter,
            "niveau": "simple",
        })
    if os.environ.get("GROQ_API_KEY"):
        providers.append({
            "nom": "Groq",
            "modeles": MODELES_GROQ,
            "fonction": chat_with_cloud,
            "niveau": "complexe",
        })
    if os.environ.get("TOGETHER_API_KEY"):
        providers.append({
            "nom": "Together",
            "modeles": MODELES_TOGETHER,
            "fonction": chat_with_together,
            "niveau": "simple",
        })
    return providers


def ordonner_providers_cloud(providers: list[dict], memoire: dict, complexite: str = "simple") -> list[dict]:
    """Choisir selon la complexite, puis alterner dans le groupe prioritaire pour repartir les quotas."""
    if len(providers) <= 1:
        return providers
    priorite = ["complexe", "simple"] if complexite == "complexe" else ["simple", "complexe"]
    routeur = memoire.get("routeur_modeles", {})
    ordonnes = []
    for niveau in priorite:
        groupe = [provider for provider in providers if provider["niveau"] == niveau]
        if not groupe:
            continue
        dernier = routeur.get(f"dernier_provider_{niveau}")
        noms = [provider["nom"] for provider in groupe]
        if dernier in noms:
            index_suivant = (noms.index(dernier) + 1) % len(groupe)
            groupe = groupe[index_suivant:] + groupe[:index_suivant]
        ordonnes.extend(groupe)
    return ordonnes


def memoriser_provider_cloud(nom_provider: str) -> None:
    data = normaliser_memoire(charger_memoire())
    routeur = data.setdefault("routeur_modeles", {})
    routeur["dernier_provider_cloud"] = nom_provider
    for provider in providers_cloud_disponibles():
        if provider["nom"] == nom_provider:
            routeur[f"dernier_provider_{provider['niveau']}"] = nom_provider
            break
    routeur["maj"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sauvegarder_memoire(data)

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
    position = 0
    
    while position < len(texte):
        position = texte.find("{", position)
        if position == -1:
            break
        try:
            objet, fin = decodeur.raw_decode(texte[position:])
        except JSONDecodeError:
            position += 1
            continue
            
        if not isinstance(objet, dict):
            position += fin
            continue
            
        # Validation stricte
        if "outil" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'outil' : {objet}[/yellow]")
            position += fin
            continue
        if "args" not in objet:
            if verbose:
                console.print(f"[yellow]⚠️  JSON sans 'args' : {objet}[/yellow]")
            position += fin
            continue
        if not isinstance(objet["args"], dict):
            if verbose:
                console.print(f"[yellow]⚠️  'args' n'est pas un dictionnaire : {objet}[/yellow]")
            position += fin
            continue
            
        objets.append(objet)
        position += fin
    
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


def reponse_termine_tache(reponse: str) -> bool:
    return any(objet.get("outil") == "terminer_tache" for objet in extraire_json_objets(reponse))


def resultat_indique_erreur(resultat: str) -> bool:
    marqueurs = ["Erreur", "Outil inconnu", "Arguments invalides", "Timeout"]
    return any(marqueur in resultat for marqueur in marqueurs)

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
    complexite = estimer_complexite(message, intention_action)
    
    # Ajuster le prompt système selon l'intention
    if intention_action:
        historique[0]["content"] = construire_prompt_action(memoire)
    else:
        historique[0]["content"] = construire_prompt_conversation(memoire)
    
    reponse = None
    provider_cloud_reussi = None
    tentatives = 0
    max_tentatives = 2
    
    while tentatives < max_tentatives:
        tentatives += 1
        providers_cloud = ordonner_providers_cloud(providers_cloud_disponibles(), memoire, complexite)
        
        if providers_cloud:
            if tentatives == 1:
                console.print(f"[dim]→ Cle API cloud detectee. Tentative modeles cloud...[/dim]")
            else:
                console.print(f"[dim yellow]→ Retry modeles cloud (tentative {tentatives})...[/dim yellow]")
            
            for provider in providers_cloud:
                if reponse is not None:
                    break
                nom_provider = provider["nom"]
                modeles = provider["modeles"]
                fonction_chat = provider["fonction"]
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(modeles)) as executor:
                    futures = {executor.submit(fonction_chat, modele, historique): modele for modele in modeles}
                    for future in concurrent.futures.as_completed(futures):
                        modele = futures[future]
                        try:
                            reponse = future.result()
                            provider_cloud_reussi = nom_provider
                            console.print(f"[dim green]✓ {nom_provider} reussi : {modele}[/dim green]")
                            break
                        except Exception as e:
                            console.print(f"[dim yellow]✗ {nom_provider} {modele} indisponible : {str(e)[:100]}[/dim yellow]")
                            continue
        else:
            if tentatives == 1:
                console.print(
                    "[dim yellow]⚠️  Aucune cle API cloud detectee "
                    "(GROQ_API_KEY, TOGETHER_API_KEY ou OPENROUTER_API_KEY).[/dim yellow]"
                )
        
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
                provider_cloud_reussi = None
                continue
        else:
            # Conversation valide, on sort
            break
    
    if reponse is None:
        reponse = {"message": {"content": "Erreur : Impossible d'obtenir une réponse du modèle."}}
    
    contenu = reponse["message"]["content"]
    if provider_cloud_reussi:
        memoriser_provider_cloud(provider_cloud_reussi)
    historique.append({"role": "assistant", "content": contenu})
    limiter_historique(historique)
    return contenu, intention_action


def executer_agent(user_input: str, historique: list, memoire: dict) -> tuple[str, bool]:
    """Boucle agentique courte : action, observation, correction/continuation."""
    reponse, intention_action = parler(user_input, historique, memoire)
    if not intention_action:
        return reponse, False

    complexite = estimer_complexite(user_input, intention_action)
    max_etapes = MAX_ETAPES_AGENT if complexite == "complexe" else 1
    observations = []

    for etape in range(1, max_etapes + 1):
        resultat = executer_outil(reponse)
        if resultat:
            observations.append(f"Etape {etape}:\n{resultat}")
        else:
            resultat = (
                "[red]❌ Erreur : Je n'ai pas pu exécuter cette action car je n'ai pas généré la commande correcte.[/red]\n"
                "[dim]Conseil : Reformulez votre demande ou essayez avec d'autres mots.[/dim]"
            )
            observations.append(f"Etape {etape}:\n{resultat}")
            break

        if reponse_termine_tache(reponse):
            break
        if complexite != "complexe" and not resultat_indique_erreur(resultat):
            break
        if etape >= max_etapes:
            break

        observation = (
            "Observation outil :\n"
            f"{resultat}\n\n"
            "Continue la tache si necessaire avec le prochain JSON d'outil. "
            "Si tout est termine, reponds uniquement avec "
            '{"outil": "terminer_tache", "args": {"resume": "resume court du resultat"}}.'
        )
        reponse, intention_action = parler(observation, historique, memoire)
        if not intention_action:
            observations.append(f"Conclusion:\n{reponse}")
            break

    return "\n\n".join(observations), True

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
                user_input += PLAN_OPTIMISATION

            horodatage = datetime.now().strftime("%H:%M:%S")
            with console.status("[cyan]Jarvis réfléchit...[/cyan]", spinner="dots"):
                reponse, intention_action = executer_agent(user_input, historique, memoire)
            
            OUTILS["enregistrer_echange"](user_input, reponse)
            console.print(Panel(reponse, title=f"Jarvis — {horodatage}", style="cyan"))

        except KeyboardInterrupt:
            console.print("\n[cyan]Jarvis hors ligne.[/cyan]")
            stop_event.set()
            break

if __name__ == "__main__":
    main()
