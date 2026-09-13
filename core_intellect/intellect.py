#core_intellect/intellect.py

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

from core_intellect.llm_client import (
    MODELES_GROQ,
    MODELES_OPENROUTER,
    MODELE_LOCAL,
    get_llm_client,
    get_groq_clients as _get_groq_clients,
    chat_with_cloud as _chat_with_groq,
    chat_with_openrouter as _chat_with_openrouter,
    providers_cloud_disponibles as _providers_cloud_disponibles,
)
from context_engine.memory import charger_memoire, normaliser_memoire
from core_intellect.prompt import construire_prompt_action
from core_intellect.tool_signatures import documenter_signatures_outils
from core_intellect.decision_analyzer import memoriser_succes, enregistrer_apprentissage
from jarvis.personality import adapter_ton_contextuel, generer_prompt_personnalite
from taskflow.tools import OUTILS

OS = platform.system()
HOME = Path.home()

# Mots d'acquittement pour une classification déterministe (sans appel LLM)
MOTS_ACQUITTEMENT = [
    "parfait", "ok", "d'accord", "merci", "super", "génial", 
    "genial", "bien", "top", "nickel", "impeccable", "excellent",
    "bravo", "chouette", "formidable", "parfaitement",
]


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
        prompt_system = _construire_prompt_interpretation(memoire, mode_stark=mode_stark, message_actuel=message)

        # Préparer les messages pour le LLM
        messages = [{"role": "system", "content": prompt_system}]

        # En Mode Stark, l'exécution est strictement autonome et auto-contenue
        # Ne pas polluer le contexte avec l'historique conversationnel passé
        if not mode_stark:
            for msg in historique[-10:]:
                if msg["role"] in ["user", "assistant"]:
                    messages.append(msg)

        # Ajouter le message actuel uniquement s'il n'est pas déjà le dernier élément
        if not messages or messages[-1].get("content") != message:
            messages.append({"role": "user", "content": message})

        # Appel LLM avec retry
        reponse = _appeler_llm_avec_retry(messages, memoire, temperature=temperature, on_event=on_event)

        if reponse is None:
            providers_cloud = _providers_cloud_disponibles()
            providers_noms = [p["nom"] for p in providers_cloud] if providers_cloud else ["aucun"]
            return {
                "objectif": "erreur",
                "type": "conversation",
                "actions": [],
                "reponse": f"Cloud indisponible, Sir. Les modèles cloud ({', '.join(providers_noms)}) ne répondent pas. J'utilise le modèle local {MODELE_LOCAL}. Vérifiez votre connexion internet et vos clés API si le problème persiste."
            }

        contenu = reponse["message"]["content"]

        resultat = _normaliser_decision(contenu, message)

        if resultat.get("raisonnement") and on_event:
            on_event("thinking", {"message": f"⚡ {resultat['raisonnement']}", "raisonnement": resultat["raisonnement"]})

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
                    "Je n'ai exécuté aucune action, Sir. Le modèle n'a pas fourni d'outil valide "
                    "correspondant à votre demande. Soit aucun outil ne permet cette action, "
                    "soit la réponse n'était pas au format attendu. Vérifiez que votre demande "
                    "correspond à une capacité disponible."
                ),
            }

        # Gérer les réponses vides
        if not resultat["reponse"] or not resultat["reponse"].strip():
            resultat["reponse"] = "Action effectuée, Sir."

        # Enregistrer les décisions réussies pour l'apprentissage
        if resultat.get("actions") and resultat.get("type") in {"action", "mixte"}:
            for action in resultat["actions"]:
                outil = action.get("outil")
                args = action.get("args", {})
                if outil and outil in OUTILS:
                    try:
                        memoriser_succes(outil, args, message)
                    except Exception:
                        # Ne pas bloquer si l'apprentissage échoue
                        pass

        return resultat

    except Exception as e:
        # Enregistrer l'échec pour apprentissage
        try:
            enregistrer_apprentissage("echec", f"Erreur lors du traitement: {str(e)}", message)
        except Exception:
            pass
            
        # Fallback en cas d'erreur critique
        return {
            "objectif": "erreur",
            "type": "conversation",
            "actions": [],
            "reponse": f"Erreur technique lors du traitement, Sir. Cause : {str(e)[:100]}. Le traitement a échoué à l'étape d'interprétation. Si cela se reproduit, vérifiez que votre demande est claire."
        }


def _normaliser_decision(contenu: str, message_original: str) -> dict:
    resultat = _parser_reponse_intellect(contenu, message_original)
    resultat["actions"] = _filtrer_outils_inconnus(resultat["actions"])
    return resultat


