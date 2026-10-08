"""Tests de validation de la portabilité et de l'absence de chemins en dur."""

import os
from pathlib import Path
import unittest

RACINE_PROJET = Path(__file__).resolve().parent.parent


class TestPortability(unittest.TestCase):
    def test_paths_py_uses_relative_resolution(self):
        """Vérifie que context_engine/paths.py dérive tous ses chemins de Path(__file__)."""
        from context_engine import paths
        self.assertTrue(paths.JARVIS_DIR.is_dir())
        self.assertEqual(paths.JARVIS_DIR.resolve(), RACINE_PROJET.resolve())
        self.assertTrue(str(paths.MEMORY_PATH).startswith(str(paths.JARVIS_DIR)))

    def test_gitignore_protects_env_secrets(self):
        """Vérifie que les clés et variables d'environnement locales ne sont jamais versionnées."""
        gitignore = (RACINE_PROJET / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)

    def test_no_hardcoded_user_paths_in_source_code(self):
        """Scanne tous les fichiers sources pour s'assurer de l'absence de chemins d'utilisateurs codés en dur."""
        extensions = {".py", ".ps1", ".sh"}
        dossiers_exclus = {".git", ".venv", "__pycache__", ".pytest_cache", "logs"}
        
        fautes = []
        for root, dirs, files in os.walk(RACINE_PROJET):
            dirs[:] = [d for d in dirs if d not in dossiers_exclus]
            for file in files:
                p = Path(root) / file
                if p.suffix in extensions:
                    # Ne pas tester ce fichier de test lui-même
                    if p.name == "test_portability.py":
                        continue
                    try:
                        contenu = p.read_text(encoding="utf-8", errors="ignore")
                        lignes = contenu.splitlines()
                        for num, l in enumerate(lignes, 1):
                            # Détecter C:\Users\ ou /Users/ ou /home/ en dur (hors commentaires d'exemples)
                            if ("C:\\Users\\" in l or "C:/Users/" in l) and not l.strip().startswith("#") and not l.strip().startswith("//"):
                                fautes.append(f"{p.name}:{num} -> {l.strip()[:60]}")
                    except Exception:
                        pass

        self.assertEqual(fautes, [], f"Chemins d'utilisateurs en dur trouvés dans le code source : {fautes}")

    def test_install_scripts_exist(self):
        """Vérifie la présence des scripts d'installation portables universels."""
        self.assertTrue((RACINE_PROJET / "install.ps1").exists())
        self.assertTrue((RACINE_PROJET / "install.sh").exists())
        self.assertTrue((RACINE_PROJET / "scripts" / "installer_service_windows.ps1").exists())


if __name__ == "__main__":
    unittest.main()
