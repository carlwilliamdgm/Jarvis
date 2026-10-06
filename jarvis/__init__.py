# jarvis/__init__.py
"""Module Jarvis - Interface conversationnelle, voix et visage de GreatOS (CDC GreatOS Module 4.1).

Rôle : Le visage et la voix de GreatOS.
- Interface principale en langage naturel (français/anglais)
- Écoute vocale, restitution audio et personnalités conversationnelles
- Orchestrateur général des interactions utilisateur
- Transmet les intentions à Core Intellect pour la réflexion silencieuse
"""
import sys
import jarvis.agent as _agent

class _JarvisProxy(sys.modules[__name__].__class__):
    def __getattr__(self, name):
        return getattr(_agent, name)

    def __setattr__(self, name, value):
        setattr(_agent, name, value)
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _JarvisProxy

# Populate initial attributes
for _name in dir(_agent):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_agent, _name)

# Import optionnel du daemon proactif (déplacé depuis service/)
try:
    from jarvis.proactive_daemon import DaemonProactif  # noqa: F401
except ImportError:
    pass
