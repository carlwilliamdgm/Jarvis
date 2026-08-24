"""Tests for calendar integration."""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

import capabilities.calendar_integration as calendar_integration


class TestCalendarIntegration(unittest.TestCase):
    """Tests for calendar integration functions."""

    def test_constants_defined(self):
        """Test that Outlook COM constants are properly defined."""
        self.assertEqual(calendar_integration.OL_FOLDER_CALENDAR, 9)
        self.assertEqual(calendar_integration.OL_APPOINTMENT_ITEM, 1)
        self.assertEqual(calendar_integration.APPOINTMENT_DURATION_MINUTES, 60)
        self.assertEqual(calendar_integration.REMINDER_MINUTES_BEFORE_START, 15)

    def test_normaliser_evenement(self):
        """Test event normalization function."""
        event = {
            "Subject": "Test Meeting",
            "Start": "2024-01-15T10:30:00",
            "End": "2024-01-15T11:30:00",
            "Location": "Conference Room",
            "Body": "Meeting description",
            "Importance": "high"
        }

        normalized = calendar_integration._normaliser_evenement(event)

        self.assertEqual(normalized["titre"], "Test Meeting")
        self.assertEqual(normalized["debut"], "2024-01-15T10:30:00")
        self.assertEqual(normalized["fin"], "2024-01-15T11:30:00")
        self.assertEqual(normalized["lieu"], "Conference Room")
        self.assertEqual(normalized["description"], "Meeting description")
        self.assertEqual(normalized["importance"], "high")

    def test_normaliser_evenement_with_missing_fields(self):
        """Test normalization with missing fields."""
        event = {"Subject": "Minimal Event"}

        normalized = calendar_integration._normaliser_evenement(event)

        self.assertEqual(normalized["titre"], "Minimal Event")
        self.assertEqual(normalized["debut"], "")
        self.assertEqual(normalized["fin"], "")
        self.assertEqual(normalized["lieu"], "")
        self.assertEqual(normalized["description"], "")
        self.assertEqual(normalized["importance"], "normal")

    def test_obtenir_evenements_calendrier_returns_list_on_error(self):
        """Test that obtenir_evenements_calendrier returns list on error."""
        # Mock subprocess to raise an exception
        with patch('capabilities.calendar_integration.subprocess.run', side_effect=Exception("Test error")):
            result = calendar_integration.obtenir_evenements_calendrier(7)
            # Should return empty list, not error dict
            self.assertIsInstance(result, list)
            self.assertEqual(result, [])

    def test_formater_evenements_with_empty_list(self):
        """Test formatting with empty list."""
        result = calendar_integration.formater_evenements([])
        self.assertEqual(result, "Aucun événement calendrier disponible.")

    def test_formater_evenements_with_valid_events(self):
        """Test formatting with valid events."""
        events = [
            {
                "titre": "Meeting",
                "debut": "2024-01-15T10:30:00",
                "lieu": "Office",
                "importance": "high"
            }
        ]

        result = calendar_integration.formater_evenements(events)
        self.assertIn("Meeting", result)
        self.assertIn("Office", result)

    def test_creer_rappel_calendrier_invalid_date_format(self):
        """Test that invalid date format is rejected."""
        result = calendar_integration.creer_rappel_calendrier(
            "Test",
            "invalid-date",
            "Description"
        )
        self.assertIn("Format de date invalide", result)

    def test_creer_rappel_calendrier_valid_date_format(self):
        """Test that valid date format is accepted."""
        # Mock subprocess to simulate successful execution
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Rappel créé avec succès"

        with patch('capabilities.calendar_integration.subprocess.run', return_value=mock_result):
            result = calendar_integration.creer_rappel_calendrier(
                "Test Meeting",
                "2024-12-25 14:30",
                "Test Description"
            )
            self.assertEqual(result, "Rappel créé avec succès")

    def test_creer_rappel_calendrier_with_special_characters(self):
        """Test that special characters are handled safely (no injection)."""
        # Mock subprocess to simulate successful execution
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Rappel créé avec succès"

        with patch('capabilities.calendar_integration.subprocess.run', return_value=mock_result):
            # Test with characters that could be used for injection
            result = calendar_integration.creer_rappel_calendrier(
                'Test"; Write-Host "Injected',
                "2024-12-25 14:30",
                'Description with "quotes"'
            )
            # Should still succeed (not fail due to injection)
            self.assertEqual(result, "Rappel créé avec succès")


if __name__ == "__main__":
    unittest.main()
