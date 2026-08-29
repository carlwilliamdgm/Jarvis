"""
Interface visuelle pour la navigation en temps réel.

Ce module crée un overlay Tkinter montrant l'état des sessions de navigateur
en temps réel, similaire à l'overlay vocal mais pour la navigation web.
"""

import tkinter as tk
from tkinter import ttk
import threading
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime
from core.browser_session import BrowserSessionState, get_session_manager


class BrowserOverlay:
    """Overlay visuel pour la navigation en temps réel."""
    
    def __init__(self):
        """Initialise l'overlay de navigation."""
        self.root = None
        self.running = False
        self.thread = None
        self.manager = get_session_manager()
        self.state_file = os.path.join(os.path.dirname(__file__), "..", "browser_overlay_state.json")
        
        # Configuration visuelle
        self.bg_color = "#1a1a2e"
        self.text_color = "#00ff00"  # Vert pour l'état actif
        self.error_color = "#ff4444"
        self.warning_color = "#ffaa00"
        self.info_color = "#00aaff"
        self.font_main = ("Segoe UI", 10)
        self.font_title = ("Segoe UI", 12, "bold")
        
        # État de l'overlay
        self.current_sessions = {}
        self.last_update = None
    
    def _create_window(self):
        """Crée la fenêtre de l'overlay."""
        self.root = tk.Tk()
        self.root.title("Jarvis Browser Sessions")
        self.root.configure(bg=self.bg_color)
        
        # Configuration de la fenêtre
        self.root.overrideredirect(True)  # Sans bordure
        self.root.attributes("-topmost", True)  # Toujours au-dessus
        self.root.attributes("-alpha", 0.9)  # Transparence
        
        # Positionnement (en bas à droite)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = 400
        height = 300
        x = screen_width - width - 20
        y = screen_height - height - 100
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        # Frame principal
        self.main_frame = tk.Frame(self.root, bg=self.bg_color)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Titre
        title_label = tk.Label(
            self.main_frame,
            text="🌐 JARVIS BROWSER SESSIONS",
            font=self.font_title,
            bg=self.bg_color,
            fg=self.text_color
        )
        title_label.pack(pady=(0, 10))
        
        # Zone de contenu scrollable
        self.canvas = tk.Canvas(self.main_frame, bg=self.bg_color, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=self.bg_color)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # Labels pour les sessions
        self.session_labels = {}
        
        # Bouton de fermeture
        close_btn = tk.Button(
            self.main_frame,
            text="✕",
            command=self.close,
            bg=self.error_color,
            fg="white",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            cursor="hand2"
        )
        close_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-5, y=5)
    
    def _get_state_color(self, state: str) -> str:
        """Retourne la couleur correspondant à l'état."""
        state_colors = {
            BrowserSessionState.IDLE.value: self.text_color,
            BrowserSessionState.NAVIGATING.value: self.info_color,
            BrowserSessionState.LOADING.value: self.warning_color,
            BrowserSessionState.INTERACTING.value: self.info_color,
            BrowserSessionState.ERROR.value: self.error_color,
            BrowserSessionState.CLOSED.value: "#888888"
        }
        return state_colors.get(state, self.text_color)
    
    def _get_state_icon(self, state: str) -> str:
        """Retourne l'icône correspondant à l'état."""
        state_icons = {
            BrowserSessionState.IDLE.value: "●",
            BrowserSessionState.NAVIGATING.value: "◉",
            BrowserSessionState.LOADING.value: "◌",
            BrowserSessionState.INTERACTING.value: "◈",
            BrowserSessionState.ERROR.value: "⚠",
            BrowserSessionState.CLOSED.value: "○"
        }
        return state_icons.get(state, "●")
    
    def _update_display(self):
        """Met à jour l'affichage des sessions."""
        if not self.root:
            return
        
        # Effacer les labels existants
        for label in self.session_labels.values():
            label.destroy()
        self.session_labels.clear()
        
        # Obtenir les sessions actuelles
        sessions = self.manager.get_all_sessions()
        
        if not sessions:
            no_sessions_label = tk.Label(
                self.scrollable_frame,
                text="Aucune session active",
                font=self.font_main,
                bg=self.bg_color,
                fg="#888888"
            )
            no_sessions_label.pack(pady=20)
            self.session_labels["no_sessions"] = no_sessions_label
            return
        
        # Afficher chaque session
        for i, session in enumerate(sessions):
            session_frame = tk.Frame(self.scrollable_frame, bg="#252540", relief="raised", bd=1)
            session_frame.pack(fill="x", pady=5, padx=5)
            
            state = session.get("state", "unknown")
            color = self._get_state_color(state)
            icon = self._get_state_icon(state)
            
            # En-tête de session
            header = tk.Label(
                session_frame,
                text=f"{icon} {session.get('session_id', 'Unknown')}",
                font=("Segoe UI", 10, "bold"),
                bg="#252540",
                fg=color
            )
            header.pack(anchor="w", padx=5, pady=2)
            
            # URL actuelle
            url = session.get("current_url", "")
            if url:
                url_label = tk.Label(
                    session_frame,
                    text=f"📍 {url[:50]}..." if len(url) > 50 else f"📍 {url}",
                    font=("Segoe UI", 8),
                    bg="#252540",
                    fg="#cccccc"
                )
                url_label.pack(anchor="w", padx=5)
            
            # Titre de la page
            title = session.get("current_title", "")
            if title:
                title_label = tk.Label(
                    session_frame,
                    text=f"📄 {title[:40]}..." if len(title) > 40 else f"📄 {title}",
                    font=("Segoe UI", 8),
                    bg="#252540",
                    fg="#cccccc"
                )
                title_label.pack(anchor="w", padx=5)
            
            # Statistiques
            stats = f"Actions: {session.get('actions_count', 0)} | Screenshot: {'✓' if session.get('has_screenshot') else '✗'}"
            stats_label = tk.Label(
                session_frame,
                text=stats,
                font=("Segoe UI", 7),
                bg="#252540",
                fg="#888888"
            )
            stats_label.pack(anchor="w", padx=5, pady=2)
            
            # Erreur si présente
            error = session.get("error_message", "")
            if error:
                error_label = tk.Label(
                    session_frame,
                    text=f"❌ {error[:60]}..." if len(error) > 60 else f"❌ {error}",
                    font=("Segoe UI", 8),
                    bg="#252540",
                    fg=self.error_color,
                    wraplength=350
                )
                error_label.pack(anchor="w", padx=5, pady=2)
            
            self.session_labels[session.get("session_id", str(i))] = session_frame
    
    def _save_state(self):
        """Sauvegarde l'état de l'overlay."""
        try:
            state = {
                "running": self.running,
                "last_update": datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except Exception:
            pass
    
    def _run(self):
        """Boucle principale de l'overlay."""
        self._create_window()
        self.running = True
        
        def update_loop():
            if self.running:
                self._update_display()
                self._save_state()
                self.root.after(500, update_loop)  # Mise à jour toutes les 500ms
        
        update_loop()
        self.root.mainloop()
    
    def start(self):
        """Démarre l'overlay dans un thread séparé."""
        if self.thread and self.thread.is_alive():
            return False
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True
    
    def close(self):
        """Ferme l'overlay."""
        self.running = False
        if self.root:
            self.root.destroy()
        if self.thread:
            self.thread.join(timeout=2)
    
    def is_running(self) -> bool:
        """Vérifie si l'overlay est en cours d'exécution."""
        return self.running and (self.thread is not None) and self.thread.is_alive()


# Instance globale de l'overlay
_overlay_instance: Optional[BrowserOverlay] = None
_overlay_lock = threading.Lock()


def get_browser_overlay() -> BrowserOverlay:
    """Retourne l'instance globale de l'overlay de navigation."""
    global _overlay_instance
    
    with _overlay_lock:
        if _overlay_instance is None:
            _overlay_instance = BrowserOverlay()
        return _overlay_instance


def start_browser_overlay():
    """Démarre l'overlay de navigation."""
    overlay = get_browser_overlay()
    return overlay.start()


def stop_browser_overlay():
    """Arrête l'overlay de navigation."""
    overlay = get_browser_overlay()
    overlay.close()