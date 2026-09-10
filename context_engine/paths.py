#core/paths.py

import platform
from pathlib import Path

OS = platform.system()
HOME = Path.home()
JARVIS_DIR = Path(__file__).resolve().parent.parent
MEMORY_PATH = JARVIS_DIR / "memory.json"
MEMORY_DB_PATH = JARVIS_DIR / "memory.db"