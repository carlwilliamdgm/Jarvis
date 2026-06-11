import tkinter as tk
import requests
import threading

class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis —")
        self.root.configure(bg="black")
        self.root.geometry("600x700")

        # Header
        self.label = tk.Label(self.root, text="JARVIS", bg="black", fg="white", font=("Segoe UI", 24))
        self.label.pack(pady=20)

        self.subtitle = tk.Label(self.root, text="by Carl-William", bg="black", fg="white", font=("Edwardian Script ITC", 17))
        self.subtitle.pack()

        # Conversation zone with scroll
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="black")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, pady=20)
        self.scrollbar.pack(side="right", fill="y")

        # Input + buttons
        bottom_frame = tk.Frame(self.root, bg="black")
        bottom_frame.pack(pady=10)

        self.input_field = tk.Entry(bottom_frame, width=40, bg="black", fg="white", insertbackground="white", font=("Segoe UI", 12))
        self.input_field.pack(side=tk.LEFT, padx=5)
        self.input_field.bind("<Return>", self.send_message_enter)

        self.send_button = tk.Button(bottom_frame, text="Send", command=self.send_message, bg="black", fg="white", font=("Segoe UI", 12))
        self.send_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(bottom_frame, text="Clear", command=self.clear_conversation, bg="black", fg="white", font=("Segoe UI", 12))
        self.clear_button.pack(side=tk.LEFT, padx=5)

        self.typing_label = tk.Label(self.root, text="", bg="black", fg="white", font=("Segoe UI", 12))
        self.typing_label.pack()

    def send_message(self):
        message = self.input_field.get().strip()
        if not message:
            return
        self.input_field.delete(0, tk.END)
        threading.Thread(target=self.post_message, args=(message,)).start()

    def send_message_enter(self, event):
        self.send_message()

    def post_message(self, message):
        self.typing_label.config(text="Jarvis is typing...")
        try:
            response = requests.post("http://localhost:8000/jarvis/ask", json={"message": message})
            response.raise_for_status()
            response_json = response.json()

            # User bubble
            user_label = tk.Label(self.scrollable_frame, text=f"Vous : {message}",
                                  bg="#007bff", fg="white", font=("Segoe UI", 12),
                                  wraplength=300, justify="right")
            user_label.pack(anchor="e", padx=10, pady=5)

            # Jarvis bubble
            jarvis_label = tk.Label(self.scrollable_frame, text=f"Jarvis : {response_json['response']}",
                                    bg="#2f2f2f", fg="white", font=("Segoe UI", 12),
                                    wraplength=300, justify="left")
            jarvis_label.pack(anchor="w", padx=10, pady=5)

        except requests.exceptions.RequestException:
            error_label = tk.Label(self.scrollable_frame, text="Jarvis hors ligne.",
                                   bg="black", fg="red", font=("Segoe UI", 12))
            error_label.pack(anchor="w", padx=10, pady=5)
        finally:
            self.typing_label.config(text="")
            self.canvas.yview_moveto(1.0)  # auto-scroll to bottom

    def clear_conversation(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisGUI(root)
    root.mainloop()
