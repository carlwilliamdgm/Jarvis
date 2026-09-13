"""Overlay visuel flottant pour l'état vocal de Jarvis.

Thread Tkinter dédié, indépendant de la boucle asyncio uvicorn.
Lit l'état via un fichier JSON partagé, écrit par voice_state.py.
Affiche un HUD discret en bas à droite de l'écran lors des états actifs.
"""

import json
import logging
import math
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from jarvis.voice_state import VoiceState

# Configuration du logger
logger = logging.getLogger(__name__)

# Fichier d'état partagé pour la communication inter-process
VOICE_STATE_FILE = Path(__file__).parent.parent / "voice_state.json"

# Suivi global du processus overlay
_overlay_process: Optional[subprocess.Popen] = None
_overlay_lock = threading.Lock()


class VoiceOverlay:
    """Overlay visuel flottant dynamique pour l'état vocal (process séparé)."""

    BG_COLOR = "#12131f"        # Fond HUD sombre
    ACCENT_CYAN = "#00d4ff"     # Cyan écoute / parole
    ACCENT_GOLD = "#ffd700"     # Or réveil
    ACCENT_ORANGE = "#ffa502"   # Orange réflexion
    ACCENT_ACTION = "#a29bfe"   # Violet action
    ACCENT_RED = "#ff4757"      # Rouge erreur
    TEXT_COLOR = "#ffffff"      # Blanc
    SUBTEXT_COLOR = "#b2bec3"   # Gris clair

    WIDTH = 220
    HEIGHT = 86
    POSITION = "bottom-right"

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._current_state = VoiceState.IDLE
        self._current_transcript = ""
        self._stop_event = threading.Event()
        self._anim_tick = 0
        self._is_visible = False

    def _get_position_coords(self) -> tuple[int, int]:
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()

        if self.POSITION == "bottom-right":
            x = screen_width - self.WIDTH - 24
            y = screen_height - self.HEIGHT - 28
        elif self.POSITION == "bottom-left":
            x = 24
            y = screen_height - self.HEIGHT - 28
        elif self.POSITION == "top-right":
            x = screen_width - self.WIDTH - 24
            y = 24
        else:
            x = 24
            y = 24
        return x, y

    def _read_state_from_file(self) -> tuple[VoiceState, str] | None:
        """Lit l'état depuis le fichier JSON partagé."""
        try:
            if not VOICE_STATE_FILE.exists():
                return VoiceState.IDLE, ""
            with open(VOICE_STATE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            state_str = data.get("state", "idle")
            text_str = str(data.get("text", "") or "")
            return VoiceState(state_str), text_str
        except (json.JSONDecodeError, IOError, ValueError, AttributeError, TypeError, OSError):
            return None

    def _create_overlay(self):
        """Crée la fenêtre HUD."""
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.94)
        self._root.geometry(f"{self.WIDTH}x{self.HEIGHT}")

        x, y = self._get_position_coords()
        self._root.geometry(f"+{x}+{y}")

        # Bloquer les clics et touches sur la fenêtre
        self._root.bind("<Button>", lambda e: "break")
        self._root.bind("<Key>", lambda e: "break")

        # Activer le click-through sous Windows
        if sys.platform == "win32":
            try:
                import ctypes
                self._root.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
                if not hwnd:
                    hwnd = self._root.winfo_id()
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                WS_EX_LAYERED = 0x00080000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
            except Exception as e:
                logger.debug(f"Click-through notice: {e}")

        self._canvas = tk.Canvas(
            self._root,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=self.BG_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Button>", lambda e: "break")

        # Masquer initialement (IDLE)
        self._root.withdraw()
        self._is_visible = False

    def _draw_frame_and_header(self, accent_color: str, title: str, badge: str):
        """Dessine le cadre HUD et l'en-tête."""
        c = self._canvas
        w = self.WIDTH
        h = self.HEIGHT

        # Cadre extérieur avec lueur
        c.create_rectangle(1, 1, w - 2, h - 2, outline=accent_color, width=1)
        c.create_rectangle(4, 4, w - 5, h - 5, outline="#2c3e50", width=1)

        # Coins décoratifs style HUD
        c.create_line(1, 8, 8, 1, fill=accent_color, width=2)
        c.create_line(w - 9, 1, w - 2, 8, fill=accent_color, width=2)
        c.create_line(1, h - 9, 8, h - 2, fill=accent_color, width=2)
        c.create_line(w - 9, h - 2, w - 2, h - 9, fill=accent_color, width=2)

        # Titre JARVIS
        c.create_text(16, 14, text=title, fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 8, "bold"))
        # Badge d'état à droite
        c.create_text(w - 16, 14, text=badge, fill=accent_color, anchor="e", font=("Segoe UI", 8, "bold"))

    def _render_waking_up(self):
        """Animation dynamique de réveil : ondes radar dorées pulsantes synchronisées."""
        c = self._canvas
        accent = self.ACCENT_GOLD
        self._draw_frame_and_header(accent, "JARVIS", "★ RÉVEIL")

        cx = 40
        cy = 48

        # Ondes concentriques en expansion
        phase1 = (self._anim_tick * 2) % 24
        phase2 = (self._anim_tick * 2 + 12) % 24
        r1 = 6 + phase1
        r2 = 6 + phase2

        c.create_oval(cx - r1, cy - r1, cx + r1, cy + r1, outline="#8c7800", width=1)
        c.create_oval(cx - r2, cy - r2, cx + r2, cy + r2, outline=accent, width=1)

        # Étoile / orbe centrale pulsante
        glow_size = 3 + int(math.sin(self._anim_tick * 0.4) * 2)
        c.create_oval(cx - glow_size, cy - glow_size, cx + glow_size, cy + glow_size, fill=accent, outline="")

        # Texte
        c.create_text(76, 42, text="À votre écoute", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 10, "bold"))
        c.create_text(76, 58, text="Initialisation vocale...", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 8))

    def _render_listening(self):
        """Animation dynamique d'écoute : barres audio + transcription en direct."""
        c = self._canvas
        accent = self.ACCENT_CYAN
        self._draw_frame_and_header(accent, "JARVIS", "◉ ÉCOUTE")

        # Barres d'animation audio (ondes sonores perçues)
        start_x = 18
        cy = 46
        num_bars = 6
        spacing = 6
        for i in range(num_bars):
            amp = math.sin(self._anim_tick * 0.25 + i * 0.9)
            bar_h = int(5 + 9 * abs(amp))
            x = start_x + (i * spacing)
            c.create_line(x, cy - bar_h, x, cy + bar_h, fill=accent, width=2)

        # Texte transcrit ou indication d'attente
        text_x = start_x + (num_bars * spacing) + 12
        if self._current_transcript:
            display_text = self._current_transcript
            if len(display_text) > 22:
                display_text = "..." + display_text[-19:]
            c.create_text(text_x, 38, text=display_text, fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 9, "bold"))
            c.create_text(text_x, 56, text="Transcription en direct", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 7))
        else:
            c.create_text(text_x, 38, text="Parlez maintenant...", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 9))
            c.create_text(text_x, 56, text="Fenêtre 30s active", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 7))

        # Indicateur de pulsation en bas
        pulse_alpha = abs(math.sin(self._anim_tick * 0.15))
        dot_color = accent if pulse_alpha > 0.4 else "#0984e3"
        c.create_oval(self.WIDTH - 18, self.HEIGHT - 12, self.WIDTH - 12, self.HEIGHT - 6, fill=dot_color, outline="")

    def _render_thinking(self):
        """Animation dynamique de réflexion : orbital spinner ambre/orange."""
        c = self._canvas
        accent = self.ACCENT_ORANGE
        self._draw_frame_and_header(accent, "JARVIS", "◌ RÉFLEXION")

        cx = 40
        cy = 48
        r = 12
        base_angle = self._anim_tick * 0.2

        for i in range(3):
            ang = base_angle + (i * (2 * math.pi / 3))
            px = cx + r * math.cos(ang)
            py = cy + r * math.sin(ang)
            size = 2 if i > 0 else 3
            c.create_oval(px - size, py - size, px + size, py + size, fill=accent, outline="")

        c.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill="#d63031", outline="")

        c.create_text(76, 42, text="Traitement...", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 10, "bold"))
        c.create_text(76, 58, text="Analyse de la demande", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 8))

    def _render_action(self):
        """Animation dynamique d'action / exécution d'outil."""
        c = self._canvas
        accent = self.ACCENT_ACTION
        self._draw_frame_and_header(accent, "JARVIS", "⚡ ACTION")

        cx = 40
        cy = 48

        pulse = 1 + int(math.sin(self._anim_tick * 0.3) * 3)
        c.create_text(cx, cy, text="⚡", fill=accent, font=("Segoe UI", 14 + pulse, "bold"))

        c.create_text(76, 42, text="Exécution en cours", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 10, "bold"))
        c.create_text(76, 58, text="Action système / outil", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 8))

    def _render_speaking(self):
        """Animation dynamique de parole : égaliseur sonore en sortie."""
        c = self._canvas
        accent = self.ACCENT_CYAN
        self._draw_frame_and_header(accent, "JARVIS", "◈ PAROLE")

        cx = 38
        cy = 48
        num_bars = 5
        bar_w = 4
        gap = 3
        total_w = num_bars * bar_w + (num_bars - 1) * gap
        start_x = cx - total_w // 2

        for i in range(num_bars):
            h_var = math.sin(self._anim_tick * 0.35 + i * 1.2) * 12
            bar_h = max(3, int(14 + h_var))
            bx = start_x + i * (bar_w + gap)
            c.create_rectangle(bx, cy - bar_h // 2, bx + bar_w, cy + bar_h // 2, fill=accent, outline="")

        c.create_text(76, 42, text="Réponse en cours", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 10, "bold"))
        c.create_text(76, 58, text="Synthèse vocale active", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 8))

    def _render_error(self):
        """Affichage d'erreur."""
        c = self._canvas
        accent = self.ACCENT_RED
        self._draw_frame_and_header(accent, "JARVIS", "⚠ ERREUR")

        c.create_text(38, 48, text="⚠", fill=accent, font=("Segoe UI", 16, "bold"))
        c.create_text(76, 42, text="Incident détecté", fill=self.TEXT_COLOR, anchor="w", font=("Segoe UI", 10, "bold"))
        c.create_text(76, 58, text="Reprise automatique...", fill=self.SUBTEXT_COLOR, anchor="w", font=("Segoe UI", 8))

    def _render_current_state(self):
        """Dessine l'état courant avec ses animations dynamiques."""
        if not self._canvas:
            return

        self._canvas.delete("all")

        if self._current_state == VoiceState.WAKING_UP:
            self._render_waking_up()
        elif self._current_state == VoiceState.LISTENING:
            self._render_listening()
        elif self._current_state == VoiceState.THINKING:
            self._render_thinking()
        elif self._current_state == VoiceState.ACTION:
            self._render_action()
        elif self._current_state == VoiceState.SPEAKING:
            self._render_speaking()
        elif self._current_state == VoiceState.ERROR:
            self._render_error()

    def _tick(self):
        """Boucle d'animation principale à ~30 FPS."""
        if not self._root or self._stop_event.is_set():
            return

        self._anim_tick += 1

        # 1. Vérifier la mise à jour de l'état
        snapshot = self._read_state_from_file()
        if snapshot is not None:
            new_state, new_transcript = snapshot
            self._current_state = new_state
            self._current_transcript = new_transcript

        # 2. Gestion de la visibilité selon l'état
        if self._current_state == VoiceState.IDLE:
            if self._is_visible:
                self._root.withdraw()
                self._is_visible = False
        else:
            if not self._is_visible:
                self._root.deiconify()
                self._root.lift()
                self._root.attributes("-topmost", True)
                self._is_visible = True
            # 3. Rendu dynamique de l'animation
            try:
                self._render_current_state()
            except Exception:
                logger.exception("Erreur rendu animation overlay")

        self._root.after(33, self._tick)

    def start(self):
        """Démarre l'overlay."""
        self._stop_event.clear()
        logger.debug("Démarrage overlay Tkinter...")
        try:
            self._create_overlay()
            logger.debug("Overlay Tkinter créé")
            self._root.after(33, self._tick)
            self._root.mainloop()
        except Exception:
            logger.exception("Erreur boucle overlay")
        finally:
            if self._root:
                self._root.destroy()
                self._root = None
                self._canvas = None
                logger.debug("Fenêtre Tkinter détruite")

    def stop(self):
        """Arrête l'overlay."""
        self._stop_event.set()


