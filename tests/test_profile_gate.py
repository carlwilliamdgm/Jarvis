import threading
from types import SimpleNamespace
from unittest.mock import patch

from datashield.profile_gate import ProfileExecutionGate, profile_execution_gate


def test_action_step_drains_across_lock_and_old_generation_stays_closed_after_unlock():
    gate = ProfileExecutionGate()
    generation = gate.generation
    started = threading.Event()
    finish = threading.Event()

    def action():
        with gate.action_step(generation) as admitted:
            assert admitted
            started.set()
            assert finish.wait(timeout=2)

    worker = threading.Thread(target=action)
    worker.start()
    assert started.wait(timeout=2)
    gate.set_locked(True)
    assert gate.active_action_steps == 1
    with gate.action_step(generation) as admitted:
        assert not admitted
    finish.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert gate.active_action_steps == 0

    # Even an immediate unlock must not resume work from the pre-lock plan.
    gate.set_locked(False)
    with gate.action_step(generation) as admitted:
        assert not admitted


def test_runtime_teardown_waits_for_active_action_step():
    from interface_morphique import server

    gate = profile_execution_gate
    previous_locked = gate.locked
    previous_windows_locked = server.WINDOWS_SESSION_LOCKED.is_set()
    if previous_locked:
        gate.set_locked(False)
    action_generation = gate.generation
    app = SimpleNamespace(state=SimpleNamespace())
    stopped = threading.Event()
    try:
        with patch.object(server, "_stop_profile_runtime", side_effect=lambda *_: stopped.set()):
            with gate.action_step(action_generation) as admitted:
                assert admitted
                gate.set_locked(True)
                server.WINDOWS_SESSION_LOCKED.set()
                lock_generation = gate.generation
                worker = server._stop_profile_runtime_after_active_steps(
                    app, "test_lock", lock_generation
                )
                assert worker is not None
                assert not stopped.wait(timeout=0.05)
            worker.join(timeout=2)
            assert not worker.is_alive()
            assert stopped.is_set()
    finally:
        server.WINDOWS_SESSION_LOCKED.set() if previous_windows_locked else server.WINDOWS_SESSION_LOCKED.clear()
        gate.set_locked(previous_locked)


def test_plan_finishes_admitted_capability_but_does_not_dispatch_next_step():
    from greatos_contracts import CapabilityResult, CapabilityStatus, ExecutionPlan, PlanStep
    from interface_morphique import server
    from jarvis.agent import orchestrer_plan

    gate = profile_execution_gate
    previous_locked = gate.locked
    previous_windows_locked = server.WINDOWS_SESSION_LOCKED.is_set()
    if previous_locked:
        gate.set_locked(False)
    generation = gate.generation
    first_started = threading.Event()
    dispatched = []

    def first_capability():
        first_started.set()
        # Simulate the OS lock arriving while this capability is in flight.
        gate.set_locked(True)
        server.WINDOWS_SESSION_LOCKED.set()
        return ["sensitive-result"]

    def second_capability():
        dispatched.append("second")
        return {"ok": True}

    plan = ExecutionPlan(goal="lock boundary", steps=[
        PlanStep(id="step_1", capability="goals.list", arguments={}),
        PlanStep(id="step_2", capability="goals.statistics", arguments={}),
    ])
    try:
        with (
            patch.dict("jarvis.agent.OUTILS", {
                "lister_objectifs": first_capability,
                "stats_objectifs": second_capability,
            }),
            patch("jarvis.agent._confirmer_selon_confiance", return_value=True),
            patch("jarvis.agent.journaliser_resultat_capacite") as persist_result,
            patch("jarvis.agent.enregistrer_impact_capacite") as persist_impact,
            patch("jarvis.agent.evaluate_capability") as evaluate,
        ):
            evaluate.return_value.decision.value = "allow"
            evaluate.return_value.reason = "allowed"
            results = orchestrer_plan(plan, {}, expected_generation=generation)
        assert first_started.is_set()
        assert dispatched == []
        assert persist_result.call_count == 0
        assert persist_impact.call_count == 0
        assert len(results) == 1
        assert results[0].error_category == "profil_verrouille"
        assert "masqué" in results[0].message
    finally:
        server.WINDOWS_SESSION_LOCKED.set() if previous_windows_locked else server.WINDOWS_SESSION_LOCKED.clear()
        gate.set_locked(previous_locked)


def test_direct_capability_is_indivisible_and_teardown_waits_for_it():
    from greatos_capabilities import execute_capability
    from interface_morphique import server

    gate = profile_execution_gate
    previous_locked = gate.locked
    previous_windows_locked = server.WINDOWS_SESSION_LOCKED.is_set()
    if previous_locked:
        gate.set_locked(False)
    entered = threading.Event()
    finish = threading.Event()
    app = SimpleNamespace(state=SimpleNamespace())
    stopped = threading.Event()
    results = []

    def blocking_list_goals():
        entered.set()
        gate.set_locked(True)
        server.WINDOWS_SESSION_LOCKED.set()
        assert finish.wait(timeout=2)
        return ["sensitive-goal"]

    registry = {"lister_objectifs": blocking_list_goals}
    try:
        with patch.object(server, "_stop_profile_runtime", side_effect=lambda *_: stopped.set()):
            caller = threading.Thread(
                target=lambda: results.append(execute_capability(registry, "goals.list", {}))
            )
            caller.start()
            assert entered.wait(timeout=2)
            assert gate.active_action_steps == 1
            lock_worker = server._stop_profile_runtime_after_active_steps(
                app, "test_direct_action", gate.generation
            )
            assert lock_worker is not None
            assert not stopped.wait(timeout=0.05)
            finish.set()
            caller.join(timeout=2)
            lock_worker.join(timeout=2)
        assert not caller.is_alive()
        assert not lock_worker.is_alive()
        assert stopped.is_set()
        assert len(results) == 1
        assert results[0].status.value == "success"
    finally:
        finish.set()
        server.WINDOWS_SESSION_LOCKED.set() if previous_windows_locked else server.WINDOWS_SESSION_LOCKED.clear()
        gate.set_locked(previous_locked)


def test_unlock_remains_blocked_while_old_autonomous_agent_thread_lives():
    from interface_morphique import server

    stopped = threading.Event()
    worker = threading.Thread(target=lambda: stopped.wait(timeout=2), daemon=True)
    worker.start()
    try:
        with patch.object(server, "_agent_thread", worker):
            assert server._profile_workers_pending(SimpleNamespace(state=SimpleNamespace()))
    finally:
        stopped.set()
        worker.join(timeout=2)
