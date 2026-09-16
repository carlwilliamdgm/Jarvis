from greatos_contracts import CapabilityRequest, RiskLevel, SecurityDecision
from datashield.defcon import DefconLevel, defcon
from datashield.policy import evaluate_capability


def test_irreversible_capability_is_always_denied():
    decision = evaluate_capability(CapabilityRequest(
        capability="system.execute_command",
        risk=RiskLevel.SYSTEM,
        irreversible=True,
    ))
    assert decision.decision == SecurityDecision.DENY


def test_defcon_three_requires_confirmation_for_system_capability():
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_3)
        decision = evaluate_capability(CapabilityRequest(
            capability="system.execute_command", risk=RiskLevel.SYSTEM,
        ))
        assert decision.decision == SecurityDecision.CONFIRM
    finally:
        defcon.set_level(previous)


def test_user_space_write_is_allowed_at_nominal_defcon():
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_5)
        decision = evaluate_capability(CapabilityRequest(
            capability="filesystem.write", risk=RiskLevel.WRITE,
        ))
        assert decision.decision == SecurityDecision.ALLOW
    finally:
        defcon.set_level(previous)


def test_defcon_one_blocks_all_capabilities():
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_1)
        for risk in (RiskLevel.READ, RiskLevel.WRITE, RiskLevel.SYSTEM, RiskLevel.DESTRUCTIVE):
            decision = evaluate_capability(CapabilityRequest(
                capability="test.capability", risk=risk,
            ))
            assert decision.decision == SecurityDecision.DENY
    finally:
        defcon.set_level(previous)


def test_destructive_capability_denied_at_defcon_two():
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_2)
        decision = evaluate_capability(CapabilityRequest(
            capability="storage.empty_recycle_bin",
            risk=RiskLevel.DESTRUCTIVE,
            resource="corbeille",
        ))
        assert decision.decision == SecurityDecision.DENY
    finally:
        defcon.set_level(previous)


def test_write_capability_requires_confirmation_at_defcon_two():
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_2)
        decision = evaluate_capability(CapabilityRequest(
            capability="storage.clean_temp",
            risk=RiskLevel.WRITE,
            resource="temp",
        ))
        assert decision.decision == SecurityDecision.CONFIRM
    finally:
        defcon.set_level(previous)


def test_syncsphere_snapshot_blocked_at_defcon_one():
    from syncsphere.tools import creer_snapshot_systeme_tool
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_1)
        res = creer_snapshot_systeme_tool("test_snap")
        assert "DEFCON 1" in str(res)
    finally:
        defcon.set_level(previous)


def test_empty_recycle_bin_blocked_at_defcon_two():
    from taskflow.tools import vider_corbeille
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_2)
        res = vider_corbeille()
        assert "DEFCON 2" in str(res)
    finally:
        defcon.set_level(previous)


def test_browser_navigate_blocked_at_defcon_one():
    from taskflow.tools import naviguer_vers_tool
    previous = defcon.current_level
    try:
        defcon.set_level(DefconLevel.DEFCON_1)
        res = naviguer_vers_tool("https://example.com")
        assert "DEFCON 1" in str(res)
    finally:
        defcon.set_level(previous)

