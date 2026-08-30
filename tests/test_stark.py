import unittest
try:
    import pytest
except ImportError:
    # pytest n'est pas disponible : on fournit des stubs no-op
    # pour que le fichier soit importable via unittest discover.
    class _MarkStub:
        def __getattr__(self, name):
            return lambda *a, **kw: (lambda f: f)
    class _PytestStub:
        mark = _MarkStub()
        @staticmethod
        def skip(reason=""):
            raise unittest.SkipTest(reason)
    pytest = _PytestStub()  # type: ignore[assignment]

import jarvis
from core.error_classification import classifier_erreur_systeme, extraire_code_erreur, resultat_erreur
from core.memory import (
    charger_memoire,
    journaliser_erreur_systeme,
    normaliser_memoire,
    signalement_erreurs_autre_recurrentes,
)
from core.paths import MEMORY_PATH
from core.stark_parser import parser_objectif_stark
from core.stark_session import STARK_ACTIF_PATH


class FakeWinError(Exception):
    def __init__(self, winerror):
        super().__init__(f"[WinError {winerror}]")
        self.winerror = winerror


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


class AutodestructionCommandTests(unittest.TestCase):
    def setUp(self):
        jarvis.etat_autodestruction.statut = "attente_declenchement"
        jarvis.etat_autodestruction.deadline = None

    def tearDown(self):
        jarvis.etat_autodestruction.statut = "attente_declenchement"
        jarvis.etat_autodestruction.deadline = None

    def test_trigger_opens_confirmation_window_without_llm(self):
        historique = []

        reponse, intention_action = jarvis.parler("Jarvis, auto-destruction", historique, {})

        self.assertFalse(intention_action)
        self.assertEqual("attente_confirmation", jarvis.etat_autodestruction.statut)
        self.assertIn("Jarvis, confirme auto-destruction", reponse)

    def test_exact_confirmation_launches_teardown(self):
        launches = []
        old_schedule = jarvis.schedule_autodestruction
        jarvis.schedule_autodestruction = lambda delay_sec=2: launches.append(delay_sec)
        try:
            jarvis.parler("Jarvis, auto-destruction", [], {})
            reponse, intention_action = jarvis.parler("Jarvis, confirme auto-destruction", [], {})
        finally:
            jarvis.schedule_autodestruction = old_schedule

        self.assertTrue(intention_action)
        self.assertEqual([2], launches)
        self.assertEqual("attente_declenchement", jarvis.etat_autodestruction.statut)
        self.assertIn("Teardown local lancé", reponse)

    def test_unrelated_input_cancels_pending_request(self):
        old_interpreter = jarvis.interpreter_objectif
        calls = []
        jarvis.interpreter_objectif = lambda *args, **kwargs: calls.append(args) or {
            "type": "conversation",
            "actions": [],
            "reponse": "ne devrait pas passer au LLM",
        }
        try:
            jarvis.parler("Jarvis, auto-destruction", [], {})
            reponse, intention_action = jarvis.parler("oui", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter

        self.assertFalse(intention_action)
        self.assertEqual([], calls)
        self.assertEqual("attente_declenchement", jarvis.etat_autodestruction.statut)
        self.assertIn("annulée", reponse)

    def test_timeout_expires_before_next_message(self):
        jarvis.parler("Jarvis, auto-destruction", [], {})
        jarvis.etat_autodestruction.deadline = 0

        handled, reponse, intention_action = jarvis._gerer_autodestruction("bonjour")

        self.assertFalse(handled)
        self.assertIsNone(reponse)
        self.assertFalse(intention_action)
        self.assertEqual("attente_declenchement", jarvis.etat_autodestruction.statut)


@pytest.mark.slow
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
        executions = []

        def fake_interpreter(message, historique, memoire, **kwargs):
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

        # Le blocage anti-répétition doit empêcher l'exécution répétée de l'outil
        self.assertEqual(["x"], executions)
        self.assertEqual(1, len(executions))
        self.assertIn("Budget de 5 décisions épuisé", rapport)

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

    def test_three_consecutive_distinct_errors_stop_before_budget_exhaustion(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("stark_error_tool")
        appels = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            index = len(appels)
            return {
                "actions": [{"outil": "stark_error_tool", "args": {"chemin": f"cible_{index}.sys"}}],
                "reponse": "tentative",
            }

        def fake_tool(chemin):
            return resultat_erreur(f"Erreur : fichier verrouille {chemin}", 32)

        backup = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else None
        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["stark_error_tool"] = fake_tool
        try:
            rapport = jarvis.executer_mode_stark("analyse le disque", [], {})
            data = normaliser_memoire(charger_memoire())
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("stark_error_tool", None)
            else:
                jarvis.OUTILS["stark_error_tool"] = old_tool
            if backup is None:
                MEMORY_PATH.unlink(missing_ok=True)
            else:
                MEMORY_PATH.write_text(backup, encoding="utf-8")

        self.assertEqual(3, len(appels))
        self.assertIn("echecs_consecutifs", rapport)
        self.assertNotIn("Budget de 5 décisions épuisé", rapport)
        erreurs = data["erreurs_systeme"]["ressource_systeme_insuffisante"]
        self.assertGreaterEqual(len(erreurs), 3)
        self.assertEqual({"mode_stark"}, {entree["contexte"] for entree in erreurs[-3:]})

    def test_real_bug_shape_stops_on_consecutive_system_file_failures(self):
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("supprimer")
        chemins = ["C:\\pagefile.sys", "C:\\hiberfil.sys", "C:\\swapfile.sys"]

        def fake_interpreter(message, historique, memoire, **kwargs):
            chemin = chemins[len(chemins) - len(restants)]
            restants.pop(0)
            return {
                "actions": [{"outil": "supprimer", "args": {"chemin": chemin}}],
                "reponse": "suppression",
            }

        def fake_supprimer(chemin):
            code = 32 if "pagefile" in chemin else 2
            return resultat_erreur(f"Erreur : [WinError {code}] {chemin}", code)

        restants = chemins.copy()
        backup = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else None
        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["supprimer"] = fake_supprimer
        try:
            rapport = jarvis.executer_mode_stark("analyse le disque pour trouver les fichiers lourds qui peuvent être effacés", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("supprimer", None)
            else:
                jarvis.OUTILS["supprimer"] = old_tool
            if backup is None:
                MEMORY_PATH.unlink(missing_ok=True)
            else:
                MEMORY_PATH.write_text(backup, encoding="utf-8")

        self.assertIn("echecs_consecutifs", rapport)
        self.assertIn("3 échecs consécutifs", rapport)


class ErrorClassificationTests(unittest.TestCase):
    def test_classifier_covers_categories_and_unknown_code(self):
        self.assertEqual("ressource_systeme_insuffisante", classifier_erreur_systeme(FakeWinError(32)))
        self.assertEqual("acces_refuse", classifier_erreur_systeme(FakeWinError(5)))
        self.assertEqual("cible_introuvable", classifier_erreur_systeme(FakeWinError(2)))
        self.assertEqual("ressource_systeme_insuffisante", classifier_erreur_systeme(FakeWinError(112)))
        self.assertEqual("erreur_technique_outil", classifier_erreur_systeme(resultat_erreur("tech", categorie="erreur_technique_outil")))
        inconnu = FakeWinError(9999)
        self.assertEqual("autre", classifier_erreur_systeme(inconnu))
        self.assertEqual(9999, extraire_code_erreur(inconnu))

    def test_journalisation_from_stark_and_conversation_contexts(self):
        backup = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else None
        old_interpreter = jarvis.interpreter_objectif
        old_tool = jarvis.OUTILS.get("conversation_error_tool")

        def fake_interpreter(message, historique, memoire, **kwargs):
            return {
                "type": "action",
                "actions": [{"outil": "conversation_error_tool", "args": {"chemin": "absent.txt"}}],
                "reponse": "Je tente.",
            }

        jarvis.interpreter_objectif = fake_interpreter
        jarvis.OUTILS["conversation_error_tool"] = lambda chemin: resultat_erreur("Erreur : absent", 2)
        try:
            journaliser_erreur_systeme(
                resultat_erreur("Erreur : verrouille", 32),
                contexte="mode_stark",
                objectif="analyse",
                outil="supprimer",
                args={"chemin": "C:\\pagefile.sys"},
                resultat_brut="Erreur : verrouille",
            )
            jarvis.parler("ouvre absent", [], normaliser_memoire({}))
            data = normaliser_memoire(charger_memoire())
        finally:
            jarvis.interpreter_objectif = old_interpreter
            if old_tool is None:
                jarvis.OUTILS.pop("conversation_error_tool", None)
            else:
                jarvis.OUTILS["conversation_error_tool"] = old_tool
            if backup is None:
                MEMORY_PATH.unlink(missing_ok=True)
            else:
                MEMORY_PATH.write_text(backup, encoding="utf-8")

        self.assertEqual("mode_stark", data["erreurs_systeme"]["ressource_systeme_insuffisante"][-1]["contexte"])
        self.assertEqual("conversation", data["erreurs_systeme"]["cible_introuvable"][-1]["contexte"])

    def test_repeated_unknown_error_code_triggers_signalement(self):
        backup = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else None
        try:
            MEMORY_PATH.write_text("{}", encoding="utf-8")
            for index in range(3):
                journaliser_erreur_systeme(
                    resultat_erreur(f"Erreur inconnue {index}", 9999),
                    contexte="conversation",
                    objectif="test",
                    outil="outil",
                    args={"index": index},
                    resultat_brut=f"Erreur inconnue {index}",
                )

            signalement = signalement_erreurs_autre_recurrentes()
        finally:
            if backup is None:
                MEMORY_PATH.unlink(missing_ok=True)
            else:
                MEMORY_PATH.write_text(backup, encoding="utf-8")

        self.assertIn("9999", signalement)
        self.assertIn("3 fois", signalement)

    def test_stark_reasoning_captured_and_emitted(self):
        from core.intellect import _construire_prompt_interpretation, _parser_reponse_intellect
        
        # 1. Vérifier que le prompt Stark intègre les règles tri-phase et le champ raisonnement
        prompt = _construire_prompt_interpretation({}, mode_stark=True, message_actuel="test")
        self.assertIn("Règles impératives du Mode Stark (Plein Accès & Raisonnement Renforcé)", prompt)
        self.assertIn("DIAGNOSTIC", prompt)
        self.assertIn("ÉVALUATION D'IMPACT", prompt)
        self.assertIn('"raisonnement"', prompt)

        # 2. Vérifier le parsing du raisonnement dans la décision
        reponse_json = """{
            "objectif": "lister",
            "type": "action",
            "raisonnement": "Diagnostic: répertoire inconnu. Impact: lecture seule. Décision: lister.",
            "actions": [{"outil": "lister_dossier", "args": {"chemin": "."}}],
            "reponse": "J'inspecte le dossier, Sir."
        }"""
        decision = _parser_reponse_intellect(reponse_json, "lister")
        self.assertEqual("Diagnostic: répertoire inconnu. Impact: lecture seule. Décision: lister.", decision.get("raisonnement"))

    def test_stark_inter_segment_context_propagation(self):
        old_interpreter = jarvis.interpreter_objectif
        appels = []

        def fake_interpreter(message, historique, memoire, **kwargs):
            appels.append(message)
            if "etape 1" in message:
                return {
                    "actions": [{"outil": "terminer_tache", "args": {"resume": "Fichier config.json trouve et analyse"}}],
                    "reponse": "ok 1",
                    "raisonnement": "Étape 1 terminée avec succès."
                }
            else:
                return {
                    "actions": [{"outil": "terminer_tache", "args": {"resume": "Déploiement achevé"}}],
                    "reponse": "ok 2",
                    "raisonnement": "Étape 2 terminée avec succès en utilisant config.json."
                }

        jarvis.interpreter_objectif = fake_interpreter
        try:
            rapport = jarvis.executer_mode_stark("etape 1 >> etape 2", [], {})
        finally:
            jarvis.interpreter_objectif = old_interpreter

        self.assertEqual(2, len(appels))
        self.assertIn("Fichier config.json trouve et analyse", appels[1])
        self.assertIn("Contexte et acquis des étapes précédentes", appels[1])
        self.assertIn("1. réussi", rapport)
        self.assertIn("2. réussi", rapport)

    def test_stark_is_clean_from_memory_and_chat_history_pollution(self):
        from core.intellect import _construire_prompt_interpretation, interpreter_objectif
        
        memoire_avec_bribes = {
            "notes": [{"contenu": "Note personnelle : acheter des oeufs"}],
            "journal_conversation": [{"date": "2026-08-29", "utilisateur": "Raconte une blague", "jarvis": "Pourquoi les plongeurs..."}],
        }
        
        # 1. Vérifier que le prompt système Stark n'a AUCUNE trace de notes ou d'anciens échanges
        prompt_stark = _construire_prompt_interpretation(memoire_avec_bribes, mode_stark=True, message_actuel="test")
        self.assertNotIn("Notes enregistrées récemment", prompt_stark)
        self.assertNotIn("acheter des oeufs", prompt_stark)
        self.assertNotIn("Raconte une blague", prompt_stark)
        self.assertNotIn("Pourquoi les plongeurs", prompt_stark)
        
        # 2. Vérifier que le mode normal conserve bien la mémoire
        prompt_normal = _construire_prompt_interpretation(memoire_avec_bribes, mode_stark=False, message_actuel="test")
        self.assertIn("Notes enregistrées récemment", prompt_normal)
        self.assertIn("acheter des oeufs", prompt_normal)

        # 3. Vérifier que l'historique conversationnel n'est pas injecté dans les messages LLM en mode Stark
        historique_bavardage = [
            {"role": "user", "content": "Salut Jarvis !"},
            {"role": "assistant", "content": "Bonjour Sir, que puis-je faire ?"},
        ]
        appels_llm = []
        import core.intellect
        old_appeler_llm = core.intellect._appeler_llm_avec_retry
        try:
            core.intellect._appeler_llm_avec_retry = lambda msgs, mem, **kw: appels_llm.append(msgs) or {
                "message": {"content": '{"objectif": "test", "type": "action", "actions": [{"outil": "terminer_tache", "args": {}}], "reponse": "ok"}'}
            }
            interpreter_objectif("micro-objectif stark", historique_bavardage, memoire_avec_bribes, mode_stark=True)
            
            # En mode Stark, messages ne contient que [system_prompt, user_micro_objectif]
            self.assertEqual(1, len(appels_llm))
            messages_envoyes = appels_llm[0]
            self.assertEqual(2, len(messages_envoyes))
            self.assertEqual("system", messages_envoyes[0]["role"])
            self.assertEqual("user", messages_envoyes[1]["role"])
            self.assertEqual("micro-objectif stark", messages_envoyes[1]["content"])
        finally:
            core.intellect._appeler_llm_avec_retry = old_appeler_llm


if __name__ == "__main__":
    unittest.main()
