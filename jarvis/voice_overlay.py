# jarvis/voice_overlay.py
"""Shim de rétrocompatibilité — module déplacé vers interface_morphique.voice_overlay.

Utiliser directement : from interface_morphique.voice_overlay import ...
"""
from interface_morphique.voice_overlay import (  # noqa: F401
    VoiceOverlay,
    lancer_process_overlay,
    demarrer_overlay_vocal,
    arreter_overlay_vocal,
    main_standalone,
)
