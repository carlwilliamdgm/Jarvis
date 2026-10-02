#capabilities/memory_tools.py

import re
from datetime import datetime

from context_engine.memory import CATEGORIES_CONTEXTE, charger_memoire, normaliser_memoire, sauvegarder_memoire


def noter(note: str) -> str:
    data = normaliser_memoire(charger_memoire())
    notes = data.get("notes", [])
    notes.append({"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "contenu": note})
    data["notes"] = notes
    sauvegarder_memoire(data)
    return "Note enregistree."


def lire_notes() -> str:
    data = normaliser_memoire(charger_memoire())
    notes = data.get("notes", [])
    if not notes:
        return "Aucune note enregistree."
    return "\n".join([f"[{n['date']}] {n['contenu']}" for n in notes])


def memoriser_contexte(categorie: str, cle: str, valeur: str) -> str:
    categorie = str(categorie).lower().strip()
    if categorie not in CATEGORIES_CONTEXTE:
        return f"Categorie inconnue : {categorie}. Categories : {', '.join(sorted(CATEGORIES_CONTEXTE))}"
    data = normaliser_memoire(charger_memoire())
    data["contexte"][categorie][str(cle)] = {
        "valeur": str(valeur),
        "maj": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    sauvegarder_memoire(data)
    return f"Contexte memorise [{categorie}] {cle} = {valeur}"


def lire_contexte(categorie: str | None = None) -> str:
    data = normaliser_memoire(charger_memoire())
    contexte = data.get("contexte", {})
    categories = [categorie.lower().strip()] if categorie else sorted(CATEGORIES_CONTEXTE)
    lignes = []
    for cat in categories:
        if cat not in contexte:
            continue
        valeurs = contexte.get(cat, {})
        if not valeurs:
            continue
        lignes.append(f"[{cat}]")
        for cle, entree in sorted(valeurs.items()):
            valeur = entree.get("valeur", entree) if isinstance(entree, dict) else entree
            lignes.append(f"- {cle}: {valeur}")
    return "\n".join(lignes) if lignes else "Aucun contexte personnel enregistre."


def oublier_contexte(categorie: str, cle: str) -> str:
    categorie = str(categorie).lower().strip()
    data = normaliser_memoire(charger_memoire())
    valeurs = data.get("contexte", {}).get(categorie)
    if not valeurs or cle not in valeurs:
        return f"Contexte introuvable : [{categorie}] {cle}"
    del valeurs[cle]
    sauvegarder_memoire(data)
    return f"Contexte supprime : [{categorie}] {cle}"


def memoriser_preference(cle: str, valeur: str) -> str:
    data = normaliser_memoire(charger_memoire())
    data["preferences"][str(cle)] = str(valeur)
    sauvegarder_memoire(data)
    return f"Preference enregistree : {cle} = {valeur}"


def lire_preferences() -> str:
    data = normaliser_memoire(charger_memoire())
    preferences = data.get("preferences", {})
    if not preferences:
        return "Aucune preference enregistree."
    return "\n".join(f"- {cle}: {valeur}" for cle, valeur in sorted(preferences.items()))


def oublier_preference(cle: str) -> str:
    data = normaliser_memoire(charger_memoire())
    preferences = data.get("preferences", {})
    if cle not in preferences:
        return f"Preference introuvable : {cle}"
    del preferences[cle]
    sauvegarder_memoire(data)
    return f"Preference supprimee : {cle}"


def lire_journal_agents(limite: int = 10) -> str:
    """Lit le relais durable laissé par les agents de développement du projet."""
    from context_engine.agent_learning import format_agent_sessions
    try:
        return format_agent_sessions(limite)
    except (TypeError, ValueError):
        return "Limite invalide pour le journal des agents."


def lire_traces_capacites(limite: int = 10) -> str:
    """Consulte les traces d'exécution des capacités GreatOS enregistrées dans Context Engine."""
    from context_engine.memory import consulter_trace_capacites
    try:
        traces = consulter_trace_capacites(limite=limite)
        if not traces:
            return "Aucune trace de capacité enregistrée pour le moment."
        lignes = []
        for t in traces:
            date_str = t.get("date", "")
            owner = t.get("owner", "inconnu")
            cap = t.get("capability", t.get("outil", ""))
            statut = t.get("status", "")
            duree = t.get("duree_ms", 0)
            res = str(t.get("resultat", ""))[:100]
            lignes.append(f"[{date_str}] {cap} ({owner}) -> {statut} ({duree}ms) : {res}")
        return "\n".join(lignes)
    except Exception as e:
        return f"Erreur lors de la lecture des traces de capacités : {e}"


# ============================================================================
# INTERCEPTEUR DE DIRECTIVES - JALON 1
# ============================================================================

_AMORCES = r"(?:(?:jarvis|dis[- ]moi|s'il\s+(?:te|vous)\s+pla[îi]t)[,\s]+)?"

_PATTERNS_DIRECTIVES = [
    # Formes de retenue - doit explicitement contenir "retiens"
    rf"^{_AMORCES}retiens\s+(?:bien\s+)?(?:que\s+)?(.+?)[.!?]?$",
    # Formes temporelles
    rf"^{_AMORCES}(?:à\s+l'avenir|désormais|dorénavant|à\s+partir\s+de\s+maintenant|a\s+l'avenir|desormais|a\s+partir\s+de\s+maintenant)\s*,?\s*(.+?)[.!?]?$",
    # Formes d'interdiction - capture le verbe + l'objet (élargi avec génère, utilise, produis, cesse...)
    rf"^{_AMORCES}(?:ne\s+)?(?:fais\s+plus|fait\s+plus|génère\s+plus|génères\s+plus|genere\s+plus|affiche\s+plus|affiches\s+plus|n'affiche\s+plus|utilise\s+plus|utilises\s+plus|n'utilise\s+plus|produis\s+plus|mets\s+plus|évite\s+de|evite\s+de|arrête\s+de|arrete\s+de|cesse\s+de|ne\s+plus)\s+(?:de\s+|d')?(.+?)[.!?]?$",
    # Formes d'exigence
    rf"^{_AMORCES}(?:je\s+veux\s+que\s+tu|je\s+voudrais\s+que\s+tu|je\s+te\s+demande\s+de)\s+(.+?)[.!?]?$",
]

_PATTERNS_QUESTIONS = [
    rf"^{_AMORCES}est-ce\s+que\s+",
    rf"^{_AMORCES}tu\s+(?:sais|connais|peux)\s+",
    rf"^{_AMORCES}comment\s+",
    rf"^{_AMORCES}pourquoi\s+",
    rf"^{_AMORCES}qu'est-ce\s+que\s+",
    rf"^{_AMORCES}c'est\s+quoi\s+",
]


def intercepter_directive(message: str, user_id: str | None = None) -> tuple[bool, str, str, str] | None:
    """
    Intercepte et persiste les directives utilisateur de manière déterministe.

    Détecte les patterns de directives (retenue, temporel, interdiction, exigence)
    et les persiste immédiatement dans le profil de l'utilisateur actif,
    sans recopier ses consignes dans la mémoire globale ni appeler le LLM.

    Args:
        message: Le message utilisateur à analyser.
        user_id: Identifiant utilisateur optionnel pour Jalon 2 (multi-utilisateurs).
                 Si None, résolu dynamiquement via user_profile.resoudre_utilisateur_actif().

    Returns:
        None si ce n'est pas une directive (continue le flux normal).
        Tuple (True, consigne, cle, reponse) si directive détectée :
            - consigne: le corps de la directive nettoyé
            - cle: la clé générée pour la préférence
            - reponse: la réponse Jarvis à afficher (court-circuite LLM)
    """
    message_nettoye = message.strip()
    if not message_nettoye:
        return None

    # Éliminer les questions (faux positifs)
    message_lower = message_nettoye.lower()
    if any(re.search(pattern, message_lower, re.IGNORECASE) for pattern in _PATTERNS_QUESTIONS):
        return None

    # Tester chaque pattern de directive
    for pattern in _PATTERNS_DIRECTIVES:
        match = re.search(pattern, message_nettoye, re.IGNORECASE)
        if match:
            consigne = match.group(1).strip()
            if not consigne or len(consigne) < 3:
                continue

            # Nettoyer la ponctuation finale
            consigne = re.sub(r"[.!?]+$", "", consigne).strip()

            # Générer une clé pertinente (basée sur les premiers mots ou horodatée)
            mots_cle = re.findall(r"\b\w+\b", consigne.lower())[:3]
            if mots_cle:
                cle_base = "_".join(mots_cle)
            else:
                cle_base = "directive"

            # Ajouter un timestamp pour éviter les collisions
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cle = f"{cle_base}_{timestamp}"

            # Le profil est la source de vérité multi-utilisateurs.
            try:
                from context_engine.user_profile import mettre_a_jour_directive_profil
                mettre_a_jour_directive_profil(cle, consigne, user_id)
            except Exception:
                # Ne pas acquitter une directive qui n'a pas été durablement
                # ancrée dans l'espace de l'utilisateur actif.
                return None

            # Générer la réponse Jarvis (ton naturel, zéro coût LLM)
            reponse = f"Directive ancrée, Sir. Je retiens : « {consigne} »"

            return (True, consigne, cle, reponse)

    return None
