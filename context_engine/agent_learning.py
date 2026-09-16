"""Mémoire durable des sessions d'agents intervenant sur GreatOS.

Le journal JSONL est la source de vérité : chaque ligne est un événement
autonome, facile à relire, versionner et indexer. ``SUIVI_PROJET.md`` est une
vue humaine régénérée à partir de ce journal ; il ne doit pas être édité à la
main pour éviter les divergences.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PROJECT_ROOT / "learning" / "agent_sessions.jsonl"
DEFAULT_STATUS_PATH = PROJECT_ROOT / "SUIVI_PROJET.md"
_LOG_LOCK = threading.RLock()

REQUIRED_FIELDS = ("agent", "summary", "status")
VALID_STATUSES = {"completed", "in_progress", "blocked", "review"}


def _as_list(values: Iterable[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _normalise_entry(entry: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if not str(entry.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Champs obligatoires absents : {', '.join(missing)}")

    status = str(entry["status"]).strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"Statut invalide : {status}. Valeurs admises : {', '.join(sorted(VALID_STATUSES))}")

    return {
        "id": str(entry.get("id") or uuid4().hex),
        "timestamp": str(entry.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        "agent": str(entry["agent"]).strip(),
        "session": str(entry.get("session") or "").strip(),
        "status": status,
        "summary": str(entry["summary"]).strip(),
        "decisions": _as_list(entry.get("decisions")),
        "changes": _as_list(entry.get("changes")),
        "verification": _as_list(entry.get("verification")),
        "blockers": _as_list(entry.get("blockers")),
        "learnings": _as_list(entry.get("learnings")),
        "next_steps": _as_list(entry.get("next_steps")),
        "references": _as_list(entry.get("references")),
    }


def read_agent_sessions(log_path: Path | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Retourne les entrées valides, de la plus récente à la plus ancienne."""
    path = log_path or DEFAULT_LOG_PATH
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with _LOG_LOCK:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            try:
                parsed = json.loads(raw_line)
                if isinstance(parsed, dict):
                    entries.append(parsed)
            except json.JSONDecodeError:
                # Un journal doit rester consultable même après une écriture
                # interrompue : les lignes valides antérieures sont conservées.
                continue
    entries.reverse()
    return entries[:limit] if limit is not None else entries


def format_agent_sessions(limit: int = 10, log_path: Path | None = None) -> str:
    """Produit une vue compacte exploitable par Jarvis dans une réponse."""
    entries = read_agent_sessions(log_path, limit=max(1, min(int(limit), 50)))
    if not entries:
        return "Aucune session d'agent n'est encore journalisée."

    lines = ["=== JOURNAL D'APPRENTISSAGE DES AGENTS ==="]
    for entry in entries:
        lines.extend([
            f"- {entry.get('timestamp', '?')} | {entry.get('agent', '?')} | {entry.get('status', '?')}",
            f"  Sujet : {entry.get('summary', '')}",
        ])
        if entry.get("next_steps"):
            lines.append(f"  À suivre : {' ; '.join(entry['next_steps'])}")
        if entry.get("blockers"):
            lines.append(f"  Blocages : {' ; '.join(entry['blockers'])}")
    return "\n".join(lines)


def _markdown_list(values: list[str], empty: str = "Aucun élément signalé.") -> str:
    return "\n".join(f"- {value}" for value in values) if values else f"- {empty}"


def render_project_status(entries: list[dict[str, Any]], output_path: Path | None = None) -> Path:
    """Régénère la vue de suivi humaine depuis le journal structuré."""
    target = output_path or DEFAULT_STATUS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    current = next((entry for entry in entries if entry.get("status") == "in_progress"), None)
    latest = entries[:10]

    lines = [
        "# Suivi vivant de GreatOS",
        "",
        "> Vue générée depuis `learning/agent_sessions.jsonl`. Ne pas modifier manuellement : utilisez `scripts/log_agent_session.py`.",
        "",
        "## État courant",
        "",
    ]
    if current:
        lines.extend([
            f"- Responsable : {current['agent']}",
            f"- Session : {current['session'] or 'non renseignée'}",
            f"- Sujet : {current['summary']}",
            "- Prochaines étapes :",
            _markdown_list(current.get("next_steps", [])),
        ])
    else:
        lines.append("- Aucune session marquée `in_progress`.")

    lines.extend(["", "## Journal récent", ""])
    if not latest:
        lines.append("Aucune session journalisée pour le moment.")
    for entry in latest:
        lines.extend([
            f"### {entry.get('timestamp', '?')} — {entry.get('agent', '?')} — {entry.get('status', '?')}",
            "",
            entry.get("summary", ""),
            "",
            "**Décisions**",
            _markdown_list(entry.get("decisions", [])),
            "",
            "**Changements**",
            _markdown_list(entry.get("changes", [])),
            "",
            "**Vérification**",
            _markdown_list(entry.get("verification", [])),
            "",
            "**Blocages**",
            _markdown_list(entry.get("blockers", [])),
            "",
            "**À suivre**",
            _markdown_list(entry.get("next_steps", [])),
            "",
        ])
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def record_agent_session(
    *,
    agent: str,
    summary: str,
    status: str,
    session: str = "",
    decisions: Iterable[str] | None = None,
    changes: Iterable[str] | None = None,
    verification: Iterable[str] | None = None,
    blockers: Iterable[str] | None = None,
    learnings: Iterable[str] | None = None,
    next_steps: Iterable[str] | None = None,
    references: Iterable[str] | None = None,
    log_path: Path | None = None,
    status_path: Path | None = None,
) -> dict[str, Any]:
    """Ajoute une session de façon atomique puis actualise le suivi humain."""
    entry = _normalise_entry(locals())
    path = log_path or DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"

    with _LOG_LOCK:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        render_project_status(read_agent_sessions(path), status_path)
    return entry
