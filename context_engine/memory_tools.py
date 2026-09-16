#capabilities/memory_tools.py

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