def lancer_process_overlay():
    """Lance l'overlay comme process séparé."""
    global _overlay_process
    
    with _overlay_lock:
        # Vérifier si un overlay est déjà en cours
        if _overlay_process is not None:
            try:
                # Vérifier si le processus est encore vivant
                if _overlay_process.poll() is None:
                    logger.debug("Overlay déjà en cours, pas de nouveau lancement")
                    return
                else:
                    # Processus terminé, nettoyer la référence
                    logger.debug("Processus overlay précédent terminé, nettoyage")
                    _overlay_process = None
            except Exception as e:
                logger.debug(f"Erreur vérification processus overlay: {e}")
                _overlay_process = None
        
        script = __file__
        try:
            # Lancer sans console visible (DETACHED_PROCESS sur Windows)
            # Utiliser STARTUPINFO pour masquer la fenêtre console
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            project_root = Path(__file__).resolve().parents[1]
            venv_python = project_root / ".venv" / "Scripts" / "python.exe"
            python_bin = str(venv_python) if venv_python.is_file() else sys.executable

            _overlay_process = subprocess.Popen(
                [python_bin, "-m", "jarvis.voice_overlay", "--standalone"],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                startupinfo=startupinfo if sys.platform == "win32" else None,
                cwd=str(project_root)
            )
            logger.debug(f"Overlay lancé avec PID {_overlay_process.pid}")
        except Exception as e:
            logger.error(f"Erreur lors du lancement de l'overlay: {e}")
            _overlay_process = None
            raise


