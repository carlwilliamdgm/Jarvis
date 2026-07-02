import json
import os
import threading
import uuid
from urllib.parse import quote

import requests
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


HEADER_BG = "#0a0a0f"
TARGETS_FILE = os.path.join(os.path.dirname(__file__), "targets.json")


THEMES = {
    "dark": {
        "root": "#0a0a0f",
        "panel": "#0a0a0f",
        "footer": "#08080d",
        "input_bg": "#0c1018",
        "input_fg": "#7a9ab8",
        "input_border": "#1a2a3a",
        "user_bg": "#0d2a44",
        "user_border": "#1a4a6a",
        "user_fg": "#8ab8d8",
        "jarvis_bg": "#0d0d14",
        "jarvis_border": "#1a2030",
        "jarvis_fg": "#a8b8c8",
        "meta": "#6f8194",
        "button_bg": "#0c2a44",
        "button_fg": "white",
        "muted_button_bg": "#0d0d14",
        "status": "#1a4a6a",
    },
    "light": {
        "root": "#f4f6f8",
        "panel": "#f4f6f8",
        "footer": "#e8edf3",
        "input_bg": "#ffffff",
        "input_fg": "#23384d",
        "input_border": "#b8c7d8",
        "user_bg": "#d8ebfb",
        "user_border": "#8ab8d8",
        "user_fg": "#0d2a44",
        "jarvis_bg": "#ffffff",
        "jarvis_border": "#cad4df",
        "jarvis_fg": "#263746",
        "meta": "#587083",
        "button_bg": "#1a4a6a",
        "button_fg": "white",
        "muted_button_bg": "#dde5ee",
        "status": "#1a4a6a",
    },
}


