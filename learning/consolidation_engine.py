"""Consolidation quotidienne de statistiques de confiance par profil."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from context_engine.trust_registry import PROFILES_DIR
from context_engine.user_profile import charger_profil, resoudre_utilisateur_actif, sauvegarder_profil


def consolider_apprentissages(user_id: str | None = None, maintenant: datetime | None = None) -> dict:
    """Consolide les résultats des 7 derniers jours en tendances explicables.

    Cette opération ne crée pas de directives et ne promeut pas l'autonomie :
    les seuils de confiance sont appliqués en ligne par trust_registry.
    """
    user = resoudre_utilisateur_actif(user_id)
    now = maintenant or datetime.now().astimezone()
    since = now - timedelta(days=7)
    matrix_path = PROFILES_DIR / user / "trust_matrix.json"
    matrix = {}
    if matrix_path.exists():
        try:
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            matrix = {}

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

    profile = charger_profil(user)
    profile["apprentissages_consolides"] = snapshot
    sauvegarder_profil(profile, user)

    log_path = PROFILES_DIR / user / "consolidation.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return snapshot


def consolider_si_due(user_id: str | None = None, maintenant: datetime | None = None) -> dict | None:
    """Lance au plus une consolidation par jour à partir de 02:00 local."""
    now = maintenant or datetime.now().astimezone()
    if now.hour != 2:
        return None
    user = resoudre_utilisateur_actif(user_id)
    state_path = PROFILES_DIR / user / "consolidation-state.json"
    today = now.date().isoformat()
    try:
        last = json.loads(state_path.read_text(encoding="utf-8")).get("date")
    except (OSError, json.JSONDecodeError):
        last = None
    if last == today:
        return None
    snapshot = consolider_apprentissages(user, maintenant=now)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"date": today}, ensure_ascii=False), encoding="utf-8")
    return snapshot
