"""CLI commune pour le passage de relais entre agents GreatOS."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context_engine.agent_learning import record_agent_session


def _items(values: list[str] | None) -> list[str]:
    return values or []


def main() -> int:
    parser = argparse.ArgumentParser(description="Journalise une session d'agent GreatOS.")
    parser.add_argument("--agent", required=True, help="Nom de l'agent : Codex, Devin, Antigravity, etc.")
    parser.add_argument("--summary", required=True, help="Résultat ou objectif de la session.")
    parser.add_argument("--status", required=True, choices=["completed", "in_progress", "blocked", "review"])
    parser.add_argument("--session", default="", help="Identifiant de session optionnel.")
    for name, help_text in (
        ("decisions", "Décision durable prise"),
        ("changes", "Fichier ou comportement modifié"),
        ("verification", "Test ou contrôle effectué"),
        ("blockers", "Blocage concret"),
        ("learnings", "Apprentissage réutilisable"),
        ("next-steps", "Prochaine étape actionnable"),
        ("references", "Fichier ou source concerné"),
    ):
        parser.add_argument(f"--{name}", action="append", metavar="TEXTE", help=help_text)
    args = parser.parse_args()
    entry = record_agent_session(
        agent=args.agent,
        summary=args.summary,
        status=args.status,
        session=args.session,
        decisions=_items(args.decisions),
        changes=_items(args.changes),
        verification=_items(args.verification),
        blockers=_items(args.blockers),
        learnings=_items(args.learnings),
        next_steps=_items(args.next_steps),
        references=_items(args.references),
    )
    print(f"Session journalisée : {entry['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
