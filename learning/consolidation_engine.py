"""Consolidation quotidienne de statistiques de confiance par profil."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from context_engine.encrypted_user_store import append_encrypted_jsonl, load_encrypted_json, save_encrypted_json
from context_engine.trust_registry import PROFILES_DIR
from context_engine.user_profile import resoudre_utilisateur_actif, transaction_profil


def consolider_apprentissages(user_id: str | None = None, maintenant: datetime | None = None) -> dict:
    """Consolide les résultats des 7 derniers jours en tendances explicables.

    Cette opération ne crée pas de directives et ne promeut pas l'autonomie :
    les seuils de confiance sont appliqués en ligne par trust_registry.
    """
    user = resoudre_utilisateur_actif(user_id)
    now = maintenant or datetime.now().astimezone()
    since = now - timedelta(days=7)
    matrix_path = PROFILES_DIR / user / "trust_matrix.json"
    matrix = load_encrypted_json(matrix_path, lambda: {"domaines": {}})
    if not isinstance(matrix, dict) or not isinstance(matrix.get("domaines"), dict):
        raise RuntimeError("Matrice de confiance invalide; consolidation refusée.")

    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"succes": 0, "echecs": 0})
    for result in matrix.get("historique_resultats", []):
        try:
            date = datetime.fromisoformat(result["date"])
            if date.tzinfo is None:
                date = date.replace(tzinfo=now.tzinfo or timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if date >= since:
            bucket = grouped[str(result.get("domaine", "inconnu"))]
            bucket["succes" if result.get("succes") else "echecs"] += 1

    tendances = {
        domaine: {
            **counts,
            "score": round(counts["succes"] / max(1, counts["succes"] + counts["echecs"]), 3),
        }
        for domaine, counts in sorted(grouped.items())
    }
    snapshot = {
        "consolide_le": now.isoformat(),
        "periode_jours": 7,
        "domaines_observes": tendances,
    }

    with transaction_profil(user) as profile:
        profile["apprentissages_consolides"] = snapshot

    log_path = PROFILES_DIR / user / "consolidation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    append_encrypted_jsonl(log_path, snapshot)
    return snapshot


def consolider_si_due(user_id: str | None = None, maintenant: datetime | None = None) -> dict | None:
    """Lance au plus une consolidation par jour à partir de 02:00 local."""
    now = maintenant or datetime.now().astimezone()
    if now.hour != 2:
        return None
    user = resoudre_utilisateur_actif(user_id)
    state_path = PROFILES_DIR / user / "consolidation-state.json"
    today = now.date().isoformat()
    state = load_encrypted_json(state_path, lambda: {})
    if not isinstance(state, dict):
        raise RuntimeError("État de consolidation invalide; écriture refusée.")
    last = state.get("date")
    if last == today:
        return None
    snapshot = consolider_apprentissages(user, maintenant=now)
    save_encrypted_json(state_path, {"date": today})
    return snapshot
