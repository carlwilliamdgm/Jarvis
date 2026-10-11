"""Propositions inertes de capacités manquantes, soumises à revue humaine."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from context_engine.encrypted_user_store import append_encrypted_jsonl
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
    append_encrypted_jsonl(PROPOSALS_PATH, record)
    return record