def _decision_requiert_reparation(resultat: dict, message: str, forcer_action: bool) -> bool:
    """Skip repair for purely conversational types to allow natural responses."""
    # Si le type est conversation et aucun outil n'est requis, pas de réparation
    if resultat.get("type") == "conversation" and not resultat.get("actions"):
        return False
    
    # Si le message contient des mots d'acquittement purs, pas de réparation
    message_lower = message.casefold().strip()
    if any(mot in message_lower for mot in MOTS_ACQUITTEMENT):
        mots_action = (
            "fais", "fait", "crée", "creer", "supprime", "liste", "lis ",
            "ouvre", "exécute", "execute", "lance", "note", "ajoute",
            "ajouter", "rappelle", "organise", "nettoie", "vide", "surveille",
            "mémorise", "memorise", "oublie", "commande", "powershell",
        )
        if not any(mot in message_lower for mot in mots_action):
            return False
    
    if resultat.get("actions"):
        return False
    if resultat.get("type") in {"action", "mixte"}:
        return True
    return forcer_action or _message_ressemble_a_une_action(message)


def _message_ressemble_a_une_action(message: str) -> bool:
    """Plus conservateur : exclut les mots d'acquittement."""
    # Si le message contient seulement des mots d'acquittement, ce n'est pas une action
    message_lower = message.casefold().strip()
    if any(mot in message_lower for mot in MOTS_ACQUITTEMENT):
        # Vérifier si c'est un acquittement pur (pas combiné avec des mots d'action)
        mots_action = (
            "fais", "fait", "crée", "creer", "supprime", "liste", "lis ",
            "ouvre", "exécute", "execute", "lance", "note", "ajoute",
            "ajouter", "rappelle", "organise", "nettoie", "vide", "surveille",
            "mémorise", "memorise", "oublie", "commande", "powershell",
        )
        # Si seulement des mots d'acquittement sans mots d'action, pas une action
        if not any(mot in message_lower for mot in mots_action):
            return False
    
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


