import json
import threading
from urllib.parse import quote

import requests
import tkinter as tk


API_BASE = "http://localhost:8000"
HEADER_BG = "#0a0a0f"


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
        self.theme_button.place(relx=1.0, rely=0.0, anchor="ne")

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
        url = f"{API_BASE}/jarvis/stream?message={quote(message)}"
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


if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisGUI(root)
    root.mainloop()
