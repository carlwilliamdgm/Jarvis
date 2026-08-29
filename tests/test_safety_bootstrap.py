import unittest
from unittest.mock import patch, MagicMock
import sys
import importlib

try:
    import pytest
except ImportError:
    class _MarkStub:
        def __getattr__(self, name):
            def _decorator(*args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:
                    return args[0]
                return lambda f: f
            return _decorator
    class _PytestStub:
        mark = _MarkStub()
    pytest = _PytestStub()  # type: ignore[assignment]

# Importer le module a tester
import core.safety


@pytest.mark.smoke
class TestBootstrapImport(unittest.TestCase):
    """Tests pour garantir que _bootstrap_import n'effectue jamais d'installation pip."""

    def setUp(self):
        """Reinitialiser l'etat global avant chaque test."""
        core.safety.USE_FALLBACK = False

    def tearDown(self):
        """Nettoyer l'etat global apres chaque test."""
        core.safety.USE_FALLBACK = False

    @patch('core.safety.subprocess.run')
    @patch('core.safety.importlib.import_module')
    def test_bootstrap_import_never_calls_pip_on_success(self, mock_import, mock_subprocess):
        """Test que subprocess.run n'est jamais appele si l'import reussit."""
        # Reset the flag before the test
        core.safety.USE_FALLBACK = False
        mock_import.return_value = MagicMock()
        
        core.safety._bootstrap_import("module_existant")
        
        # subprocess.run ne doit jamais etre appele
        mock_subprocess.assert_not_called()
        # Le mode fallback ne doit pas etre active (pas d'erreur d'import)
        self.assertFalse(core.safety.USE_FALLBACK)

    @patch('core.safety.subprocess.run')
    @patch('core.safety.importlib.import_module')
    def test_bootstrap_import_never_calls_pip_on_import_error(self, mock_import, mock_subprocess):
        """Test que subprocess.run n'est jamais appele meme si l'import echoue."""
        mock_import.side_effect = ImportError("Module not found")
        
        result = core.safety._bootstrap_import("module_inexistant")
        
        # subprocess.run ne doit jamais etre appele
        mock_subprocess.assert_not_called()
        # Le mode fallback doit etre active
        self.assertTrue(core.safety.USE_FALLBACK)
        # Le resultat doit etre None
        self.assertIsNone(result)

    @patch('core.safety.subprocess.run')
    @patch('core.safety.importlib.import_module')
    def test_bootstrap_import_with_package_name(self, mock_import, mock_subprocess):
        """Test que le parametre package_name est respecte sans appel pip."""
        mock_import.side_effect = ImportError("Module not found")
        
        result = core.safety._bootstrap_import("module_inexistant", "package_name")
        
        # subprocess.run ne doit jamais etre appele
        mock_subprocess.assert_not_called()
        # Le mode fallback doit etre active
        self.assertTrue(core.safety.USE_FALLBACK)
        # Le resultat doit etre None
        self.assertIsNone(result)

    @patch('core.safety.subprocess.run')
    @patch('core.safety.importlib.import_module')
    def test_bootstrap_import_no_side_effects_on_failure(self, mock_import, mock_subprocess):
        """Test qu'il n'y a aucun effet de bord (reseau, ecriture) lors d'un echec."""
        mock_import.side_effect = ImportError("Module not found")
        
        # Simuler que subprocess.run echouerait s'il etait appele
        mock_subprocess.side_effect = Exception("Should not be called")
        
        result = core.safety._bootstrap_import("module_inexistant")
        
        # subprocess.run ne doit jamais etre appele
        mock_subprocess.assert_not_called()
        # Aucune exception ne doit etre levee
        self.assertIsNone(result)
        # Le mode fallback doit etre active
        self.assertTrue(core.safety.USE_FALLBACK)

    @patch('core.safety.subprocess.run')
    @patch('core.safety.importlib.import_module')
    def test_bootstrap_import_preserves_fallback_flag(self, mock_import, mock_subprocess):
        """Test que le flag USE_FALLBACK reste actif une fois active."""
        # Reset the flag before the test
        core.safety.USE_FALLBACK = False
        
        # Premier appel qui echoue
        mock_import.side_effect = ImportError("Module not found")
        result1 = core.safety._bootstrap_import("module_inexistant")
        
        self.assertTrue(core.safety.USE_FALLBACK)
        self.assertIsNone(result1)
        
        # Deuxieme appel qui reussit (pour tester que le flag reste)
        mock_import.side_effect = None
        mock_import.return_value = MagicMock()
        result2 = core.safety._bootstrap_import("module_existant")
        
        # Le flag fallback reste active (comportement attendu de l'implementation)
        self.assertTrue(core.safety.USE_FALLBACK)
        # subprocess.run n'a toujours pas ete appele
        mock_subprocess.assert_not_called()
        # Le resultat est le module importe
        self.assertIsNotNone(result2)


if __name__ == '__main__':
    unittest.main()
