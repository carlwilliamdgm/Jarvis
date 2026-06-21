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
        STARK_ACTIF_PATH.write_text("[]", encoding="utf-8")
        jarvis.desactiver_mode_stark()

    def test_simple_stark_objective_finishes_as_one_micro_objective(self):
        old_interpreter = jarvis.interpreter_objectif
        appels = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            self.assertEqual(0.3, kwargs.get("temperature"))
            self.assertTrue(kwargs.get("mode_stark"))
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

        def fake_interpreter(message, historique, memoire, **kwargs):
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

    def test_repeated_identical_attempt_is_blocked_before_execution(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("stark_test_same")
        appels = []
        executions = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            return {
                "actions": [{"outil": "stark_test_same", "args": {"valeur": "x"}}],
                "reponse": "encore",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["stark_test_same"] = lambda valeur: executions.append(valeur) or "meme resultat"
        try:
            rapport = jarvis.executer_mode_stark("faire x", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("stark_test_same", None)
            else:
                jarvis.OUTILS["stark_test_same"] = old_tool

        self.assertEqual(3, len(appels))
        self.assertEqual(["x"], executions)
        self.assertIn("Action déjà exécutée", appels[2])
        self.assertIn("Budget de 3 décisions épuisé", rapport)

    def test_read_tool_does_not_complete_without_terminer_tache(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("lire_notes")
        appels = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            if len(appels) > 1:
                return {"actions": [], "reponse": "rien de plus"}
            return {
                "actions": [{"outil": "lire_notes", "args": {}}],
                "reponse": "lecture",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["lire_notes"] = lambda: "note complete lisible"
        try:
            resultat = jarvis._executer_micro_objectif_stark("lis les notes", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("lire_notes", None)
            else:
                jarvis.OUTILS["lire_notes"] = old_tool

        self.assertEqual(2, len(appels))
        self.assertEqual("échoué", resultat["statut"])
        self.assertIn("note complete lisible", resultat["tentatives"][0]["observation"])

    def test_type_error_is_reported_as_technical_error(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("stark_type_error")

        def fake_interpreter(message, historique, memoire, **kwargs):
            return {
                "actions": [{"outil": "stark_type_error", "args": {}}],
                "reponse": "appel",
            }

        def tool_requires_value(valeur):
            return valeur

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["stark_type_error"] = tool_requires_value
        try:
            rapport = jarvis.executer_mode_stark("provoque erreur", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("stark_type_error", None)
            else:
                jarvis.OUTILS["stark_type_error"] = old_tool

        self.assertIn("erreur_technique", rapport)
        self.assertIn("ERREUR TECHNIQUE", rapport)

    def test_stark_context_keeps_latest_observation_untruncated(self):
        etat = jarvis.EtatMicroObjectif(objectif="observer")
        long_result = "ligne complete\n" * 500
        etat.actions.append({
            "outil": "top_fichiers_lourds",
            "args": {"n": 20},
            "resultat_brut": long_result,
            "erreur": False,
        })

        message = jarvis._construire_message_micro_objectif(etat)

        self.assertIn(long_result, message)
        self.assertNotIn(long_result[:300] + "\n\nDécide", message)

    def test_stark_context_omits_old_whole_results_when_too_long(self):
        etat = jarvis.EtatMicroObjectif(objectif="observer")
        old_result = "ancien resultat\n" * 500
        latest_result = "dernier resultat\n" * 20
        etat.actions.append({
            "outil": "top_fichiers_lourds",
            "args": {"n": 20},
            "resultat_brut": old_result,
            "erreur": False,
        })
        etat.actions.append({
            "outil": "audit_stockage",
            "args": {},
            "resultat_brut": latest_result,
            "erreur": False,
        })

        message = jarvis._construire_message_micro_objectif(etat)

        self.assertIn("résultat omis pour longueur", message)
        self.assertIn(latest_result, message)

    def test_destructive_tool_does_not_complete_analysis_objective(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("vider_temp")
        appels = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            if len(appels) > 1:
                return {"actions": [], "reponse": "rien de plus"}
            return {
                "actions": [{"outil": "vider_temp", "args": {}}],
                "reponse": "nettoyage",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["vider_temp"] = lambda: "Fichiers temporaires anciens vides - 2.9 MB liberes"
        try:
            resultat = jarvis._executer_micro_objectif_stark(
                "analyse le disque pour trouver les fichiers lourds qui peuvent etre effaces",
                [],
                {},
            )
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("vider_temp", None)
            else:
                jarvis.OUTILS["vider_temp"] = old_tool

        self.assertEqual(2, len(appels))
        self.assertEqual("échoué", resultat["statut"])
        self.assertIn("Fichiers temporaires anciens vides", resultat["tentatives"][0]["observation"])

    def test_action_then_terminer_tache_closes_without_repetition_block(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("lister_dossier")
        appels = []
        executions = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            if len(appels) == 1:
                return {
                    "actions": [{"outil": "lister_dossier", "args": {"chemin": "."}}],
                    "reponse": "liste",
                }
            return {
                "actions": [{"outil": "terminer_tache", "args": {"resume": "Dossier liste."}}],
                "reponse": "termine",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["lister_dossier"] = lambda chemin: executions.append(chemin) or "jarvis.py\ntools.py"
        try:
            rapport = jarvis.executer_mode_stark("liste le dossier Jarvis", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("lister_dossier", None)
            else:
                jarvis.OUTILS["lister_dossier"] = old_tool

        self.assertEqual(["."], executions)
        self.assertEqual(2, len(appels))
        self.assertNotIn("Action déjà exécutée", appels[1])
        self.assertIn("appelle terminer_tache directement", appels[1])
        self.assertIn("1. réussi", rapport)
        self.assertIn("Dossier liste.", rapport)


if __name__ == "__main__":
    unittest.main()
