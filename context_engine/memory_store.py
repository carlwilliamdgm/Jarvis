# core/memory_store.py

from abc import ABC, abstractmethod
from contextlib import contextmanager
import json
from json import JSONDecodeError
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any, Dict, Generator, Optional

from core_intellect.paths import MEMORY_DB_PATH, MEMORY_PATH


class BaseMemoryStore(ABC):
    """Interface abstraite définissant les opérations de persistance de la mémoire."""

    @abstractmethod
    def load(self) -> dict:
        """Charge l'intégralité des données en mémoire."""
        raise NotImplementedError

    @abstractmethod
    def save(self, data: dict) -> None:
        """Sauvegarde l'intégralité des données."""
        raise NotImplementedError

    @abstractmethod
    @contextmanager
    def transaction(self) -> Generator[dict, None, None]:
        """Gestionnaire de transaction ACID (Commit sur succès, Rollback sur exception)."""
        raise NotImplementedError

    def close(self) -> None:
        """Libère les ressources si nécessaire."""
        pass


_GLOBAL_MEMORY_LOCK = threading.RLock()


class JsonMemoryStore(BaseMemoryStore):
    """Implémentation du stockage mémoire basée sur un fichier JSON avec locking process-level."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or MEMORY_PATH

    def load(self) -> dict:
        with _GLOBAL_MEMORY_LOCK:
            for tentative in range(5):
                try:
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        contenu = f.read().strip()
                        return json.loads(contenu) if contenu else {}
                except FileNotFoundError:
                    return {}
                except (JSONDecodeError, UnicodeDecodeError):
                    time.sleep(0.05 * (tentative + 1))
                    continue
                except OSError as e:
                    winerror = getattr(e, "winerror", None)
                    if winerror in (5, 32) or getattr(e, "errno", None) in (5, 13, 16, 32):
                        time.sleep(0.05 * (tentative + 1))
                        continue
                    return {}
            return {}

    def save(self, data: dict) -> None:
        with _GLOBAL_MEMORY_LOCK:
            tmp_path = self.file_path.with_name(
                f"{self.file_path.stem}_{os.getpid()}_{threading.get_ident()}_{time.time_ns()}.tmp"
            )
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                derniere_erreur = None
                for tentative in range(5):
                    try:
                        os.replace(tmp_path, self.file_path)
                        return
                    except OSError as e:
                        derniere_erreur = e
                        winerror = getattr(e, "winerror", None)
                        if winerror in (5, 32) or e.errno in (5, 13, 16, 32):
                            time.sleep(0.05 * (tentative + 1))
                            continue
                        raise

                shutil.copy2(tmp_path, self.file_path)
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    @contextmanager
    def transaction(self) -> Generator[dict, None, None]:
        from context_engine.memory import normaliser_memoire
        with _GLOBAL_MEMORY_LOCK:
            data = normaliser_memoire(self.load())
            yield data
            self.save(data)


class SqliteMemoryStore(BaseMemoryStore):
    """
    Implémentation haute concurrence basée sur SQLite avec Write-Ahead Logging (WAL).
    Permet des lectures concurrentes non bloquantes et une isolation transactionnelle multi-processus.
    """

    def __init__(self, db_path: Optional[Path] = None, json_fallback_path: Optional[Path] = None):
        self.db_path = db_path or MEMORY_DB_PATH
        self.json_fallback_path = json_fallback_path or MEMORY_PATH
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=15.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            with self._connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memory_kv;")
                count = cursor.fetchone()[0]

                # Migration automatique depuis memory.json si la DB est vierge
                if count == 0 and self.json_fallback_path.exists():
                    self._migrate_from_json(conn)

    def _migrate_from_json(self, conn: sqlite3.Connection) -> None:
        try:
            with open(self.json_fallback_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return
                data = json.loads(content)
                if isinstance(data, dict):
                    for key, val in data.items():
                        conn.execute(
                            "INSERT OR REPLACE INTO memory_kv (key, value) VALUES (?, ?);",
                            (key, json.dumps(val, ensure_ascii=False)),
                        )
                    conn.commit()
        except Exception:
            pass

    def load(self) -> dict:
        with self._lock:
            try:
                with self._connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT key, value FROM memory_kv;")
                    rows = cursor.fetchall()
                    result = {}
                    for key, raw_val in rows:
                        try:
                            result[key] = json.loads(raw_val)
                        except Exception:
                            result[key] = raw_val
                    return result
            except Exception:
                return {}

    def save(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        with self._lock:
            with self._connection() as conn:
                cursor = conn.cursor()
                existing_keys = {row[0] for row in cursor.execute("SELECT key FROM memory_kv;").fetchall()}
                current_keys = set(data.keys())

                # Insertion et mise à jour
                for key, val in data.items():
                    val_str = json.dumps(val, ensure_ascii=False)
                    cursor.execute(
                        "INSERT INTO memory_kv (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP;",
                        (key, val_str),
                    )

                # Suppression des clés qui n'existent plus
                keys_to_delete = existing_keys - current_keys
                for key in keys_to_delete:
                    cursor.execute("DELETE FROM memory_kv WHERE key = ?;", (key,))
                conn.commit()

    @contextmanager
    def transaction(self) -> Generator[dict, None, None]:
        from context_engine.memory import normaliser_memoire
        with self._lock:
            data = normaliser_memoire(self.load())
            yield data
            self.save(data)


_STORES: Dict[str, BaseMemoryStore] = {}


def get_memory_store(backend: Optional[str] = None) -> BaseMemoryStore:
    """
    Factory & Singleton retournant l'instance du store configuré.
    Par défaut, sélectionne JSON pour compatibilité totale (ou SQLite WAL si JARVIS_MEMORY_BACKEND=sqlite).
    """
    selected = backend or os.environ.get("JARVIS_MEMORY_BACKEND", "json").lower()
    if selected not in _STORES:
        if selected == "sqlite":
            _STORES[selected] = SqliteMemoryStore()
        else:
            _STORES[selected] = JsonMemoryStore()
    return _STORES[selected]


def reset_memory_stores() -> None:
    """Réinitialise les singletons (utile pour les tests)."""
    global _STORES
    _STORES.clear()
