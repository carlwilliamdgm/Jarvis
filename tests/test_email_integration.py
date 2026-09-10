"""Tests for email integration."""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import taskflow.email_integration as email_integration


class TestEmailIntegration(unittest.TestCase):
    """Tests for email integration functions."""

    def test_analyser_patterns_email_with_valid_data(self):
        """Test analyser_patterns_email with valid data."""
        # Mock obtenir_emails_recents to return test emails
        mock_emails = [
            {
                "sujet": "Meeting important",
                "expediteur": "alice@example.com",
                "nom_expediteur": "Alice",
                "date_reception": "2024-01-15T10:30:00",
                "corps": "Discuter du projet",
                "importance": "high",
                "pieces_jointes": 0
            },
            {
                "sujet": "Rapport hebdomadaire",
                "expediteur": "bob@example.com",
                "nom_expediteur": "Bob",
                "date_reception": "2024-01-15T14:00:00",
                "corps": "Voici le rapport",
                "importance": "normal",
                "pieces_jointes": 1
            },
            {
                "sujet": "Meeting important follow-up",
                "expediteur": "alice@example.com",
                "nom_expediteur": "Alice",
                "date_reception": "2024-01-16T09:00:00",
                "corps": "Suite à notre discussion",
                "importance": "normal",
                "pieces_jointes": 0
            }
        ]

        with patch('taskflow.email_integration.obtenir_emails_recents', return_value=mock_emails):
            result = email_integration.analyser_patterns_email(heures=24)

            # Verify result structure
            self.assertIn("periode_analysee", result)
            self.assertIn("total_emails", result)
            self.assertIn("top_expediteurs", result)
            self.assertIn("top_horaires", result)
            self.assertIn("top_sujets", result)

            # Verify values
            self.assertEqual(result["total_emails"], 3)
            self.assertEqual(result["periode_analysee"], "24 heures")

            # Verify alice@example.com is top sender (2 emails)
            top_expediteurs = result["top_expediteurs"]
            self.assertEqual(len(top_expediteurs), 2)
            self.assertEqual(top_expediteurs[0]["email"], "alice@example.com")
            self.assertEqual(top_expediteurs[0]["count"], 2)

    def test_analyser_patterns_email_with_empty_data(self):
        """Test analyser_patterns_email with empty data."""
        with patch('taskflow.email_integration.obtenir_emails_recents', return_value=[]):
            result = email_integration.analyser_patterns_email(heures=24)

            # Verify result contains error message
            self.assertIn("message", result)
            self.assertIn("Pas assez de données", result["message"])

    def test_analyser_patterns_email_with_error(self):
        """Test analyser_patterns_email with access error."""
        mock_error = [{"erreur": "Impossible d'accéder aux emails"}]

        with patch('taskflow.email_integration.obtenir_emails_recents', return_value=mock_error):
            result = email_integration.analyser_patterns_email(heures=24)

            # Verify result contains error message
            self.assertIn("message", result)
            self.assertIn("Pas assez de données", result["message"])

    def test_analyser_patterns_email_regression_check_expediteurs_typo(self):
        """Regression test to verify exppediteurs typo is fixed."""
        mock_emails = [
            {
                "sujet": "Test email",
                "expediteur": "test@example.com",
                "nom_expediteur": "Test",
                "date_reception": "2024-01-15T10:30:00",
                "corps": "Test content",
                "importance": "normal",
                "pieces_jointes": 0
            }
        ]

        with patch('taskflow.email_integration.obtenir_emails_recents', return_value=mock_emails):
            # This function should not raise NameError for 'exppediteurs'
            result = email_integration.analyser_patterns_email(heures=24)

            # Verify function executes correctly
            self.assertIn("total_emails", result)
            self.assertEqual(result["total_emails"], 1)

    def test_normaliser_email(self):
        """Test email normalization function."""
        email = {
            "Subject": "Test Subject",
            "Sender": "sender@example.com",
            "SenderName": "Sender Name",
            "ReceivedTime": "2024-01-15T10:30:00",
            "Body": "Email body content",
            "Importance": "high",
            "Attachments": 2
        }

        normalized = email_integration._normaliser_email(email)

        self.assertEqual(normalized["sujet"], "Test Subject")
        self.assertEqual(normalized["expediteur"], "sender@example.com")
        self.assertEqual(normalized["nom_expediteur"], "Sender Name")
        self.assertEqual(normalized["date_reception"], "2024-01-15T10:30:00")
        self.assertEqual(normalized["corps"], "Email body content")
        self.assertEqual(normalized["importance"], "high")
        self.assertEqual(normalized["pieces_jointes"], 2)

    def test_normaliser_email_with_missing_fields(self):
        """Test normalization with missing fields."""
        email = {"Subject": "Minimal Email"}

        normalized = email_integration._normaliser_email(email)

        self.assertEqual(normalized["sujet"], "Minimal Email")
        self.assertEqual(normalized["expediteur"], "")
        self.assertEqual(normalized["nom_expediteur"], "")
        self.assertEqual(normalized["date_reception"], "")
        self.assertEqual(normalized["corps"], "")
        self.assertEqual(normalized["importance"], "normal")
        self.assertEqual(normalized["pieces_jointes"], 0)


if __name__ == "__main__":
    unittest.main()