class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis —")
        self.root.geometry("600x700")
        self.root.minsize(520, 600)
        self.theme_name = "dark"
        self.theme = THEMES[self.theme_name]
        self.is_streaming = False
        self.cancel_event = None
        self.themed_widgets = []
        
        # Instance management
        self.api_base = "http://localhost:8000"
        self.instances = []
        self.active_instance_id = "pc1-local"
        self.load_instances()

        self.root.configure(bg=self.theme["root"])

        self.header = tk.Frame(self.root, bg=HEADER_BG)
        self.header.pack(side="top", fill="x", pady=(18, 4))

        self.header_grid = tk.Frame(self.header, bg=HEADER_BG)
        self.header_grid.pack(fill="x", padx=14)

        self.title_stack = tk.Frame(self.header_grid, bg=HEADER_BG)
        self.title_stack.pack(side="top")

        self.label = tk.Label(
            self.title_stack,
            text="JARVIS",
            bg=HEADER_BG,
            fg="white",
            font=("Segoe UI", 24),
        )
        self.label.pack()

        self.subtitle = tk.Label(
            self.title_stack,
            text="by Carl-William",
            bg=HEADER_BG,
            fg="white",
            font=("Edwardian Script ITC", 17, "italic"),
        )
        self.subtitle.pack()

        # Instance selector
        self.instance_frame = tk.Frame(self.header_grid, bg=HEADER_BG)
        self.instance_frame.pack(side="right", padx=(0, 8))
        
        self.instance_var = tk.StringVar()
        self.instance_selector = ttk.Combobox(
            self.instance_frame,
            textvariable=self.instance_var,
            state="readonly",
            width=15,
            font=("Segoe UI", 10)
        )
        self.instance_selector.pack(side="left", padx=(0, 4))
        self.instance_selector.bind("<<ComboboxSelected>>", self.on_instance_change)
        
        self.instance_badge = tk.Label(
            self.instance_frame,
            text="",
            bg=self.theme["button_bg"],
            fg="white",
            font=("Segoe UI", 9, "bold"),
            padx=6,
            pady=2
        )
        self.instance_badge.pack(side="left")
        
        self.kill_button = tk.Button(
            self.instance_frame,
            text="Effacer",
            command=self.kill_instance,
            bg="#6a1a1a",
            fg="#ffd0d0",
            activebackground="#8a2a2a",
            activeforeground="#ffd0d0",
            relief="flat",
            font=("Segoe UI", 9),
            padx=8,
            pady=2
        )
        self.kill_button.pack(side="left", padx=(8, 0))
        
        self.manage_button = tk.Button(
            self.header_grid,
            text="⚙",
            command=self.open_instance_manager,
            bg=self.theme["muted_button_bg"],
            fg=self.theme["jarvis_fg"],
            activebackground=self.theme["button_bg"],
            activeforeground=self.theme["button_fg"],
            relief="flat",
            font=("Segoe UI", 12),
            width=3,
        )
        self.manage_button.pack(side="right", padx=(0, 4))
        
        self.theme_button = tk.Button(
            self.header_grid,
            text="☾",
            command=self.toggle_theme,
            bg=self.theme["muted_button_bg"],
            fg=self.theme["jarvis_fg"],
            activebackground=self.theme["button_bg"],
            activeforeground=self.theme["button_fg"],
            relief="flat",
            font=("Segoe UI", 12),
            width=3,
        )
        self.theme_button.pack(side="right")

        self.content = tk.Frame(self.root, bg=self.theme["root"])
        self.content.pack(side="top", fill="both", expand=True, padx=14, pady=10)

        self.canvas = tk.Canvas(self.content, bg=self.theme["root"], highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.content, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=self.theme["root"])
        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.footer = tk.Frame(self.root, bg=self.theme["footer"])
        self.footer.pack(side="bottom", fill="x", padx=14, pady=(0, 12))

        self.typing_label = tk.Label(
            self.footer,
            text="",
            bg=self.theme["footer"],
            fg=self.theme["status"],
            font=("Segoe UI", 10, "italic"),
            anchor="w",
        )
        self.typing_label.pack(side="top", fill="x", padx=2, pady=(8, 4))

        self.input_row = tk.Frame(self.footer, bg=self.theme["footer"])
        self.input_row.pack(side="bottom", fill="x", pady=(0, 8))

        self.input_field = tk.Text(
            self.input_row,
            height=1,
            wrap="word",
            bg=self.theme["input_bg"],
            fg=self.theme["input_fg"],
            insertbackground=self.theme["input_fg"],
            relief="flat",
            font=("Segoe UI", 12),
            padx=10,
            pady=8,
            undo=True,
        )
        self.input_field.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.input_field.bind("<Return>", self.send_message_enter)
        self.input_field.bind("<Shift-Return>", self.insert_newline)
        self.input_field.bind("<KeyRelease>", self.resize_textarea)

        self.send_button = tk.Button(
            self.input_row,
            text="→",
            command=self.send_message,
            bg=self.theme["button_bg"],
            fg=self.theme["button_fg"],
            activebackground=self.theme["button_bg"],
            activeforeground=self.theme["button_fg"],
            relief="flat",
            font=("Segoe UI", 14),
            width=3,
        )
        self.send_button.pack(side="left", padx=(0, 8))

        self.cancel_button = tk.Button(
            self.input_row,
            text="✕",
            command=self.cancel_stream,
            bg="#4a1a1a",
            fg="white",
            activebackground="#6a2222",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 12),
            width=3,
        )

        self.clear_button = tk.Button(
            self.input_row,
            text="Clear",
            command=self.clear_conversation,
            bg=self.theme["muted_button_bg"],
            fg=self.theme["jarvis_fg"],
            activebackground=self.theme["button_bg"],
            activeforeground=self.theme["button_fg"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.clear_button.pack(side="left")

    def _on_frame_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._scroll_bottom()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _scroll_bottom(self):
        self.root.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def resize_textarea(self, _event=None):
        try:
            counted = self.input_field.count("1.0", "end-1c", "displaylines")
            visual_lines = max(1, counted[0] if counted else 1)
        except tk.TclError:
            text = self.input_field.get("1.0", "end-1c")
            visual_lines = max(1, text.count("\n") + 1)
        self.input_field.configure(height=min(4, visual_lines))

    def insert_newline(self, _event=None):
        self.input_field.insert("insert", "\n")
        self.resize_textarea()
        return "break"

    def send_message_enter(self, _event=None):
        self.send_message()
        return "break"

    def _set_streaming(self, streaming):
        self.is_streaming = streaming
        state = tk.DISABLED if streaming else tk.NORMAL
        self.input_field.configure(state=state)
        self.send_button.configure(state=state)
        self.clear_button.configure(state=state)
        if streaming:
            if not self.cancel_button.winfo_ismapped():
                self.cancel_button.pack(side="left", padx=(0, 8), before=self.clear_button)
        else:
            if self.cancel_button.winfo_ismapped():
                self.cancel_button.pack_forget()
            self.input_field.focus_set()

    def send_message(self):
        if self.is_streaming:
            return
        message = self.input_field.get("1.0", "end-1c").strip()
        if not message:
            return
        self.input_field.delete("1.0", tk.END)
        self.resize_textarea()
        self._add_user_bubble(message)
        self.cancel_event = threading.Event()
        self._set_streaming(True)
        thread = threading.Thread(target=self.stream_message, args=(message, self.cancel_event), daemon=True)
        thread.start()

    def cancel_stream(self):
        if self.cancel_event:
            self.cancel_event.set()
        self._add_status("Flux interrompu.", "#9a6a1a")
        self._finish_stream()

    def stream_message(self, message, cancel_event):
        url = f"{self.api_base}/jarvis/stream?message={quote(message)}"
        try:
            with requests.get(url, stream=True, timeout=(5, None)) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if cancel_event.is_set():
                        break
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    self.root.after(0, self.handle_event, event)
                    if event.get("type") == "done":
                        break
        except requests.exceptions.RequestException as exc:
            if not cancel_event.is_set():
                self.root.after(0, self._add_error, f"Jarvis hors ligne. {exc}")
        finally:
            self.root.after(0, self._finish_stream)

    def handle_event(self, event):
        event_type = event.get("type")
        data = event.get("data", {})

        if event_type == "thinking":
            self.typing_label.configure(text=data.get("message", "Jarvis réfléchit..."), fg="#1a4a6a")
        elif event_type == "provider":
            provider = data.get("provider", "?")
            model = data.get("model", "?")
            self._add_status(f"✓ {provider} — {model}", "#1a6a3a")
        elif event_type == "stark_activated":
            self._add_banner(f"⚡ Mode Stark activé — {data.get('objectif', '')}", "#1a0a0a", "#5a1a1a", "#e0b8b8")
        elif event_type == "stark_action":
            outil = data.get("outil", "?")
            resultat = str(data.get("resultat", ""))[:120]
            bg = "#4a1a1a" if data.get("erreur") else "#1a4a1a"
            fg = "#ffd0d0" if data.get("erreur") else "#d5ecd5"
            self._add_action(f"  ⚡ {outil} → {resultat}", bg, fg)
        elif event_type == "stark_terminated":
            statut = data.get("statut", "")
            bg = "#0a1a0a" if statut == "terminé" else "#1a0f00"
            border = "#1a4a1a" if statut == "terminé" else "#5a3a1a"
            fg = "#d8ead8" if statut == "terminé" else "#f0d0a8"
            self._add_banner(data.get("rapport", ""), bg, border, fg)
        elif event_type == "response":
            self.typing_label.configure(text="")
            timestamp = data.get("timestamp", "")
            self._add_jarvis_bubble(data.get("text", ""), timestamp)
        elif event_type == "error":
            self._add_error(data.get("message", "Erreur inconnue."))
        elif event_type == "done":
            self._finish_stream()

    def _finish_stream(self):
        self.typing_label.configure(text="")
        self.cancel_event = None
        self._set_streaming(False)

    def _register_theme_widget(self, widget, role):
        self.themed_widgets.append((widget, role))

    def _apply_widget_theme(self, widget, role):
        theme = self.theme
        if role == "surface":
            widget.configure(bg=theme["root"])
        elif role == "footer":
            widget.configure(bg=theme["footer"])
        elif role == "meta":
            widget.configure(bg=theme["root"], fg=theme["meta"])
        elif role == "user":
            widget.configure(bg=theme["user_bg"], fg=theme["user_fg"], highlightbackground=theme["user_border"])
        elif role == "jarvis":
            widget.configure(bg=theme["jarvis_bg"], fg=theme["jarvis_fg"], highlightbackground=theme["jarvis_border"])
        elif role == "status":
            widget.configure(bg=theme["root"])

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.theme = THEMES[self.theme_name]
        self.theme_button.configure(text="☀" if self.theme_name == "light" else "☾")
        self.apply_theme()

    def apply_theme(self):
        theme = self.theme
        self.root.configure(bg=theme["root"])
        for widget in (self.header, self.header_grid, self.title_stack):
            widget.configure(bg=HEADER_BG)
        for widget in (self.content, self.scrollable_frame):
            widget.configure(bg=theme["root"])
        self.canvas.configure(bg=theme["root"])
        self.footer.configure(bg=theme["footer"])
        self.input_row.configure(bg=theme["footer"])
        self.typing_label.configure(bg=theme["footer"], fg=theme["status"])
        self.input_field.configure(bg=theme["input_bg"], fg=theme["input_fg"], insertbackground=theme["input_fg"])
        self.send_button.configure(bg=theme["button_bg"], fg=theme["button_fg"], activebackground=theme["button_bg"])
        self.clear_button.configure(bg=theme["muted_button_bg"], fg=theme["jarvis_fg"], activebackground=theme["button_bg"])
        self.theme_button.configure(bg=theme["muted_button_bg"], fg=theme["jarvis_fg"], activebackground=theme["button_bg"])
        self.label.configure(bg=HEADER_BG, fg="white")
        self.subtitle.configure(bg=HEADER_BG, fg="white")
        for widget, role in list(self.themed_widgets):
            if widget.winfo_exists():
                self._apply_widget_theme(widget, role)
        self._scroll_bottom()

    def _add_user_bubble(self, text):
        self._add_labeled_bubble("Vous", text, "e", "user")

    def _add_jarvis_bubble(self, text, timestamp):
        label = f"Jarvis — {timestamp}" if timestamp else "Jarvis"
        self._add_labeled_bubble(label, text, "w", "jarvis")

    def _add_labeled_bubble(self, label, text, anchor, role):
        wrapper = tk.Frame(self.scrollable_frame, bg=self.theme["root"])
        wrapper.pack(fill="x", padx=10, pady=6)
        self._register_theme_widget(wrapper, "surface")

        label_widget = tk.Label(
            wrapper,
            text=label,
            bg=self.theme["root"],
            fg=self.theme["meta"],
            font=("Segoe UI", 9),
        )
        label_widget.pack(anchor=anchor, padx=8)
        self._register_theme_widget(label_widget, "meta")

        bubble = tk.Label(
            wrapper,
            text=text,
            font=("Segoe UI", 11),
            wraplength=390,
            justify="left",
            padx=12,
            pady=10,
            highlightthickness=1,
        )
        self._apply_widget_theme(bubble, role)
        bubble.pack(anchor=anchor, padx=8)
        self._register_theme_widget(bubble, role)
        self._scroll_bottom()

    def _add_status(self, text, fg):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=self.theme["root"],
            fg=fg,
            font=("Segoe UI", 10, "italic"),
        )
        label.pack(anchor="w", padx=20, pady=3)
        self._register_theme_widget(label, "status")
        self._scroll_bottom()

    def _add_banner(self, text, bg, border, fg):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=bg,
            fg=fg,
            font=("Segoe UI", 11),
            wraplength=500,
            justify="left",
            padx=12,
            pady=10,
            highlightbackground=border,
            highlightthickness=1,
        )
        label.pack(fill="x", padx=14, pady=6)
        self._scroll_bottom()

    def _add_action(self, text, bg, fg):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=bg,
            fg=fg,
            font=("Segoe UI", 10),
            wraplength=480,
            justify="left",
            padx=10,
            pady=7,
        )
        label.pack(fill="x", padx=34, pady=3)
        self._scroll_bottom()

    def _add_error(self, text):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=self.theme["root"],
            fg="#ff4444",
            font=("Segoe UI", 11),
            wraplength=500,
            justify="left",
        )
        label.pack(anchor="w", padx=20, pady=6)
        self._register_theme_widget(label, "status")
        self._scroll_bottom()

    def clear_conversation(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.themed_widgets.clear()
        self.typing_label.configure(text="")
    
    # Instance Management Methods
    def load_instances(self):
        if os.path.exists(TARGETS_FILE):
            try:
                with open(TARGETS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.instances = data.get("instances", [])
                    self.active_instance_id = data.get("instance_active", "pc1-local")
            except Exception:
                self.instances = [
                    {"id": "pc1-local", "nom": "PC1 (local)", "url": "http://localhost:8000"}
                ]
                self.active_instance_id = "pc1-local"
        else:
            self.instances = [
                {"id": "pc1-local", "nom": "PC1 (local)", "url": "http://localhost:8000"}
            ]
            self.active_instance_id = "pc1-local"
            self.save_instances()
        
        self.update_instance_ui()
    
    def save_instances(self):
        data = {
            "instances": self.instances,
            "instance_active": self.active_instance_id
        }
        try:
            with open(TARGETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder les instances: {e}")
    
    def is_localhost(self, url):
        """Check if URL points to localhost."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            hostname = parsed.hostname.lower() if parsed.hostname else ""
            return hostname in ("localhost", "127.0.0.1")
        except:
            return False

    def update_instance_ui(self):
        instance_names = [inst["nom"] for inst in self.instances]
        self.instance_selector['values'] = instance_names
        
        active_inst = next((i for i in self.instances if i["id"] == self.active_instance_id), None)
        if active_inst:
            self.instance_var.set(active_inst["nom"])
            self.api_base = active_inst["url"]
            self.instance_badge.config(text=active_inst["nom"])
            self.root.title(f"Jarvis — {active_inst['nom']}")
            
            # Show/hide kill button based on whether it's a remote instance
            if self.is_localhost(active_inst["url"]):
                self.kill_button.pack_forget()
            else:
                self.kill_button.pack(side="left", padx=(8, 0))
        else:
            # Fallback to first instance
            if self.instances:
                self.active_instance_id = self.instances[0]["id"]
                self.update_instance_ui()
    
    def on_instance_change(self, event):
        selected_name = self.instance_var.get()
        selected_inst = next((i for i in self.instances if i["nom"] == selected_name), None)
        if selected_inst:
            self.active_instance_id = selected_inst["id"]
            self.api_base = selected_inst["url"]
            self.instance_badge.config(text=selected_inst["nom"])
            self.root.title(f"Jarvis — {selected_inst['nom']}")
            self.save_instances()
            self.refresh_status()
    
    def open_instance_manager(self):
        manager = InstanceManager(self.root, self)
        self.root.wait_window(manager.window)
        self.load_instances()
    
    def refresh_status(self):
        # Status check - can be extended to show visual indicator if needed
        try:
            response = requests.get(f"{self.api_base}/jarvis/status", timeout=5)
            if not response.ok:
                pass  # Could add visual error indicator here
        except:
            pass  # Could add visual error indicator here

    def kill_instance(self):
        """Kill the remote Jarvis instance."""
        active_inst = next((i for i in self.instances if i["id"] == self.active_instance_id), None)
        if not active_inst:
            return

        if self.is_localhost(active_inst["url"]):
            messagebox.showwarning("Avertissement", "Impossible d'effacer l'instance locale")
            return

        confirmed = messagebox.askyesno(
            "Confirmation",
            f"Effacer définitivement l'instance {active_inst['nom']} ?\n\nCette action est irréversible."
        )

        if not confirmed:
            return

        try:
            response = requests.post(
                f"{active_inst['url']}/jarvis/kill",
                timeout=10
            )

            if response.ok:
                self._add_status("Instance effacée", "#1a4a6a")
                
                # Remove the instance from the list
                self.instances = [i for i in self.instances if i["id"] != self.active_instance_id]
                
                # Switch to localhost
                self.active_instance_id = "pc1-local"
                self.save_instances()
                self.update_instance_ui()
                self.refresh_status()
            else:
                self._add_error("Erreur lors de l'effacement de l'instance")
        except requests.exceptions.Timeout:
            self._add_error("Impossible de joindre l'instance — vérifier Tailscale")
        except Exception as e:
            self._add_error(f"Erreur: {e}")


class InstanceManager:
    def __init__(self, parent, gui):
        self.gui = gui
        self.window = tk.Toplevel(parent)
        self.window.title("Gérer les instances Jarvis")
        self.window.geometry("500x600")
        self.window.configure(bg=gui.theme["root"])
        self.window.transient(parent)
        self.window.grab_set()
        
        self.editing_id = None
        
        self.setup_ui()
        self.refresh_list()
    
    def setup_ui(self):
        # Header
        header = tk.Frame(self.window, bg=self.gui.theme["header"], pady=12)
        header.pack(fill="x")
        
        title = tk.Label(
            header,
            text="Gérer les instances Jarvis",
            bg=self.gui.theme["header"],
            fg="white",
            font=("Segoe UI", 16, "bold")
        )
        title.pack()
        
        # Add/Edit form
        form_frame = tk.Frame(self.window, bg=self.gui.theme["root"], padx=20, pady=10)
        form_frame.pack(fill="x")
        
        tk.Label(
            form_frame,
            text="Nom:",
            bg=self.gui.theme["root"],
            fg=self.gui.theme["meta"],
            font=("Segoe UI", 10)
        ).grid(row=0, column=0, sticky="w", pady=4)
        
        self.name_entry = tk.Entry(
            form_frame,
            bg=self.gui.theme["input_bg"],
            fg=self.gui.theme["input_fg"],
            insertbackground=self.gui.theme["input_fg"],
            relief="flat",
            font=("Segoe UI", 11),
            width=30
        )
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=4, padx=8)
        
        tk.Label(
            form_frame,
            text="URL:",
            bg=self.gui.theme["root"],
            fg=self.gui.theme["meta"],
            font=("Segoe UI", 10)
        ).grid(row=1, column=0, sticky="w", pady=4)
        
        self.url_entry = tk.Entry(
            form_frame,
            bg=self.gui.theme["input_bg"],
            fg=self.gui.theme["input_fg"],
            insertbackground=self.gui.theme["input_fg"],
            relief="flat",
            font=("Segoe UI", 11),
            width=30
        )
        self.url_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=8)
        
        button_frame = tk.Frame(form_frame, bg=self.gui.theme["root"])
        button_frame.grid(row=2, column=0, columnspan=2, pady=8)
        
        tk.Button(
            button_frame,
            text="Tester",
            command=self.test_connection,
            bg=self.gui.theme["muted_button_bg"],
            fg=self.gui.theme["jarvis_fg"],
            relief="flat",
            font=("Segoe UI", 10),
            padx=12
        ).pack(side="left", padx=4)
        
        self.add_button = tk.Button(
            button_frame,
            text="Ajouter",
            command=self.add_instance,
            bg=self.gui.theme["button_bg"],
            fg="white",
            relief="flat",
            font=("Segoe UI", 10),
            padx=12
        )
        self.add_button.pack(side="left", padx=4)
        
        # Instance list
        list_frame = tk.Frame(self.window, bg=self.gui.theme["root"], padx=20, pady=10)
        list_frame.pack(fill="both", expand=True)
        
        tk.Label(
            list_frame,
            text="Instances configurées:",
            bg=self.gui.theme["root"],
            fg=self.gui.theme["meta"],
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", pady=(0, 8))
        
        self.list_container = tk.Frame(list_frame, bg=self.gui.theme["root"])
        self.list_container.pack(fill="both", expand=True)
        
        # Discovery section
        discovery_frame = tk.Frame(self.window, bg=self.gui.theme["root"], padx=20, pady=10)
        discovery_frame.pack(fill="x")
        
        self.discovery_var = tk.BooleanVar()
        discovery_check = tk.Checkbutton(
            discovery_frame,
            text="Découverte réseau Tailscale",
            variable=self.discovery_var,
            command=self.toggle_discovery,
            bg=self.gui.theme["root"],
            fg=self.gui.theme["text"],
            selectcolor=self.gui.theme["input_bg"],
            activebackground=self.gui.theme["root"],
            font=("Segoe UI", 10)
        )
        discovery_check.pack(anchor="w")
        
        self.discovery_results = tk.Frame(discovery_frame, bg=self.gui.theme["root"])
        self.discovery_results.pack(fill="x", pady=8)
    
    def refresh_list(self):
        for widget in self.list_container.winfo_children():
            widget.destroy()
        
        for inst in self.gui.instances:
            item = tk.Frame(
                self.list_container,
                bg=self.gui.theme["input_bg"],
                pady=8,
                padx=10
            )
            item.pack(fill="x", pady=4)
            
            info = tk.Frame(item, bg=self.gui.theme["input_bg"])
            info.pack(side="left", fill="x", expand=True)
            
            tk.Label(
                info,
                text=inst["nom"],
                bg=self.gui.theme["input_bg"],
                fg=self.gui.theme["text"],
                font=("Segoe UI", 11, "bold")
            ).pack(anchor="w")
            
            tk.Label(
                info,
                text=inst["url"],
                bg=self.gui.theme["input_bg"],
                fg=self.gui.theme["meta"],
                font=("Segoe UI", 9)
            ).pack(anchor="w")
            
            if inst["id"] != "pc1-local":
                actions = tk.Frame(item, bg=self.gui.theme["input_bg"])
                actions.pack(side="right", padx=8)
                
                tk.Button(
                    actions,
                    text="Modifier",
                    command=lambda iid=inst["id"]: self.edit_instance(iid),
                    bg=self.gui.theme["muted_button_bg"],
                    fg=self.gui.theme["jarvis_fg"],
                    relief="flat",
                    font=("Segoe UI", 9),
                    padx=8
                ).pack(side="left", padx=2)
                
                tk.Button(
                    actions,
                    text="Supprimer",
                    command=lambda iid=inst["id"]: self.delete_instance(iid),
                    bg="#6a1a1a",
                    fg="#ffd0d0",
                    relief="flat",
                    font=("Segoe UI", 9),
                    padx=8
                ).pack(side="left", padx=2)
    
    def test_connection(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Avertissement", "Veuillez entrer une URL")
            return
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                messagebox.showerror("Erreur", "URL invalide (doit commencer par http:// ou https://)")
                return
        except:
            messagebox.showerror("Erreur", "URL invalide")
            return
        
        try:
            response = requests.get(f"{url}/jarvis/status", timeout=5)
            if response.ok:
                messagebox.showinfo("Succès", "Connexion réussie !")
            else:
                messagebox.showerror("Erreur", "Connexion échouée (service non disponible)")
        except Exception as e:
            messagebox.showerror("Erreur", f"Connexion échouée: {e}")
    
    def add_instance(self):
        name = self.name_entry.get().strip()
        url = self.url_entry.get().strip()
        
        if not name or not url:
            messagebox.showwarning("Avertissement", "Veuillez remplir le nom et l'URL")
            return
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                messagebox.showerror("Erreur", "URL invalide (doit commencer par http:// ou https://)")
                return
        except:
            messagebox.showerror("Erreur", "URL invalide")
            return
        
        if self.editing_id:
            inst = next((i for i in self.gui.instances if i["id"] == self.editing_id), None)
            if inst:
                inst["nom"] = name
                inst["url"] = url
            self.editing_id = None
            self.add_button.config(text="Ajouter")
        else:
            new_inst = {
                "id": f"inst-{uuid.uuid4().hex[:8]}",
                "nom": name,
                "url": url
            }
            self.gui.instances.append(new_inst)
        
        self.gui.save_instances()
        self.name_entry.delete(0, tk.END)
        self.url_entry.delete(0, tk.END)
        self.refresh_list()
    
    def edit_instance(self, instance_id):
        inst = next((i for i in self.gui.instances if i["id"] == instance_id), None)
        if inst:
            self.editing_id = instance_id
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, inst["nom"])
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, inst["url"])
            self.add_button.config(text="Mettre à jour")
    
    def delete_instance(self, instance_id):
        if messagebox.askyesno("Confirmation", "Supprimer cette instance ?"):
            self.gui.instances = [i for i in self.gui.instances if i["id"] != instance_id]
            if self.gui.active_instance_id == instance_id:
                self.gui.active_instance_id = "pc1-local"
            self.gui.save_instances()
            self.refresh_list()
    
    def toggle_discovery(self):
        if self.discovery_var.get():
            self.run_discovery()
        else:
            for widget in self.discovery_results.winfo_children():
                widget.destroy()
    
    def run_discovery(self):
        for widget in self.discovery_results.winfo_children():
            widget.destroy()
        
        tk.Label(
            self.discovery_results,
            text="Recherche en cours...",
            bg=self.gui.theme["root"],
            fg=self.gui.theme["meta"],
            font=("Segoe UI", 10)
        ).pack()
        
        try:
            response = requests.get(f"{self.gui.api_base}/jarvis/discover", timeout=10)
            if not response.ok:
                error = response.json()
                raise Exception(error.get("detail", "Erreur de découverte"))
            
            data = response.json()
            devices = data.get("devices", [])
            
            for widget in self.discovery_results.winfo_children():
                widget.destroy()
            
            if not devices:
                tk.Label(
                    self.discovery_results,
                    text="Aucun appareil détecté",
                    bg=self.gui.theme["root"],
                    fg=self.gui.theme["meta"],
                    font=("Segoe UI", 10)
                ).pack()
                return
            
            for device in devices:
                item = tk.Frame(
                    self.discovery_results,
                    bg=self.gui.theme["input_bg"],
                    pady=6,
                    padx=10
                )
                item.pack(fill="x", pady=4)
                
                info = tk.Frame(item, bg=self.gui.theme["input_bg"])
                info.pack(side="left", fill="x", expand=True)
                
                tk.Label(
                    info,
                    text=device["nom"],
                    bg=self.gui.theme["input_bg"],
                    fg=self.gui.theme["text"],
                    font=("Segoe UI", 10, "bold")
                ).pack(anchor="w")
                
                tk.Label(
                    info,
                    text=device["ip"],
                    bg=self.gui.theme["input_bg"],
                    fg=self.gui.theme["meta"],
                    font=("Segoe UI", 9)
                ).pack(anchor="w")
                
                status = tk.Label(
                    item,
                    text="Test...",
                    bg=self.gui.theme["input_bg"],
                    fg=self.gui.theme["meta"],
                    font=("Segoe UI", 9)
                )
                status.pack(side="right", padx=8)
                
                # Test Jarvis on port 8000
                jarvis_url = f"http://{device['ip']}:8000"
                try:
                    test_resp = requests.get(f"{jarvis_url}/jarvis/status", timeout=3)
                    is_online = test_resp.ok
                except:
                    is_online = False
                
                status.config(
                    text="Jarvis actif" if is_online else "Hors ligne",
                    fg="#d5ecd5" if is_online else "#ffd0d0"
                )
                
                if is_online:
                    add_btn = tk.Button(
                        item,
                        text="Ajouter",
                        command=lambda n=device["nom"], u=jarvis_url: self.quick_add(n, u),
                        bg=self.gui.theme["button_bg"],
                        fg="white",
                        relief="flat",
                        font=("Segoe UI", 9),
                        padx=8
                    )
                    add_btn.pack(side="right", padx=4)
        
        except Exception as e:
            for widget in self.discovery_results.winfo_children():
                widget.destroy()
            tk.Label(
                self.discovery_results,
                text=f"Erreur: {e}",
                bg=self.gui.theme["root"],
                fg="#ff4444",
                font=("Segoe UI", 10)
            ).pack()
    
    def quick_add(self, name, url):
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, name)
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, url)
        self.discovery_var.set(False)
        for widget in self.discovery_results.winfo_children():
            widget.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisGUI(root)
    root.mainloop()
