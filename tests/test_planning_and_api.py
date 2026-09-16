from unittest.mock import MagicMock, patch
from greatos_contracts import (
    CapabilityResult,
    CapabilityStatus,
    ExecutionPlan,
    PlanStep,
    RiskLevel,
    SecurityDecision,
)
from datashield.defcon import DefconLevel, defcon
from jarvis.agent import orchestrer_plan
from core_intellect.intellect import planifier_objectif


def test_contracts_plan_step_and_execution_plan():
    step = PlanStep(
        id="s1",
        capability="filesystem.create_directory",
        arguments={"chemin": "test_dir"},
        description="Créer répertoire test",
        preconditions=["parent exists"],
        dependencies=[],
    )
    assert step.id == "s1"
    assert step.capability == "filesystem.create_directory"
    assert step.dependencies == []

    plan = ExecutionPlan(
        goal="Préparer environnement",
        steps=[step],
        context={"auteur": "test"},
    )
    assert plan.goal == "Préparer environnement"
    assert len(plan.steps) == 1


def test_core_intellect_planifier_objectif_with_mock_llm():
    mock_llm_json = {
        "objectif": "Créer un dossier puis un fichier",
        "etapes": [
            {
                "id": "step_1",
                "capacite": "creer_dossier",
                "args": {"chemin": "mon_dossier"},
                "description": "Créer le dossier",
                "preconditions": [],
                "dependencies": [],
            },
            {
                "id": "step_2",
                "capacite": "creer_fichier",
                "args": {"chemin": "mon_dossier/test.txt", "contenu": "salut"},
                "description": "Créer le fichier",
                "preconditions": ["dossier step_1 créé"],
                "dependencies": ["step_1"],
            },
        ],
    }

    import json
    mock_reponse = {"message": {"content": json.dumps(mock_llm_json)}}

    with patch("core_intellect.intellect._appeler_llm_avec_retry", return_value=mock_reponse):
        plan = planifier_objectif("Créer un dossier puis un fichier", memoire={})
        assert plan.goal == "Créer un dossier puis un fichier"
        assert len(plan.steps) == 2
        assert plan.steps[0].id == "step_1"
        assert plan.steps[0].capability == "filesystem.create_directory"
        assert plan.steps[1].dependencies == ["step_1"]
        assert plan.steps[1].capability == "filesystem.create_file"



def test_jarvis_orchestrer_plan_events_and_execution():
    events_recus = []

    def capter_event(event_type: str, data: dict):
        events_recus.append((event_type, data))

    step1 = PlanStep(
        id="step_1",
        capability="goals.list",
        arguments={},
        description="Lister les objectifs",
    )
    plan = ExecutionPlan(goal="Test orchestration", steps=[step1])

    resultats = orchestrer_plan(plan, memoire={}, on_event=capter_event)

    assert len(resultats) == 1
    assert resultats[0].status == CapabilityStatus.SUCCESS

    types_events = [t for t, _ in events_recus]
    assert "plan_created" in types_events
    assert "step_started" in types_events
    assert "policy_decision" in types_events
    assert "tool_started" in types_events
    assert "step_completed" in types_events
    assert "plan_completed" in types_events

    policy_events = [d for t, d in events_recus if t == "policy_decision"]
    assert len(policy_events) == 1
    assert policy_events[0]["step_id"] == "step_1"
    assert policy_events[0]["decision"] == "allow"


def test_jarvis_orchestrer_plan_fails_when_dependency_fails():
    events_recus = []

    def capter_event(event_type: str, data: dict):
        events_recus.append((event_type, data))

    step1 = PlanStep(
        id="step_1",
        capability="system.execute_command",
        arguments={"commande": "commande_totalement_invalide_xyz_123"},
        description="Étape vouée à l'échec",
    )
    step2 = PlanStep(
        id="step_2",
        capability="goals.list",
        arguments={},
        dependencies=["step_1"],
        description="Étape dépendante",
    )
    plan = ExecutionPlan(goal="Test dépendances", steps=[step1, step2])

    resultats = orchestrer_plan(plan, memoire={}, on_event=capter_event)

    assert len(resultats) == 2
    assert resultats[1].status == CapabilityStatus.FAILED
    assert resultats[1].error_category == "dependance_non_satisfaite"

    types_events = [t for t, _ in events_recus]
    assert "plan_interrupted" in types_events


def test_jarvis_orchestrer_plan_blocked_by_defcon():
    events_recus = []

    def capter_event(event_type: str, data: dict):
        events_recus.append((event_type, data))

    step1 = PlanStep(
        id="step_1",
        capability="system.execute_command",
        arguments={"commande": "dir"},
        description="Commande système",
    )
    plan = ExecutionPlan(goal="Test DEFCON", steps=[step1])

    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_1)
        resultats = orchestrer_plan(plan, memoire={}, on_event=capter_event)

        assert len(resultats) == 1
        assert resultats[0].status == CapabilityStatus.DENIED

        policy_events = [d for t, d in events_recus if t == "policy_decision"]
        assert len(policy_events) == 1
        assert policy_events[0]["decision"] == "deny"
    finally:
        defcon.set_level(previous)


def test_api_create_plan_endpoint():
    import asyncio
    from interface_morphique.server import PlanRequest, create_plan

    req = PlanRequest(goal="Créer un espace de travail")
    mock_plan = ExecutionPlan(
        goal="Créer un espace de travail",
        steps=[
            PlanStep(
                id="s1",
                capability="filesystem.create_directory",
                arguments={"chemin": "mon_projet"},
                description="Créer le dossier",
            )
        ],
    )
    with patch("core_intellect.intellect.planifier_objectif", return_value=mock_plan):
        res = asyncio.run(create_plan(req, _auth=True))
        assert res["goal"] == "Créer un espace de travail"
        assert res["total_steps"] == 1
        assert res["steps"][0]["id"] == "s1"
        assert res["steps"][0]["capability"] == "filesystem.create_directory"

