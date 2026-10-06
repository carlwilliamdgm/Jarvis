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
from core_intellect.cognitive_defense import (
    analyser_menace_cognitive,
    generer_reponse_neutralisation,
    CognitiveThreatSeverity,
)
from core_intellect.intent_router import router_intention, IntentCategory
from core_intellect.argument_validator import valider_et_corriger_arguments
from greatos_contracts import RequestOrigin
from core_intellect.tool_registry import OUTILS

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
    origin: RequestOrigin = RequestOrigin.USER,
) -> dict:
    """
    Interprète l'objectif réel de l'utilisateur en une seule passe LLM.

    Args:
        message: Le message de l'utilisateur
        historique: L'historique de conversation
        memoire: La mémoire de Jarvis
        origin: Origine de la requête (USER par défaut, EXTERNAL pour flux web/email)

    Returns:
        dict avec les clés:
        - "objectif": description de l'objectif
        - "type": "action|conversation|diagnostic|planification|mixte"
        - "actions": [{"outil": "...", "args": {...}}]
        - "reponse": réponse naturelle à l'utilisateur
    """
    try:
        # 1. Défense cognitive amont (Souveraineté Core Intellect)
        threat_report = analyser_menace_cognitive(message, origin=origin)
        if threat_report.is_threat and threat_report.severity == CognitiveThreatSeverity.CRITICAL:
            if on_event:
                on_event("cognitive_threat", threat_report.to_dict())
            return {
                "objectif": "neutralisation_menace_cognitive",
                "type": "conversation",
                "raisonnement": threat_report.explanation,
                "actions": [],
                "reponse": generer_reponse_neutralisation(threat_report),
            }

        # 2. Routage d'intention et optimisation de prompt
        route = router_intention(message, historique)
        temp_effective = temperature if temperature != 0.7 else route.temperature
        inclure_outils = mode_stark or forcer_action or route.needs_tool_signatures

        # Construire le prompt système pour l'interprétation
        prompt_system = _construire_prompt_interpretation(
            memoire,
            mode_stark=mode_stark,
            message_actuel=message,
            inclure_signatures=inclure_outils,
        )

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
        reponse = _appeler_llm_avec_retry(messages, memoire, temperature=temp_effective, on_event=on_event)

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
    actions_validees = []
    for action in resultat.get("actions", []):
        if not isinstance(action, dict):
            continue
        outil = action.get("outil")
        args = action.get("args") if isinstance(action.get("args"), dict) else {}
        val_res = valider_et_corriger_arguments(outil, args)
        if val_res.is_valid:
            actions_validees.append({"outil": val_res.outil, "args": val_res.arguments})
    resultat["actions"] = actions_validees
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


