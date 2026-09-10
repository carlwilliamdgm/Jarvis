# jarvis/__init__.py
"""Module Jarvis - Interface conversationnelle et agent exécutif (GreatOS Module 1)."""
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
