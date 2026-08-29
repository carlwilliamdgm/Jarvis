import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.memory_store import (
    JsonMemoryStore,
    SqliteMemoryStore,
    get_memory_store,
    reset_memory_stores,
)


class SqliteMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.db"
        self.json_path = Path(self.temp_dir.name) / "test_memory.json"

    def tearDown(self):
        reset_memory_stores()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_wal_mode_enabled(self):
        store = SqliteMemoryStore(db_path=self.db_path, json_fallback_path=self.json_path)
        with store._connection() as conn:
            cursor = conn.cursor()
            mode = cursor.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_save_and_load(self):
        store = SqliteMemoryStore(db_path=self.db_path, json_fallback_path=self.json_path)
        data = {
            "utilisateur": {"nom": "Tony", "langue": "français"},
            "notes": ["premiere note", "deuxieme note"],
        }
        store.save(data)

        loaded = store.load()
        self.assertEqual(loaded["utilisateur"]["nom"], "Tony")
        self.assertEqual(len(loaded["notes"]), 2)

    def test_auto_migration_from_json(self):
        initial_json = {
            "utilisateur": {"nom": "Bruce"},
            "notes": ["migrated note"],
        }
        self.json_path.write_text(json.dumps(initial_json), encoding="utf-8")

        store = SqliteMemoryStore(db_path=self.db_path, json_fallback_path=self.json_path)
        loaded = store.load()
        self.assertEqual(loaded["utilisateur"]["nom"], "Bruce")
        self.assertIn("migrated note", loaded["notes"])

    def test_transaction_commit_and_rollback(self):
        store = SqliteMemoryStore(db_path=self.db_path, json_fallback_path=self.json_path)
        
        # Test Commit
        with store.transaction() as data:
            data["notes"].append("commit note")

        loaded = store.load()
        self.assertIn("commit note", loaded["notes"])

        # Test Rollback
        try:
            with store.transaction() as data:
                data["notes"].append("failed note")
                raise RuntimeError("Erreur simulatee")
        except RuntimeError:
            pass

        loaded_after_fail = store.load()
        self.assertNotIn("failed note", loaded_after_fail["notes"])

    def test_concurrent_multithread_writes(self):
        store = SqliteMemoryStore(db_path=self.db_path, json_fallback_path=self.json_path)
        
        def worker(w_id):
            for i in range(15):
                with store.transaction() as data:
                    data["notes"].append(f"worker_{w_id}_{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        loaded = store.load()
        self.assertEqual(len(loaded["notes"]), 60)

    def test_factory_switching(self):
        reset_memory_stores()
        with patch.dict(os.environ, {"JARVIS_MEMORY_BACKEND": "json"}):
            store = get_memory_store()
            self.assertIsInstance(store, JsonMemoryStore)

        reset_memory_stores()
        with patch.dict(os.environ, {"JARVIS_MEMORY_BACKEND": "sqlite"}):
            store = get_memory_store()
            self.assertIsInstance(store, SqliteMemoryStore)


if __name__ == "__main__":
    unittest.main()