def demarrer_overlay_vocal():
    """Démarre l'overlay vocal - alias pour compatibilité."""
    lancer_process_overlay()


def arreter_overlay_vocal():
    """Arrête l'overlay vocal de manière propre avec timeout."""
    global _overlay_process
    
    with _overlay_lock:
        if _overlay_process is None:
            logger.debug("Aucun overlay à arrêter")
            return
        
        try:
            # Vérifier si le processus est encore vivant
            if _overlay_process.poll() is not None:
                logger.debug("Processus overlay déjà terminé")
                _overlay_process = None
                return
            
            logger.debug(f"Arrêt de l'overlay PID {_overlay_process.pid}")
            
            # Arrêt propre : terminer le processus
            _overlay_process.terminate()
            
            # Attendre avec timeout (2 secondes)
            try:
                _overlay_process.wait(timeout=2.0)
                logger.debug("Overlay arrêté proprement")
            except subprocess.TimeoutExpired:
                # Force kill si timeout
                logger.debug("Timeout arrêt, force kill")
                _overlay_process.kill()
                _overlay_process.wait(timeout=1.0)
                logger.debug("Overlay forcé terminé")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt de l'overlay: {e}")
        finally:
            # Nettoyer l'état interne
            _overlay_process = None


def main_standalone():
    """Point d'entrée standalone pour l'overlay."""
    overlay = VoiceOverlay()
    overlay.start()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--standalone":
        main_standalone()