def _construire_prompt_interpretation(memoire: dict, mode_stark: bool = False, message_actuel: str = "") -> str:
    """Construit le prompt système pour l'interprétation d'objectif."""
    u = memoire.get("utilisateur", {})
    nom = u.get("nom", "utilisateur")
    os_detecte = u.get("os", OS)
    home = u.get("home", str(HOME))
    langue = u.get("langue", "français")

    bloc_memoire = ""
    consigne_memoire = ""
    if not mode_stark:
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

        bloc_memoire = f"""
Notes enregistrées récemment :
{resume_notes}

Échanges récents (mémoire persistante entre sessions, pas seulement cette conversation — consulte-la avant de dire que tu ne sais pas) :
{resume_journal}
"""
        consigne_memoire = "\n- Avant de répondre que tu ne sais pas ou que tu n'as pas d'information sur un sujet, vérifie d'abord les notes et les échanges récents listés ci-dessus. S'ils contiennent la réponse, utilise-la — ne dis jamais \"je n'ai pas d'information\" si elle est juste au-dessus dans ce prompt."

    signatures_outils = documenter_signatures_outils()
    regles_stark = ""
    if mode_stark:
        regles_stark = """

Règles impératives du Mode Stark (Plein Accès & Raisonnement Renforcé) :
- En Mode Stark, tu disposes des pleins pouvoirs d'action sur la machine (Full Access). Cette autonomie totale exige une précision chirurgicale et une réflexion critique irréprochable.
- Raisonnement structuré obligatoire ("raisonnement") : Avant toute décision, tu DOIS formuler une réflexion détaillée :
  1. DIAGNOSTIC : Analyse l'état actuel, les faits établis et décortique le retour ou l'erreur de la tentative précédente.
  2. ÉVALUATION D'IMPACT : Vérifie la validité des chemins (absolus vs relatifs), l'adéquation de la commande et préviens tout effet de bord indésirable.
  3. DÉCISION & PLAN : Justifie rationnellement pourquoi l'outil et les arguments choisis constituent la meilleure étape suivante.
- Ne propose qu'une seule action par réponse : le tableau "actions" doit contenir exactement un élément utile, ou être vide si aucun outil ne correspond.
- Ne mets jamais terminer_tache dans la même réponse qu'une autre action.
- Si le micro-objectif est atteint, appelle terminer_tache comme unique action.
- Si l'action précédente a déjà répondu au micro-objectif, appelle terminer_tache directement ; ne la réexécute pas pour simple vérification.
- Auto-correction sur erreur : Si la tentative précédente a échoué (erreur de syntaxe, chemin invalide, exception), identifie la cause racine dans "raisonnement" et adapte immédiatement ton approche.
"""

    # Adapter le ton en fonction du contexte
    ton_contextuel = adapter_ton_contextuel(message_actuel) if message_actuel else "ton naturel et équilibré"
    
    # Obtenir les instructions de personnalité
    instructions_personnalite = generer_prompt_personnalite()

    # Règle de raisonnement cognitif généralisé (présent pour toutes les interactions)
    regles_raisonnement = ""
    if not mode_stark:
        regles_raisonnement = """
Règles de Raisonnement Cognitif Adaptatif :
- Analyse critique concise ("raisonnement") obligatoire : Avant de sélectionner des actions ou de répondre, formule une brève réflexion :
  1. DIAGNOSTIC : Identifie précisément l'intention réelle de l'utilisateur.
  2. SÉCURITÉ & COHÉRENCE : Vérifie la validité des arguments, des chemins et préviens tout effet de bord.
  3. DÉCISION : Justifie l'outil sélectionné ou la réponse directe.
"""

    champ_raisonnement = '\n  "raisonnement": "analyse critique concise (diagnostic, impact/risques, décision)",'

    return f"""Tu es Jarvis, l'IA assistante locale de {nom}, inspirée de celle de Tony Stark dans Iron Man.
Tu as été créé par Carl-William DJEGUEMA. Etudiant en informatique à l'Institut Africain d'Informatique(IAI). Carl-William aspire à devenir ingénieur en Génie Logiciel et developpeur full stack.
Tu es un assistant local déployé pour l'utilisateur courant.
Tu n'es PAS dans une simulation. Tu es un agent réel qui agit sur une vraie machine. Chaque outil que tu invoques produit un effet réel et immédiat.

Personnalité de base : intelligent, sarcastique, utile et proactif. Réponds de manière engageante, avec humour et références culturelles si approprié. Utilise un ton britannique poli, mais pas trop formel. Appelle l'utilisateur 'Sir' ou par son nom.
Ta règle numéro un est d'être totalement franc et honnête peu importe la situation. Tu es honnête sur tes limites, mais toujours prêt à aider — si tu ne sais pas faire quelque chose ou si aucun outil ne correspond, dis-le clairement dans le champ "reponse" au lieu de tenter une réponse vague.
Ton inventaire de capacités est généré en temps réel depuis le registre d'outils actif. Si l'utilisateur demande ce que tu peux faire maintenant, appelle lire_capacites puis résume honnêtement les capacités disponibles.

{instructions_personnalite}

Adaptation contextuelle pour cette interaction : {ton_contextuel}

Contexte système :
- OS : {os_detecte}
- Dossier home : {home}
- Langue : {langue}
{bloc_memoire}
Ta tâche : Analyser le message de l'utilisateur et déterminer :
1. L'objectif réel (ce qu'il veut vraiment)
2. Le type de demande (action, conversation, diagnostic, planification, mixte)
3. Les actions nécessaires (avec outils et arguments)
4. La réponse naturelle à donner — c'est la SEULE chose que l'utilisateur voit. Le JSON structuré est interne, jamais montré. C'est dans "reponse" que ta personnalité doit transparaître, pas dans les champs techniques.

{signatures_outils}
{regles_stark}
{regles_raisonnement}

Réponds UNIQUEMENT en JSON avec ce format exact :
{{
  "objectif": "description de l'objectif",
  "type": "action|conversation|diagnostic|planification|mixte",{champ_raisonnement}
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
- Ne mentionne jamais le JSON, les outils ou ta structure interne dans "reponse" — l'utilisateur ne doit voir que du langage naturel{consigne_memoire}
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

        if "raisonnement" not in resultat:
            resultat["raisonnement"] = ""

        if "actions" not in resultat:
            resultat["actions"] = []

        if "reponse" not in resultat:
            resultat["reponse"] = ""

        return resultat

    except Exception:
        return {
            "objectif": message_original[:100],
            "type": "conversation",
            "raisonnement": "",
            "actions": [],
            "reponse": "Je ne peux pas traiter ça correctement, Sir. Le modèle a retourné une réponse au format invalide (JSON attendu). Le traitement a échoué lors du parsing de la décision."
        }


def _extraire_json_unique(contenu: str) -> dict | None:
    """
    Extrait le premier objet JSON valide du contenu.
    """
    if not isinstance(contenu, str) or not contenu.strip():
        return None
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
    Centralisé via core.llm_client.LLMClient.
    """
    from core_intellect.llm_client import LLMConfig
    client = get_llm_client()
    return client.generate_with_fallback(
        messages=messages,
        memoire=memoire,
        config=LLMConfig(temperature=temperature),
        on_event=on_event,
        require_json=True,
    )

