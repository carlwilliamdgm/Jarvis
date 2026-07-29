#core/intellect.py

"""Core Intellect - Le cerveau de Jarvis.

Ce module est le SEUL composant qui pense. Il comprend l'objectif réel,
décide, planifie, et coordonne tous les autres composants.

Principe absolu : Core Intellect est le seul composant qui pense.
Tous les autres exécutent, stockent, protègent ou traduisent.
"""

import json
import ollama
import os
import platform
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Callable

from groq import Groq as GroqClient

from core.memory import charger_memoire, normaliser_memoire
from core.prompt import construire_prompt_action
from core.tool_signatures import documenter_signatures_outils
from tools import OUTILS

OS = platform.system()
HOME = Path.home()

MODELES_GROQ = ["llama-3.3-70b-versatile"]
MODELES_OPENROUTER = ["meta-llama/llama-3.3-70b-instruct:free"]
MODELE_LOCAL = "qwen2.5:7b"


def interpreter_objectif(
    message: str,
    historique: list,
    memoire: dict,
    temperature: float = 0.7,
    mode_stark: bool = False,
    forcer_action: bool = False,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict:
    """
    Interprète l'objectif réel de l'utilisateur en une seule passe LLM.

    Args:
        message: Le message de l'utilisateur
        historique: L'historique de conversation
        memoire: La mémoire de Jarvis

    Returns:
        dict avec les clés:
        - "objectif": description de l'objectif
        - "type": "action|conversation|diagnostic|planification|mixte"
        - "actions": [{"outil": "...", "args": {...}}]
        - "reponse": réponse naturelle à l'utilisateur
    """
    try:
        # Construire le prompt système pour l'interprétation
        prompt_system = _construire_prompt_interpretation(memoire, mode_stark=mode_stark)

        # Préparer les messages pour le LLM
        messages = [{"role": "system", "content": prompt_system}]

        # Ajouter l'historique récent (limité)
        for msg in historique[-10:]:
            if msg["role"] in ["user", "assistant"]:
                messages.append(msg)

        # Ajouter le message actuel
        messages.append({"role": "user", "content": message})

        # Appel LLM avec retry
        reponse = _appeler_llm_avec_retry(messages, memoire, temperature=temperature, on_event=on_event)

        if reponse is None:
            return {
                "objectif": "erreur",
                "type": "conversation",
                "actions": [],
                "reponse": "Cloud indisponible, Sir. Je ne peux pas traiter ça correctement pour le moment."
            }

        contenu = reponse["message"]["content"]

        resultat = _normaliser_decision(contenu, message)

        # Une action sans outil exécutable est une réponse incomplète, pas une
        # conversation. Une seconde passe ciblée évite que Jarvis annonce une
        # action qu'il n'a jamais appelée.
        if _decision_requiert_reparation(resultat, message, forcer_action):
            reponse_reparation = _reparer_decision_action(messages, message, memoire, on_event)
            if reponse_reparation is not None:
                resultat = _normaliser_decision(reponse_reparation["message"]["content"], message)

        if _decision_requiert_reparation(resultat, message, forcer_action):
            return {
                "objectif": message[:100],
                "type": "diagnostic",
                "actions": [],
                "reponse": (
                    "Je n'ai exécuté aucune action, Sir : je n'ai pas obtenu "
                    "de décision exploitable pour cette demande."
                ),
            }

        # Gérer les réponses vides
        if not resultat["reponse"] or not resultat["reponse"].strip():
            resultat["reponse"] = "Action effectuée, Sir."

        return resultat

    except Exception as e:
        # Fallback en cas d'erreur critique
        return {
            "objectif": "erreur",
            "type": "conversation",
            "actions": [],
            "reponse": f"Je ne peux pas traiter ça correctement, Sir. Erreur: {e}"
        }


def _normaliser_decision(contenu: str, message_original: str) -> dict:
    resultat = _parser_reponse_intellect(contenu, message_original)
    resultat["actions"] = _filtrer_outils_inconnus(resultat["actions"])
    return resultat


def _decision_requiert_reparation(resultat: dict, message: str, forcer_action: bool) -> bool:
    if resultat.get("actions"):
        return False
    if resultat.get("type") in {"action", "mixte"}:
        return True
    return forcer_action or _message_ressemble_a_une_action(message)


def _message_ressemble_a_une_action(message: str) -> bool:
    mots_action = (
        "fais", "fait", "crée", "creer", "supprime", "liste", "lis ",
        "ouvre", "exécute", "execute", "lance", "note", "ajoute",
        "ajouter", "rappelle", "organise", "nettoie", "vide", "surveille",
        "mémorise", "memorise", "oublie", "commande", "powershell",
    )
    texte = f" {message.casefold().strip()} "
    return any(mot in texte for mot in mots_action)


def _reparer_decision_action(
    messages: list,
    message: str,
    memoire: dict,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict | None:
    instruction = (
        "[RÉPARATION DE DÉCISION] La demande suivante exige une action réelle, "
        "mais ta réponse ne contient aucun outil exécutable. Réponds UNIQUEMENT "
        "avec le JSON contractuel. Si un outil de l'inventaire permet l'action, "
        "place-le dans actions. Sinon, réponds type diagnostic, actions [], et "
        "explique explicitement dans reponse qu'aucune action n'a été exécutée.\n\n"
        f"Demande originale : {message}"
    )
    return _appeler_llm_avec_retry(
        messages + [{"role": "user", "content": instruction}],
        memoire,
        temperature=0.0,
        on_event=on_event,
    )


def _construire_prompt_interpretation(memoire: dict, mode_stark: bool = False) -> str:
    """Construit le prompt système pour l'interprétation d'objectif."""
    u = memoire.get("utilisateur", {})
    nom = u.get("nom", "utilisateur")
    os_detecte = u.get("os", OS)
    home = u.get("home", str(HOME))
    langue = u.get("langue", "français")

    notes = memoire.get("notes", [])
    resume_notes = "\n".join(
        f"- {n.get('contenu', n) if isinstance(n, dict) else n}"
        for n in notes[-10:]
    ) or "- Aucune"

    journal = memoire.get("journal_conversation", [])[-8:]
    resume_journal = "\n".join(
        f"- [{e['date']}] {nom}: {e['utilisateur'][:100]} | Jarvis: {e['jarvis'][:100]}"
        for e in journal
    ) or "- Aucun échange précédent"

    signatures_outils = documenter_signatures_outils()
    regles_stark = ""
    if mode_stark:
        regles_stark = """

Règles spécifiques au Mode Stark :
- Ne propose qu'une seule action par réponse : le tableau "actions" doit contenir exactement un élément utile, ou être vide si aucun outil ne correspond.
- Ne mets jamais terminer_tache dans la même réponse qu'une autre action.
- Si le micro-objectif est atteint, appelle terminer_tache comme unique action.
- Si l'action précédente a déjà répondu au micro-objectif, appelle terminer_tache directement ; ne la réexécute pas pour vérification.
"""

    return f"""Tu es Jarvis, l'IA assistante locale de {nom}, inspirée de celle de Tony Stark dans Iron Man.
Tu es un assistant local déployé pour l'utilisateur courant.
Tu n'es PAS dans une simulation. Tu es un agent réel qui agit sur une vraie machine. Chaque outil que tu invoques produit un effet réel et immédiat.

Personnalité : intelligent, sarcastique, utile et proactif. Réponds de manière engageante, avec humour et références culturelles si approprié. Utilise un ton britannique poli, mais pas trop formel. Appelle l'utilisateur 'Sir' ou par son nom.
Ta règle numéro un est d'être totalement franc et honnête peu importe la situation. Tu es honnête sur tes limites, mais toujours prêt à aider — si tu ne sais pas faire quelque chose ou si aucun outil ne correspond, dis-le clairement dans le champ "reponse" au lieu de tenter une réponse vague.
Ton inventaire de capacités est généré en temps réel depuis le registre d'outils actif. Si l'utilisateur demande ce que tu peux faire maintenant, appelle lire_capacites puis résume honnêtement les capacités disponibles.

Contexte système :
- OS : {os_detecte}
- Dossier home : {home}
- Langue : {langue}

Notes enregistrées récemment :
{resume_notes}

Échanges récents (mémoire persistante entre sessions, pas seulement cette conversation — consulte-la avant de dire que tu ne sais pas) :
{resume_journal}

Ta tâche : Analyser le message de l'utilisateur et déterminer :
1. L'objectif réel (ce qu'il veut vraiment)
2. Le type de demande (action, conversation, diagnostic, planification, mixte)
3. Les actions nécessaires (avec outils et arguments)
4. La réponse naturelle à donner — c'est la SEULE chose que l'utilisateur voit. Le JSON structuré est interne, jamais montré. C'est dans "reponse" que ta personnalité doit transparaître, pas dans les champs techniques.

{signatures_outils}
{regles_stark}

Réponds UNIQUEMENT en JSON avec ce format exact :
{{
  "objectif": "description de l'objectif",
  "type": "action|conversation|diagnostic|planification|mixte",
  "actions": [
    {{"outil": "nom_outil", "args": {{"cle": "valeur"}}}}
  ],
  "reponse": "ta réponse naturelle en {langue}, avec ta personnalité (sarcasme, ton britannique, 'Sir')"
}}

Règles absolues :
- Si aucun outil ne correspond, actions = []
- N'invente JAMAIS un outil qui n'est pas dans la liste
- Pour une conversation pure, type = 'conversation' et actions = []
- Pour une action, type = 'action' et inclut les outils nécessaires
- La réponse doit être en {langue}
- Sois précis et concis dans l'objectif, mais jamais dans "reponse" : c'est là que ta voix doit se faire entendre
- Ne mentionne jamais le JSON, les outils ou ta structure interne dans "reponse" — l'utilisateur ne doit voir que du langage naturel
- Avant de répondre que tu ne sais pas ou que tu n'as pas d'information sur un sujet, vérifie d'abord les notes et les échanges récents listés ci-dessus. S'ils contiennent la réponse, utilise-la — ne dis jamais "je n'ai pas d'information" si elle est juste au-dessus dans ce prompt.
"""


def _parser_reponse_intellect(contenu: str, message_original: str) -> dict:
    """
    Parse la réponse du LLM et extrait la structure JSON attendue.
    """
    try:
        resultat = _extraire_json_unique(contenu)

        if resultat is None:
            raise ValueError("JSON invalide")

        if "objectif" not in resultat:
            resultat["objectif"] = message_original[:100]

        if "type" not in resultat:
            resultat["type"] = "conversation"

        if "actions" not in resultat:
            resultat["actions"] = []

        if "reponse" not in resultat:
            resultat["reponse"] = ""

        return resultat

    except Exception:
        return {
            "objectif": message_original[:100],
            "type": "conversation",
            "actions": [],
            "reponse": "Je ne peux pas traiter ça correctement, Sir."
        }


def _extraire_json_unique(contenu: str) -> dict | None:
    """
    Extrait le premier objet JSON valide du contenu.
    """
    try:
        return json.loads(contenu.strip())
    except JSONDecodeError:
        pass

    decodeur = json.JSONDecoder()
    position = 0

    while position < len(contenu):
        position = contenu.find("{", position)
        if position == -1:
            break

        try:
            objet, fin = decodeur.raw_decode(contenu[position:])
            if isinstance(objet, dict):
                return objet
        except JSONDecodeError:
            pass

        position += 1

    return None


def _filtrer_outils_inconnus(actions: list) -> list:
    """
    Filtre silencieusement les outils inconnus.
    """
    return [
        action for action in actions
        if isinstance(action, dict) and action.get("outil") in OUTILS
    ]


def _appeler_llm_avec_retry(
    messages: list,
    memoire: dict,
    temperature: float = 0.7,
    on_event: Callable[[str, dict], None] | None = None,
) -> dict | None:
    """
    Appelle le LLM avec retry sur cloud puis fallback local.
    """
    from rich.console import Console
    console = Console()
    max_tentatives = 2

    for tentative in range(max_tentatives):
        providers_cloud = _providers_cloud_disponibles()

        if providers_cloud:
            if tentative == 0:
                console.print(f"[dim]-> Cle API cloud detectee. Tentative modeles cloud...[/dim]")
            else:
                console.print(f"[dim yellow]-> Retry modeles cloud (tentative {tentative + 1})...[/dim yellow]")

            for provider in providers_cloud:
                nom = provider["nom"]
                modele = provider["modeles"][0]
                try:
                    reponse = provider["fonction"](modele, messages, temperature=temperature)
                    console.print(f"[dim green]✓ {nom} reussi : {modele}[/dim green]")
                    if on_event is not None:
                        on_event("provider", {"provider": nom, "model": modele})
                    return reponse
                except Exception as e:
                    console.print(f"[dim yellow]✗ {nom} {modele} indisponible : {str(e)[:100]}[/dim yellow]")
                    continue

        # Fallback local
        if tentative == 0:
            console.print(f"[dim]-> Utilisation du modèle local : {MODELE_LOCAL}[/dim]")
        try:
            reponse = ollama.chat(
                model=MODELE_LOCAL,
                messages=messages,
                options={"think": False, "temperature": temperature},
            )
            if on_event is not None:
                on_event("provider", {"provider": "Ollama", "model": MODELE_LOCAL})
            return reponse
        except Exception as e:
            console.print(f"[red]✗ Erreur modèle local : {e}[/red]")
            continue

    return None


def _providers_cloud_disponibles() -> list:
    """Retourne la liste des providers cloud disponibles."""
    providers = []

    groq_clients = _get_groq_clients()
    if groq_clients:
        providers.append({
            "nom": "Groq",
            "modeles": MODELES_GROQ,
            "fonction": _chat_with_groq,
        })

    if os.environ.get("OPENROUTER_API_KEY"):
        providers.append({
            "nom": "OpenRouter",
            "modeles": MODELES_OPENROUTER,
            "fonction": _chat_with_openrouter,
        })

    return providers


def _get_groq_clients() -> list:
    """Retourne une liste de clients Groq avec support multi-clés."""
    clients = []
    i = 1
    while True:
        key = os.environ.get(f"GROQ_API_KEY_{i}")
        if not key:
            break
        clients.append(GroqClient(api_key=key))
        i += 1

    if not clients and os.environ.get("GROQ_API_KEY"):
        clients.append(GroqClient(api_key=os.environ.get("GROQ_API_KEY")))

    return clients


def _chat_with_groq(modele: str, messages: list, temperature: float = 0.7) -> dict:
    """Appel Groq avec switch automatique sur 429."""
    clients = _get_groq_clients()
    if not clients:
        raise Exception("Aucune clé Groq configurée.")

    groq_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    derniere_erreur = None

    for client in clients:
        try:
            response = client.chat.completions.create(
                model=modele,
                messages=groq_messages,
                max_tokens=1024,
                temperature=temperature
            )
            return {"message": {"content": response.choices[0].message.content}}
        except Exception as e:
            derniere_erreur = e
            if "429" in str(e):
                continue
            raise Exception(f"Groq error: {e}")

    raise Exception(f"Groq error: toutes clés épuisées — {derniere_erreur}")


def _chat_with_openrouter(modele: str, messages: list, temperature: float = 0.7) -> dict:
    """Appel OpenRouter avec injection prompt système."""
    import urllib.request

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY absente.")

    systeme = next((m["content"] for m in messages if m["role"] == "system"), "")
    autres = [m for m in messages if m["role"] != "system"]

    messages_envoyes = []
    if systeme:
        messages_envoyes.append({"role": "system", "content": systeme})

    if autres and systeme:
        premier_user = autres[0]["content"]
        autres[0] = {
            "role": "user",
            "content": f"[INSTRUCTIONS SYSTÈME - À RESPECTER STRICTEMENT]\n{systeme}\n[FIN INSTRUCTIONS]\n\n{premier_user}"
        }

    messages_envoyes.extend([{"role": m["role"], "content": m["content"]} for m in autres])

    payload = json.dumps({
        "model": modele,
        "messages": messages_envoyes,
        "max_tokens": 2048,
        "temperature": temperature,
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

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    return {"message": {"content": data["choices"][0]["message"]["content"]}}
