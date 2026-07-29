import json
import unittest
from unittest.mock import patch

from core import intellect


def llm_response(decision: dict) -> dict:
    return {"message": {"content": json.dumps(decision)}}


class IntellectActionContractTests(unittest.TestCase):
    def test_action_without_tool_is_repaired_before_returning(self):
        responses = iter(
            [
                llm_response(
                    {
                        "objectif": "noter une idée",
                        "type": "action",
                        "actions": [],
                        "reponse": "Je vais enregistrer cette idée, Sir.",
                    }
                ),
                llm_response(
                    {
                        "objectif": "noter une idée",
                        "type": "action",
                        "actions": [{"outil": "noter", "args": {"note": "idée"}}],
                        "reponse": "Je l'enregistre, Sir.",
                    }
                ),
            ]
        )
        with patch.object(intellect, "_appeler_llm_avec_retry", side_effect=lambda *args, **kwargs: next(responses)) as call:
            resultat = intellect.interpreter_objectif("Note cette idée", [], {})

        self.assertEqual(2, call.call_count)
        self.assertEqual("noter", resultat["actions"][0]["outil"])

    def test_unrepairable_action_never_claims_that_it_was_done(self):
        response = llm_response(
            {
                "objectif": "noter une idée",
                "type": "action",
                "actions": [],
                "reponse": "Je vais enregistrer cette idée, Sir.",
            }
        )
        with patch.object(intellect, "_appeler_llm_avec_retry", return_value=response):
            resultat = intellect.interpreter_objectif("Note cette idée", [], {})

        self.assertEqual([], resultat["actions"])
        self.assertIn("n'ai exécuté aucune action", resultat["reponse"])


if __name__ == "__main__":
    unittest.main()