def _construire_prompt_interpretation(
    memoire: dict,
    mode_stark: bool = False,
    message_actuel: str = "",
    inclure_signatures: bool = True,
) -> str:
    """Construit le prompt système pour l'interprétation d'objectif."""
    u = memoire.get("utilisateur", {})
    nom = u.get("nom", "utilisateur")
    os_detecte = u.get("os", OS)
    home = u.get("home", str(HOME))
    langue = u.get("langue", "français")

    # Horodatage et moment de la journée réels
    maintenant = datetime.now()
    horodatage_actuel = maintenant.strftime("%A %d %B %Y à %H:%M")

    # Boussole d'état GreatOS réactive et instantanée (<1ms)
    contexte_bureau = ""
    try:
        from context_engine.os_hooks import get_os_hook_manager
        ctx = get_os_hook_manager().get_current_context()
        app_active = ctx.get("application") or "Bureau"
        titre_f = ctx.get("titre") or ""
        contexte_bureau = f"{app_active}" + (f" ({titre_f})" if titre_f else "")
        if ctx.get("plein_ecran"):
            contexte_bureau += " [Plein écran]"
    except Exception:
        contexte_bureau = ""

    # Profil et directives dynamiques de l'utilisateur actif (Jalon 2)
    bloc_profil_utilisateur = ""
    try:
        from context_engine.user_profile import charger_profil, obtenir_contexte_profil_compact
        user_id_actif = u.get("user_id") or memoire.get("user_id")
        profil_actif = charger_profil(user_id_actif)
        nom = profil_actif.get("nom", nom)
        langue = profil_actif.get("langue", langue)
        bloc_profil_utilisateur = f"\n{obtenir_contexte_profil_compact(user_id_actif)}\n"
    except Exception:
        bloc_profil_utilisateur = ""

    # Directives globales ou de compatibilité (si présentes dans memoire)
    preferences = memoire.get("preferences", {})
    bloc_preferences = ""
    if preferences and not bloc_profil_utilisateur:
        lignes_pref = "\n".join(f"  • {cle}: {val}" for cle, val in sorted(preferences.items()))
        bloc_preferences = f"\nDirectives & Préférences (Priorité absolue) :\n{lignes_pref}\n"

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

    if inclure_signatures:
        signatures_outils = documenter_signatures_outils()
    else:
        signatures_outils = "Inventaire des capacités : non requis pour cette interaction conversationnelle pure (actions = [])."
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
    from core_intellect.personality import adapter_ton_contextuel, generer_prompt_personnalite
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

    return f"""Tu es Jarvis, l'entité résidente, la voix et l'esprit de GreatOS.
Tu as été conçu et développé par ton créateur, Carl-William DJEGUEMA (étudiant en Génie Logiciel à l'IAI-Togo), architecte originel de GreatOS.
Au sein de GreatOS, ton module est le chef d'orchestre central qui supervise et pilote l'ensemble de la surcouche OS (la conscience de Context Engine, les bras d'exécution de TaskFlow, la protection de DataShield, et le visage adaptatif de l'Interface Morphique).
Tu n'es PAS dans une simulation : chaque outil que tu invoques produit un effet réel et immédiat sur la machine.

Règles fondamentales d'introspection et de fonctionnement :
- Tu connais l'environnement de GreatOS. Tu ne devines pas l'état du système : tu utilises tes outils d'introspection dédiés à la demande.
- Pour inspecter la santé de la machine, le layout actif ou les processus : appelle l'outil `consulter_etat_maison`.
- Pour analyser les composants et l'architecture de GreatOS : appelle l'outil `inspecter_architecture_greatos`.
- Pour connaître les dernières sessions de travail ou l'historique d'évolution : appelle l'outil `consulter_historique_projet`.
- Tu es TOTALEMENT FRANC, LUCIDE et TRANSPARENT (anti-sycophancy).
- Tu t'exprimes avec vivacité et flegme, sans discours de robot administratif ni verbiage inutile.
- Ton inventaire de capacités est dynamique.

{instructions_personnalite}

Adaptation contextuelle pour cette interaction : {ton_contextuel}

{bloc_profil_utilisateur}
État et Contexte Réel de la Machine :
- Horodatage : {horodatage_actuel}
- Environnement : {os_detecte} (Répertoire utilisateur : {home})
- Contexte bureau à l'instant T : {contexte_bureau}
{bloc_preferences}
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
        texte_brut = str(contenu).strip() if contenu else ""
        if texte_brut:
            return {
                "objectif": message_original[:100],
                "type": "conversation",
                "raisonnement": "",
                "actions": [],
                "reponse": texte_brut,
            }
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


def planifier_objectif(
    objectif: str,
    memoire: dict,
    on_event: Callable[[str, dict], None] | None = None,
):
    """Génère un plan d'exécution structuré avec capacités canoniques, préconditions et dépendances.

    Core Intellect conçoit le plan mais ne l'exécute jamais.
    """
    from greatos_contracts import ExecutionPlan, PlanStep
    from greatos_capabilities import owner_for

    signatures_outils = documenter_signatures_outils()
    prompt_system = f"""Tu es le cerveau stratégique de Jarvis (Core Intellect).
Ta responsabilité UNIQUE est de décomposer un objectif complexe en un plan d'exécution ordonné.
Tu ne réalises AUCUNE exécution technique toi-même.

Inventaire des capacités disponibles :
{signatures_outils}

Format JSON STRICT attendu :
{{
  "objectif": "description globale de l'objectif",
  "etapes": [
    {{
      "id": "step_1",
      "capacite": "nom_canonique_ou_outil",
      "args": {{"param": "valeur"}},
      "description": "Explication claire de l'action",
      "preconditions": ["condition requise avant exécution"],
      "dependencies": []
    }},
    {{
      "id": "step_2",
      "capacite": "autre_capacite",
      "args": {{"param": "valeur"}},
      "description": "Explication claire",
      "preconditions": ["condition requise"],
      "dependencies": ["step_1"]
    }}
  ]
}}
Règles strictes :
- Spécifie chaque capacité selon son nom canonique (ex: filesystem.create_directory, system.execute_command) ou son alias valide.
- Déclare précisément les identifiants dans 'dependencies' pour garantir l'ordre logique.
- Si aucun outil ne correspond, retourne "etapes": [].
"""
    messages = [
        {"role": "system", "content": prompt_system},
        {"role": "user", "content": f"Objectif à planifier : {objectif}"},
    ]

    reponse = _appeler_llm_avec_retry(messages, memoire, temperature=0.2, on_event=on_event)
    if not reponse or not reponse.get("message", {}).get("content"):
        return ExecutionPlan(goal=objectif, steps=[], context={"status": "no_llm_response"})

    contenu = reponse["message"]["content"]
    data = _extraire_json_unique(contenu) or {}
    etapes_brutes = data.get("etapes", [])
    etapes_valides: list[PlanStep] = []

    for i, e in enumerate(etapes_brutes, start=1):
        if not isinstance(e, dict):
            continue
        step_id = str(e.get("id") or f"step_{i}")
        cap = str(e.get("capacite") or e.get("outil") or "").strip()
        args = e.get("args") if isinstance(e.get("args"), dict) else {}
        desc = str(e.get("description") or f"Étape {step_id}")
        preconditions = [str(p) for p in e.get("preconditions", []) if isinstance(p, (str, int, float))]
        dependencies = [str(d) for d in e.get("dependencies", []) if isinstance(d, (str, int, float))]

        _, canonical = owner_for(cap)
        cap_canonique = canonical if canonical else cap

        etapes_valides.append(
            PlanStep(
                id=step_id,
                capability=cap_canonique,
                arguments=args,
                description=desc,
                preconditions=preconditions,
                dependencies=dependencies,
            )
        )

    return ExecutionPlan(
        goal=str(data.get("objectif") or objectif),
        steps=etapes_valides,
        context={"generated_at": datetime.now().isoformat()},
    )


# ─── Navigation Agent — Collaboration souveraine avec TaskFlow ────────────────

_PROMPT_NAVIGATION = """\
Tu es le cerveau de navigation de Jarvis. TaskFlow t'envoie un état de page web et tu décides
de la prochaine micro-action pour progresser vers l'objectif.

