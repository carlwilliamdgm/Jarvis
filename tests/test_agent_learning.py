from pathlib import Path

import pytest

from context_engine.agent_learning import format_agent_sessions, read_agent_sessions, record_agent_session


def test_record_session_writes_structured_log_and_living_status(tmp_path: Path):
    log_path = tmp_path / "agent_sessions.jsonl"
    status_path = tmp_path / "SUIVI_PROJET.md"

    entry = record_agent_session(
        agent="Codex",
        session="session-1",
        summary="Centralisation du journal d'apprentissage.",
        status="in_progress",
        decisions=["Le JSONL est la source de vérité."],
        changes=["context_engine/agent_learning.py"],
        verification=["Test unitaire."],
        next_steps=["Exposer la lecture à Jarvis."],
        log_path=log_path,
        status_path=status_path,
    )

    assert entry["agent"] == "Codex"
    assert read_agent_sessions(log_path) == [entry]
    content = status_path.read_text(encoding="utf-8")
    assert "Centralisation du journal" in content
    assert "Responsable : Codex" in content
    formatted = format_agent_sessions(1, log_path=log_path)
    assert "JOURNAL D'APPRENTISSAGE" in formatted
    assert "Centralisation du journal" in formatted


def test_invalid_status_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="Statut invalide"):
        record_agent_session(
            agent="Devin",
            summary="Essai.",
            status="unknown",
            log_path=tmp_path / "agent_sessions.jsonl",
            status_path=tmp_path / "SUIVI_PROJET.md",
        )
