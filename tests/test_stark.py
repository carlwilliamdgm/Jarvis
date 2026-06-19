import unittest

import jarvis
from core.stark_parser import parser_objectif_stark
from core.stark_session import STARK_ACTIF_PATH


class StarkParserTests(unittest.TestCase):
    def test_simple_objective_is_single_segment(self):
        plan = parser_objectif_stark("note acheter du pain")

        self.assertEqual(1, len(plan.segments))
        self.assertEqual([["note acheter du pain"]], [branche.actions for branche in plan.segments[0].branches])

    def test_precedence_groups_or_inside_and_inside_sequence(self):
        plan = parser_objectif_stark("a && b || c >> d && (e || f)")

        self.assertEqual(2, len(plan.segments))
        self.assertEqual([["a"], ["b", "c"]], [branche.actions for branche in plan.segments[0].branches])
        self.assertEqual([["d"], ["e", "f"]], [branche.actions for branche in plan.segments[1].branches])


class StarkExecutionTests(unittest.TestCase):
    def tearDown(self):
        STARK_ACTIF_PATH.unlink(missing_ok=True)
        jarvis.desactiver_mode_stark()

    def test_simple_stark_objective_finishes_as_one_micro_objective(self):
        old_interpreter = jarvis.interpreter_objectif
        appels = []

        def fake_interpreter(message, historique, memoire):
            appels.append(message)
            return {
                "actions": [{"outil": "terminer_tache", "args": {"resume": "ok"}}],
                "reponse": "ok",
            }

        jarvis.interpreter_objectif = fake_interpreter
        try:
            rapport = jarvis.executer_mode_stark("note acheter du pain", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter

        self.assertEqual(1, len(appels))
        self.assertIn("Micro-objectif courant :\nnote acheter du pain", appels[0])
        self.assertIn("1. réussi", rapport)

    def test_sequence_short_circuits_after_failed_segment(self):
        old_interpreter = jarvis.interpreter_objectif
        appels = []

        def fake_interpreter(message, historique, memoire):
            appels.append(message)
            return {"actions": [], "reponse": "rien"}

        jarvis.interpreter_objectif = fake_interpreter
        try:
            rapport = jarvis.executer_mode_stark("premier >> second", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter

        self.assertEqual(1, len(appels))
        self.assertIn("1. échoué", rapport)
        self.assertIn("2. jamais tenté à cause d'une dépendance non satisfaite", rapport)

    def test_repeated_identical_attempt_stops_as_stagnation(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("stark_test_same")
        appels = []

        def fake_interpreter(message, historique, memoire):
            appels.append(message)
            return {
                "actions": [{"outil": "stark_test_same", "args": {"valeur": "x"}}],
                "reponse": "encore",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["stark_test_same"] = lambda valeur: "meme resultat"
        try:
            rapport = jarvis.executer_mode_stark("faire x", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("stark_test_same", None)
            else:
                jarvis.OUTILS["stark_test_same"] = old_tool

        self.assertEqual(2, len(appels))
        self.assertIn("Piétinement détecté", rapport)


if __name__ == "__main__":
    unittest.main()