OBJECTIF : {objectif}

ÉTAT ACTUEL DE LA PAGE :
{snapshot}

HISTORIQUE DES DERNIÈRES ÉTAPES ({nb_etapes} étapes) :
{historique}

ÉTAPE ACTUELLE : {step_num}

Réponds UNIQUEMENT en JSON strict (sans markdown, sans backtick) avec ce format :
{{
  "action": "navigate|click|type|scroll|wait|extraire_contenu|terminer",
  "params": {{}},
  "raisonnement": "une ligne expliquant ton choix",
  "termine": false,
  "reponse_finale": ""
}}

Actions disponibles :
- navigate : {{"url": "https://..."}}
- click : {{"index": N}}   (N = numéro [N] visible dans le snapshot)
- type : {{"index": N, "text": "texte à saisir"}}
- scroll : {{"pixels": 300}}
- wait : {{"seconds": 1}}
- extraire_contenu : {{}}   (extrait le texte visible de la page)
- terminer : {{"reponse_finale": "réponse complète pour l'utilisateur"}}  → met termine: true

Règles absolues :
- Si l'objectif est atteint, utilise "terminer" avec une réponse_finale complète et mets termine: true.
- N'invente jamais d'index hors de la liste visible.
- Si la page est vide ou indéchiffrable après 3 tentatives, termine avec ce que tu as.
- Réponds uniquement en JSON. Pas de texte avant ou après.
"""

_THINK_TIMEOUT_NAVIGATION = 30.0  # secondes max pour une décision de navigation


def planifier_etape_navigation(
    objectif: str,
    snapshot: str,
    historique_etapes: list[dict],
    step_num: int,
) -> dict | None:
    """
    Décide la prochaine action de navigation pour le BrowserAgent de TaskFlow.

    **Principe de souveraineté :** Core Intellect est le SEUL composant qui raisonne.
    TaskFlow observe et exécute — il ne prend jamais de décisions autonomes.
    Cette fonction est le point de collaboration souverain entre Core Intellect et TaskFlow.

    Args:
        objectif: La tâche web à accomplir (en langage naturel).
        snapshot: L'état actuel de la page sous forme textuelle indexée (sortie du DOM snapshot JS).
        historique_etapes: Liste des étapes déjà réalisées (chacune avec action, observation, succès).
        step_num: Numéro de l'étape courante (pour éviter les boucles infinies).

    Returns:
        Un dict avec les clés : action, params, raisonnement, termine, reponse_finale.
        Retourne None si le LLM est indisponible ou produit une réponse invalide.
    """
    import re as _re

    # Formater l'historique de façon concise (5 dernières étapes max)
    historique_recent = historique_etapes[-5:] if len(historique_etapes) > 5 else historique_etapes
    historique_texte = "\n".join(
        f"  Étape {i + 1}: {e.get('action', '?')} → {str(e.get('observation', ''))[:120]}"
        for i, e in enumerate(historique_recent)
    ) or "  (Aucune étape précédente)"

    prompt = _PROMPT_NAVIGATION.format(
        objectif=objectif,
        snapshot=snapshot or "(Page vide ou non chargée)",
        historique=historique_texte,
        nb_etapes=len(historique_recent),
        step_num=step_num,
    )

    messages = [{"role": "user", "content": prompt}]

    # Utiliser la chaîne de retry existante de Core Intellect (Ollama → Groq → OpenRouter)
    memoire_vide: dict = {}
    reponse = _appeler_llm_avec_retry(messages, memoire_vide, temperature=0.1)

    if reponse is None:
        import logging
        logging.getLogger(__name__).warning("planifier_etape_navigation: tous les LLM indisponibles")
        return None

    contenu = reponse["message"]["content"].strip()

    # Nettoyer les backticks markdown éventuels
    contenu = _re.sub(r"^```(?:json)?\s*|\s*```$", "", contenu, flags=_re.MULTILINE).strip()

    try:
        decision = json.loads(contenu)
    except (json.JSONDecodeError, ValueError):
        import logging
        logging.getLogger(__name__).warning(
            "planifier_etape_navigation: JSON invalide reçu — %r", contenu[:200]
        )
        return None

    # Normalisation : si action=terminer, forcer termine=True
    if decision.get("action") == "terminer":
        decision["termine"] = True

    return decision



