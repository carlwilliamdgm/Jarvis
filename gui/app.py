import json
import threading
from urllib.parse import quote

import requests
import tkinter as tk


API_BASE = "http://localhost:8000"


class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis —")
        self.root.configure(bg="#0a0a0f")
        self.root.geometry("600x700")
        self.root.minsize(520, 600)
        self.is_streaming = False

        self.header = tk.Frame(self.root, bg="#0a0a0f")
        self.header.pack(fill="x", pady=(18, 4))

        self.label = tk.Label(
            self.header,
            text="JARVIS",
            bg="#0a0a0f",
            fg="white",
            font=("Segoe UI", 24),
        )
        self.label.pack()

        self.subtitle = tk.Label(
            self.header,
            text="by Carl-William",
            bg="#0a0a0f",
            fg="white",
            font=("Edwardian Script ITC", 17, "italic"),
        )
        self.subtitle.pack()

        self.canvas = tk.Canvas(self.root, bg="#0a0a0f", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#0a0a0f")
        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=14)
        self.scrollbar.pack(side="right", fill="y", pady=14)

        bottom_frame = tk.Frame(self.root, bg="#0a0a0f")
        bottom_frame.pack(fill="x", padx=14, pady=(0, 10))

        self.input_field = tk.Entry(
            bottom_frame,
            bg="#0c1018",
            fg="#7a9ab8",
            insertbackground="#7a9ab8",
            relief="flat",
            font=("Segoe UI", 12),
        )
        self.input_field.pack(side=tk.LEFT, fill="x", expand=True, ipady=8, padx=(0, 8))
        self.input_field.bind("<Return>", self.send_message_enter)

        self.send_button = tk.Button(
            bottom_frame,
            text="→",
            command=self.send_message,
            bg="#0c2a44",
            fg="white",
            activebackground="#123a5c",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 14),
            width=3,
        )
        self.send_button.pack(side=tk.LEFT, padx=(0, 8))

        self.clear_button = tk.Button(
            bottom_frame,
            text="Clear",
            command=self.clear_conversation,
            bg="#0d0d14",
            fg="#a8b8c8",
            activebackground="#1a2030",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.clear_button.pack(side=tk.LEFT)

        self.typing_label = tk.Label(
            self.root,
            text="",
            bg="#0a0a0f",
            fg="#1a4a6a",
            font=("Segoe UI", 11, "italic"),
        )
        self.typing_label.pack(fill="x", padx=14, pady=(0, 10))

    def _on_frame_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._scroll_bottom()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _scroll_bottom(self):
        self.root.after_idle(lambda: self.canvas.yview_moveto(1.0))

    def _set_streaming(self, streaming):
        self.is_streaming = streaming
        state = tk.DISABLED if streaming else tk.NORMAL
        self.input_field.configure(state=state)
        self.send_button.configure(state=state)

    def send_message(self):
        if self.is_streaming:
            return
        message = self.input_field.get().strip()
        if not message:
            return
        self.input_field.delete(0, tk.END)
        self._add_user_bubble(message)
        self._set_streaming(True)
        thread = threading.Thread(target=self.stream_message, args=(message,), daemon=True)
        thread.start()

    def send_message_enter(self, _event):
        self.send_message()

    def stream_message(self, message):
        url = f"{API_BASE}/jarvis/stream?message={quote(message)}"
        try:
            with requests.get(url, stream=True, timeout=(5, None)) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
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
            self._add_banner(f"⚡ Mode Stark activé — {data.get('objectif', '')}", "#1a0a0a", "#5a1a1a")
        elif event_type == "stark_action":
            outil = data.get("outil", "?")
            resultat = str(data.get("resultat", ""))[:120]
            bg = "#4a1a1a" if data.get("erreur") else "#1a4a1a"
            self._add_action(f"  ⚡ {outil} → {resultat}", bg)
        elif event_type == "stark_terminated":
            statut = data.get("statut", "")
            bg = "#0a1a0a" if statut == "terminé" else "#1a0f00"
            border = "#1a4a1a" if statut == "terminé" else "#5a3a1a"
            self._add_banner(data.get("rapport", ""), bg, border)
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
        self._set_streaming(False)

    def _add_user_bubble(self, text):
        self._add_labeled_bubble("Vous", text, "e", "#0d2a44", "#1a4a6a", "#8ab8d8")

    def _add_jarvis_bubble(self, text, timestamp):
        label = f"Jarvis — {timestamp}" if timestamp else "Jarvis"
        self._add_labeled_bubble(label, text, "w", "#0d0d14", "#1a2030", "#a8b8c8")

    def _add_labeled_bubble(self, label, text, anchor, bg, border, fg):
        wrapper = tk.Frame(self.scrollable_frame, bg="#0a0a0f")
        wrapper.pack(fill="x", padx=10, pady=6)

        label_widget = tk.Label(
            wrapper,
            text=label,
            bg="#0a0a0f",
            fg="#6f8194",
            font=("Segoe UI", 9),
        )
        label_widget.pack(anchor=anchor, padx=8)

        bubble = tk.Label(
            wrapper,
            text=text,
            bg=bg,
            fg=fg,
            font=("Segoe UI", 11),
            wraplength=390,
            justify="left",
            padx=12,
            pady=10,
            highlightbackground=border,
            highlightthickness=1,
        )
        bubble.pack(anchor=anchor, padx=8)
        self._scroll_bottom()

    def _add_status(self, text, fg):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg="#0a0a0f",
            fg=fg,
            font=("Segoe UI", 10, "italic"),
        )
        label.pack(anchor="w", padx=20, pady=3)
        self._scroll_bottom()

    def _add_banner(self, text, bg, border):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=bg,
            fg="#d8d8d8",
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

    def _add_action(self, text, bg):
        label = tk.Label(
            self.scrollable_frame,
            text=text,
            bg=bg,
            fg="#d5ecd5",
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
            bg="#0a0a0f",
            fg="#ff4444",
            font=("Segoe UI", 11),
            wraplength=500,
            justify="left",
        )
        label.pack(anchor="w", padx=20, pady=6)
        self._scroll_bottom()

    def clear_conversation(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.typing_label.configure(text="")


if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisGUI(root)
    root.mainloop()
