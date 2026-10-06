import yaml
import os
from types import SimpleNamespace

DEFAULT_CONFIG = {
    "theme": "dark",
    "log_retention": 500,
    "toast_duration": 3000,
    "language": "fr"
}

def load_config(config_path: str = os.path.join(os.path.dirname(__file__), "config.yaml")) -> SimpleNamespace:
    """Load configuration from ``config.yaml``.

    If the file does not exist, it is created with the default values.
    Returns a ``SimpleNamespace`` so attributes can be accessed as ``cfg.theme``.
    """
    if not os.path.exists(config_path):
        # Write default configuration
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(DEFAULT_CONFIG, f)
        cfg_dict = DEFAULT_CONFIG.copy()
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg_dict = yaml.safe_load(f) or {}
        # Fill missing defaults
        for key, value in DEFAULT_CONFIG.items():
            cfg_dict.setdefault(key, value)
    return SimpleNamespace(**cfg_dict)
