"""Pytest configuration for Jarvis tests."""
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from datashield.crypto import crypto_engine


@pytest.fixture(autouse=True, scope="session")
def _ensure_crypto_engine_for_tests():
    """Garantit que crypto_engine est déverrouillé pendant l'exécution des tests."""
    if not crypto_engine.is_enabled:
        if crypto_engine.is_locked and hasattr(crypto_engine, "unlock_from_key_store"):
            try:
                crypto_engine.unlock_from_key_store()
            except Exception:
                pass
        if not crypto_engine.is_enabled:
            crypto_engine._set_passphrase(b"isolated-greatos-test-key-32bytes!")
    yield
