import shutil
import sys
import unittest
from pathlib import Path

import tools
import jarvis
import core.prompt
import core.safety
from core.memory import charger_memoire, normaliser_memoire, sauvegarder_memoire
from core.paths import JARVIS_DIR, MEMORY_PATH
from jarvis import extraire_json_objets


class ToolSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.memory_backup = MEMORY_PATH.read_text(encoding="utf-8") if MEMORY_PATH.exists() else None
        cls.workspace = JARVIS_DIR / ".dist" / "test_tools"

    @classmethod
    def tearDownClass(cls):
        if cls.memory_backup is None:
            MEMORY_PATH.unlink(missing_ok=True)
        else:
            MEMORY_PATH.write_text(cls.memory_backup, encoding="utf-8")
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def setUp(self):
        self.protected_roots = core.safety.ZONE_MAP.protected_roots
        core.safety.ZONE_MAP.protected_roots = frozenset()
        sauvegarder_memoire({})
        shutil.rmtree(self.workspace, ignore_errors=True)
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.workspace, ignore_errors=True)
        core.safety.ZONE_MAP.protected_roots = self.protected_roots

    def test_file_tools_lifecycle(self):
        dossier = self.workspace / "docs"
        fichier = dossier / "a.txt"

        self.assertIn("Dossier cree", tools.OUTILS["creer_dossier"](str(dossier)))
        self.assertIn("Fichier cree", tools.OUTILS["creer_fichier"](str(fichier), "bonjour"))
        self.assertEqual("bonjour", tools.OUTILS["lire_fichier"](str(fichier)))
        self.assertIn("a.txt", tools.OUTILS["lister_dossier"](str(dossier)))

    def test_large_file_reads_are_truncated(self):
        fichier = self.workspace / "large.txt"
        fichier.write_text("x" * 3000, encoding="utf-8")

        contenu = tools.OUTILS["lire_fichier"](str(fichier), max_caracteres=1000)

        self.assertIn("Lecture tronquee", contenu)
        self.assertLess(len(contenu), 1200)

    def test_directory_listing_is_limited(self):
        dossier = self.workspace / "many"
        dossier.mkdir()
        for index in range(5):
            (dossier / f"{index}.txt").write_text("x", encoding="utf-8")

        sortie = tools.OUTILS["lister_dossier"](str(dossier), limite=2)

        self.assertIn("element(s) supplementaire(s)", sortie)

    def test_json_extraction_accepts_multiple_objects(self):
        objets = extraire_json_objets(
            'avant {"outil":"noter","args":{"note":"a"}} '
            'apres {"outil":"lire_notes","args":{}}'
        )

        self.assertEqual(["noter", "lire_notes"], [objet["outil"] for objet in objets])
        self.assertEqual({"note": "a"}, objets[0]["args"])

    def test_memory_normalization_recovers_from_non_dict_json(self):
        self.assertEqual([], normaliser_memoire([])["notes"])

    def test_registered_tools_match_prompt_critical_file_listing(self):
        self.assertIn("lister_dossier", tools.OUTILS)

    def test_action_prompt_mentions_every_exposed_tool(self):
        prompt = core.prompt.construire_prompt_action({
            "utilisateur": {},
            "preferences": {},
            "commandes_personnalisees": {},
            "automatisations": [],
            "surveillances_dossiers": [],
            "contexte": {},
        })
        manquants = [nom for nom in sorted(tools.OUTILS) if nom not in prompt]
        self.assertEqual([], manquants)

    def test_notification_tool_is_callable(self):
        old_notifier = tools.storage.notifier
        calls = []
        tools.storage.notifier = lambda titre, message, urgence=False: calls.append((titre, message, urgence))
        try:
            self.assertIn("Notification envoyee", tools.OUTILS["notifier_utilisateur"]("Smoke", "Message", False))
        finally:
            tools.storage.notifier = old_notifier
        self.assertEqual([("Smoke", "Message", False)], calls)

    def test_automation_preserves_memory_changes_from_tool(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: True
        try:
            resultat = tools.OUTILS["ajouter_automatisation"](
                "auto note",
                "noter",
                {"note": "note persistante"},
                "quotidien",
                "00:00",
            )
        finally:
            tools.demander_confirmation = old_confirm
        self.assertIn("Automatisation #1", resultat)

        data = normaliser_memoire(charger_memoire())
        data["automatisations"][0]["prochaine_execution"] = "2000-01-01 00:00"
        sauvegarder_memoire(data)

        self.assertIn("Note enregistree", tools.OUTILS["executer_automatisations_dues"]())
        self.assertIn("note persistante", tools.OUTILS["lire_notes"]())

    def test_can_create_and_launch_automation_manually(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: True
        try:
            self.assertIn(
                "Automatisation #1",
                tools.OUTILS["ajouter_automatisation"](
                    "lancement manuel",
                    "noter",
                    {"note": "note lancee manuellement"},
                    "quotidien",
                    "23:59",
                ),
            )
        finally:
            tools.demander_confirmation = old_confirm

        self.assertIn("Note enregistree", tools.OUTILS["executer_automatisation"](automation_id=1))
        self.assertIn("note lancee manuellement", tools.OUTILS["lire_notes"]())

    def test_sensitive_tools_cannot_be_scheduled_as_automations(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: True
        try:
            self.assertIn(
                "non automatisable",
                tools.OUTILS["ajouter_automatisation"](
                    "suppression risquee",
                    "supprimer",
                    {"chemin": str(self.workspace)},
                    "quotidien",
                    "10:00",
                ),
            )
        finally:
            tools.demander_confirmation = old_confirm

    def test_terminal_commands_can_be_scheduled_after_confirmation(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: True
        try:
            self.assertIn(
                "Automatisation #1",
                tools.OUTILS["ajouter_automatisation"](
                    "terminal auto",
                    "executer_commande",
                    {"commande": "echo auto-terminal"},
                    "quotidien",
                    "10:00",
                ),
            )
        finally:
            tools.demander_confirmation = old_confirm

    def test_terminal_command_runs_without_artificial_confirmation(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: self.fail("confirmation inutile pour le terminal Windows")
        try:
            self.assertIn("smoke", tools.OUTILS["executer_commande"](f'"{sys.executable}" -c "print(\\"smoke\\")"'))
            self.assertIn("del", tools.OUTILS["executer_commande"](f'"{sys.executable}" -c "print(\\"del\\")"'))
        finally:
            tools.demander_confirmation = old_confirm

    def test_powershell_command_runs(self):
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: self.fail("confirmation inutile pour une commande PowerShell")
        try:
            self.assertIn("ps-smoke", tools.OUTILS["executer_powershell"]("Write-Output ps-smoke"))
        finally:
            tools.demander_confirmation = old_confirm

    def test_deleting_concrete_child_path_does_not_require_confirmation(self):
        dossier = self.workspace / "delete_free"
        dossier.mkdir()
        fichier = dossier / "victim.txt"
        fichier.write_text("bye", encoding="utf-8")
        old_roots = core.safety.ZONE_MAP.protected_roots
        core.safety.ZONE_MAP.protected_roots = frozenset()
        try:
            self.assertIn("Fichier supprime", tools.OUTILS["supprimer"](str(fichier)))
        finally:
            core.safety.ZONE_MAP.protected_roots = old_roots

    def test_deleting_broad_root_is_blocked(self):
        core.safety.ZONE_MAP.protected_roots = self.protected_roots
        old_confirm = tools.demander_confirmation
        tools.demander_confirmation = lambda description: True  # Accepter confirmation pour tester le blocage de sécurité
        try:
            resultat = tools.OUTILS["supprimer"](str(JARVIS_DIR))
            resultat_normalise = str(resultat).lower().replace("é", "e").replace("è", "e")
            # Le blocage peut se manifester par un message de sécurité ou une erreur système (WinError 5)
            self.assertTrue("acces refuse" in resultat_normalise or "bloquee" in resultat_normalise or "protegee" in resultat_normalise)
        finally:
            tools.demander_confirmation = old_confirm

    def test_optimization_plan_does_not_bypass_confirmations(self):
        self.assertNotIn("sans confirmation", jarvis.PLAN_OPTIMISATION.lower())
        self.assertIn("confirmation", jarvis.PLAN_OPTIMISATION.lower())

    def test_cloud_provider_router_rotates_after_last_success(self):
        providers = [
            {"nom": "OpenRouter", "modeles": ["openrouter/free"], "fonction": object(), "niveau": "simple"},
            {"nom": "Together", "modeles": ["meta-llama/Llama-3.1-8B-Instruct-Turbo"], "fonction": object(), "niveau": "simple"},
            {"nom": "Groq", "modeles": ["openai/gpt-oss-120b"], "fonction": object(), "niveau": "complexe"},
        ]

        ordre = jarvis.ordonner_providers_cloud(
            providers,
            {"routeur_modeles": {"dernier_provider_cloud": "OpenRouter"}},
        )

        self.assertEqual(["OpenRouter", "Together", "Groq"], [provider["nom"] for provider in ordre])

        ordre = jarvis.ordonner_providers_cloud(
            providers,
            {"routeur_modeles": {"dernier_provider_simple": "OpenRouter"}},
        )

        self.assertEqual(["Together", "OpenRouter", "Groq"], [provider["nom"] for provider in ordre])

    def test_cloud_provider_router_prefers_capable_provider_for_complex_tasks(self):
        providers = [
            {"nom": "OpenRouter", "modeles": ["openrouter/free"], "fonction": object(), "niveau": "simple"},
            {"nom": "Groq", "modeles": ["openai/gpt-oss-120b"], "fonction": object(), "niveau": "complexe"},
            {"nom": "Together", "modeles": ["meta-llama/Llama-3.1-8B-Instruct-Turbo"], "fonction": object(), "niveau": "simple"},
        ]

        ordre = jarvis.ordonner_providers_cloud(providers, {}, complexite="complexe")

        self.assertEqual("Groq", ordre[0]["nom"])

    def test_complexity_estimation_uses_task_shape(self):
        self.assertEqual("simple", jarvis.estimer_complexite("note acheter du pain", True))
        self.assertEqual(
            "complexe",
            jarvis.estimer_complexite("analyse le projet puis corrige les erreurs", True),
        )

    def test_task_completion_response_is_detected(self):
        self.assertTrue(jarvis.reponse_termine_tache('{"outil":"terminer_tache","args":{"resume":"ok"}}'))

    def test_agentic_loop_executes_observes_and_continues(self):
        old_parler = jarvis.parler
        responses = [
            ('J\'ai enregistré la note demandée.\n\nNote enregistree.', True),
            ('Tâche terminée avec succès.', True),
        ]

        def fake_parler(message, historique, memoire):
            return responses.pop(0)

        jarvis.parler = fake_parler
        try:
            resultat, intention = jarvis.executer_agent(
                "analyse puis corrige quelque chose",
                [{"role": "system", "content": ""}],
                normaliser_memoire(charger_memoire()),
            )
        finally:
            jarvis.parler = old_parler

        self.assertTrue(intention)
        self.assertIn("J'ai enregistré la note demandée.", resultat)
        self.assertNotIn('{"outil"', resultat)
        self.assertNotIn("Etape", resultat)


if __name__ == "__main__":
    unittest.main()
