"""Propositions inertes de capacités manquantes, soumises à revue humaine."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from context_engine.paths import JARVIS_DIR


PROPOSALS_PATH = JARVIS_DIR / "learning" / "capability_proposals.jsonl"


def proposer_nouvelle_capacite(action_echouee: str, contexte: str = "") -> dict:
    """Enregistre un squelette inerte; aucune proposition n'est chargée comme outil."""
    action = re.sub(r"[^\w.:-]", "_", str(action_echouee).strip())[:120] or "capacite_inconnue"
    prototype = (
        "def capability_candidate(**arguments):\n"
        f"    raise NotImplementedError({('Proposition à examiner: ' + action)!r})\n"
    )
    record = {
        "id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "review_required",
        "capability_requested": action,
        "context_summary": str(contexte).strip()[:300],
        "prototype": prototype,
        "executable": False,
        "approval_required": True,
    }
    PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROPOSALS_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
    return record
