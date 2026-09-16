from greatos_capabilities import LegacyToolRegistry, CapabilityDescriptor
from greatos_contracts import CapabilityResult, CapabilityStatus
from taskflow.tools import OUTILS


def test_outils_is_legacy_tool_registry_instance():
    assert isinstance(OUTILS, LegacyToolRegistry)
    assert isinstance(OUTILS, dict)
    assert len(OUTILS) > 0


def test_legacy_tool_registry_execute_capability():
    res = OUTILS.execute("goals.list")
    assert isinstance(res, CapabilityResult)
    assert res.status == CapabilityStatus.SUCCESS
    assert res.capability == "goals.list"


def test_legacy_tool_registry_resolve_canonical_and_legacy():
    desc1 = OUTILS.resolve("creer_dossier")
    desc2 = OUTILS.resolve("filesystem.create_directory")
    assert desc1 is not None
    assert desc2 is not None
    assert desc1.name == desc2.name == "filesystem.create_directory"
    assert desc1.legacy_tool == desc2.legacy_tool == "creer_dossier"
    assert desc1.owner == "taskflow"


def test_legacy_tool_registry_list_descriptors():
    descriptors = OUTILS.list_descriptors()
    assert len(descriptors) > 0
    assert all(isinstance(d, CapabilityDescriptor) for d in descriptors)
    names = {d.name for d in descriptors}
    assert "filesystem.create_directory" in names
    assert "security.get_defcon" in names


def test_dict_backwards_compatibility_preserved():
    assert "creer_dossier" in OUTILS
    assert callable(OUTILS["creer_dossier"])
    assert "obtenir_niveau_defcon" in OUTILS
    keys = list(OUTILS.keys())
    assert len(keys) == len(OUTILS)


def test_scheduler_uses_capability_dispatcher():
    from taskflow.scheduler import executer_action_automatisation
    auto = {
        "nom": "Test Auto",
        "outil": "goals.list",
        "args": {},
        "statut": "active",
    }
    res = executer_action_automatisation(auto, OUTILS, mettre_a_jour_prochaine=False)
    assert "Test Auto :" in res
    assert auto.get("derniere_execution") is not None
