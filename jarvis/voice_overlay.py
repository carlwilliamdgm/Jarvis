"""Overlay visuel flottant pour l'état vocal de Jarvis.

Thread Tkinter dédié, indépendant de la boucle asyncio uvicorn.
Lit l'état via un fichier JSON partagé, écrit par voice_state.py.
Affiche un HUD discret en bas à droite de l'écran lors des états actifs.
"""

import json
import logging
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
    """Overlay visuel flottant pour l'état vocal (process séparé)."""

    # Configuration visuelle style HUD
    BG_COLOR = "#1a1a2e"  # Fond sombre
    ACCENT_COLOR = "#00d4ff"  # Cyan froid
    ERROR_COLOR = "#ff4757"  # Rouge erreur
    THINKING_COLOR = "#ffa502"  # Orange réflexion
    TEXT_COLOR = "#ffffff"  # Blanc
    GLOW_COLOR = "#00d4ff"  # Lueur cyan
    
    # Dimensions et positionnement
    WIDTH = 180
    HEIGHT = 80
    POSITION = "bottom-right"  # Coin bas-droite
    
    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._current_state = VoiceState.IDLE
        self._stop_event = threading.Event()
        
    def _get_position_coords(self) -> tuple[int, int]:
        """Calcule les coordonnées selon le positionnement choisi."""
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        
        if self.POSITION == "bottom-right":
            x = screen_width - self.WIDTH - 20
            y = screen_height - self.HEIGHT - 20
        elif self.POSITION == "bottom-left":
            x = 20
            y = screen_height - self.HEIGHT - 20
        elif self.POSITION == "top-right":
            x = screen_width - self.WIDTH - 20
            y = 20
        else:  # top-left
            x = 20
            y = 20
            
        return x, y
    
    def _read_state_from_file(self) -> VoiceState:
        """Lit l'état depuis le fichier JSON partagé."""
        try:
            if VOICE_STATE_FILE.exists():
                with open(VOICE_STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    state_str = data.get("state", "idle")
                    return VoiceState(state_str)
        except (json.JSONDecodeError, IOError, ValueError, AttributeError, TypeError):
            logger.debug("Fichier d'état vocal invalide ou incomplet")
        return VoiceState.IDLE
    
    def _get_state_config(self) -> dict:
        """Retourne la configuration visuelle selon l'état."""
        configs = {
            VoiceState.LISTENING: {
                "accent": self.ACCENT_COLOR,
                "glow": self.ACCENT_COLOR,
                "label": "ÉCOUTE",
                "icon": "◉"
            },
            VoiceState.THINKING: {
                "accent": self.THINKING_COLOR,
                "glow": self.THINKING_COLOR,
                "label": "RÉFLEXION",
                "icon": "◌"
            },
            VoiceState.SPEAKING: {
                "accent": self.ACCENT_COLOR,
                "glow": self.ACCENT_COLOR,
                "label": "PAROLE",
                "icon": "◈"
            },
            VoiceState.ERROR: {
                "accent": self.ERROR_COLOR,
                "glow": self.ERROR_COLOR,
                "label": "ERREUR",
                "icon": "⚠"
            },
            VoiceState.IDLE: {
                "accent": self.ACCENT_COLOR,
                "glow": self.ACCENT_COLOR,
                "label": "",
                "icon": ""
            }
        }
        return configs.get(self._current_state, configs[VoiceState.IDLE])
    
    def _create_overlay(self):
        """Crée la fenêtre overlay style HUD."""
        self._root = tk.Tk()
        
        # Configuration fenêtre sans bordure, topmost
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.95)  # Légère transparence
        self._root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        
        # Positionnement
        x, y = self._get_position_coords()
        self._root.geometry(f"+{x}+{y}")
        
        # Désactiver la capture de focus et d'entrées
        self._root.bind("<Button>", lambda e: "break")  # Bloquer les clics
        self._root.bind("<Key>", lambda e: "break")     # Bloquer les touches
        
        # Fond avec effet de lueur simulé
        self._canvas = tk.Canvas(
            self._root,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=self.BG_COLOR,
            highlightthickness=2,
            highlightbackground=self.ACCENT_COLOR
        )
        canvas = self._canvas
        canvas.pack(fill=tk.BOTH, expand=True)
        
        # Désactiver les événements sur le canvas
        canvas.bind("<Button>", lambda e: "break")
        
        # Cadre intérieur fin
        canvas.create_rectangle(
            4, 4, self.WIDTH - 4, self.HEIGHT - 4,
            outline=self.ACCENT_COLOR,
            width=1
        )
        
        # Titre JARVIS
        canvas.create_text(
            self.WIDTH // 2,
            15,
            text="JARVIS",
            fill=self.TEXT_COLOR,
            font=("Segoe UI", 10, "bold")
        )
        
        # Conteneur pour les éléments dynamiques
        self._icon_id = canvas.create_text(
            self.WIDTH // 2,
            35,
            text="",
            fill=self.ACCENT_COLOR,
            font=("Segoe UI", 16)
        )
        
        self._label_id = canvas.create_text(
            self.WIDTH // 2,
            55,
            text="",
            fill=self.TEXT_COLOR,
            font=("Segoe UI", 9)
        )
        
        # Indicateur d'état (petit point en bas)
        self._status_dot_id = canvas.create_oval(
            self.WIDTH // 2 - 3,
            self.HEIGHT - 8,
            self.WIDTH // 2 + 3,
            self.HEIGHT - 2,
            fill=self.ACCENT_COLOR,
            outline=""
        )
        
        # Masquer initialement
        self._root.withdraw()
    
    def _update_visuals(self):
        """Met à jour l'apparence selon l'état courant."""
        if not self._root or not self._canvas:
            return
            
        config = self._get_state_config()
        
        # Gestion visibilité
        if self._current_state == VoiceState.IDLE:
            self._root.withdraw()
            return
        else:
            self._root.deiconify()
        
        # Mise à jour des éléments
        canvas = self._canvas
        
        # Couleur d'accent
        canvas.itemconfig(self._icon_id, fill=config["accent"])
        canvas.itemconfig(self._status_dot_id, fill=config["accent"])
        canvas.config(highlightbackground=config["accent"])
        
        # Texte
        canvas.itemconfig(self._icon_id, text=config["icon"])
        canvas.itemconfig(self._label_id, text=config["label"])
    
    def _check_state(self):
        """Vérifie périodiquement l'état sans bloquer Tkinter."""
        if not self._root or self._stop_event.is_set():
            return

        new_state = self._read_state_from_file()
        if new_state != self._current_state:
            self._current_state = new_state
            try:
                self._update_visuals()
            except Exception:
                logger.exception("Erreur lors de la mise à jour de l'overlay")

        self._root.after(100, self._check_state)
    
    def start(self):
        """Démarre l'overlay (process autonome)."""
        self._stop_event.clear()
        logger.debug("Démarrage overlay Tkinter...")
        
        try:
            self._create_overlay()
            logger.debug("Overlay Tkinter créé")
            self._root.after(100, self._check_state)
            self._root.mainloop()
        except Exception:
            logger.exception("Erreur overlay")
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
            
            _overlay_process = subprocess.Popen(
                [sys.executable, "-m", "core.voice_overlay", "--standalone"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=startupinfo,
                cwd=str(Path(__file__).parent.parent)
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