import tkinter as tk
from tkinter import scrolledtext
import requests
import threading

class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Jarvis —")
        self.root.configure(bg="#1e1e1e")
        self.root.geometry("600x700")

        self.label = tk.Label(self.root, text="JARVIS", bg="#1e1e1e", fg="white", font=("Segoe UI", 24))
        self.label.pack(pady=20)

        self.subtitle = tk.Label(self.root, text="GreatOS v0.1", bg="#1e1e1e", fg="#cccccc", font=("Segoe UI", 12))
        self.subtitle.pack()

        self.conversation_zone = tk.Frame(self.root, bg="#1e1e1e")
        self.conversation_zone.pack(pady=20, fill="both", expand=True)

        self.input_field = tk.Entry(self.root, width=50, bg="#1e1e1e", fg="white", insertbackground="white", font=("Segoe UI", 12))
        self.input_field.pack(side=tk.LEFT, padx=10)

        self.send_button = tk.Button(self.root, text="Send", command=self.send_message, bg="#1e1e1e", fg="white", font=("Segoe UI", 12))
        self.send_button.pack(side=tk.LEFT, padx=10)

        self.clear_button = tk.Button(self.root, text="Clear", command=self.clear_conversation, bg="#1e1e1e", fg="white", font=("Segoe UI", 12))
        self.clear_button.pack(side=tk.LEFT, padx=10)

        self.root.bind("<Return>", self.send_message_enter)

        self.typing_label = tk.Label(self.root, text="Jarvis is typing...", bg="#1e1e1e", fg="white", font=("Segoe UI", 12))
        self.typing_label.pack(side=tk.LEFT, padx=10)

    def send_message(self):
        message = self.input_field.get()
        self.input_field.delete(0, tk.END)

        threading.Thread(target=self.post_message, args=(message,)).start()

    def send_message_enter(self, event):
        self.send_message()

    def post_message(self, message):
        self.typing_label.pack(side=tk.LEFT, padx=10)
        try:
            response = requests.post("http://localhost:8000/jarvis/ask", json={"message": message})
            response.raise_for_status()
            response_json = response.json()
            self.conversation_zone.pack_forget()
            self.conversation_zone = tk.Frame(self.root, bg="#1e1e1e")
            self.conversation_zone.pack(pady=20, fill="both", expand=True)
            user_label = tk.Label(self.conversation_zone, text=f"Vous : {message}", bg="#007bff", fg="white", font=("Segoe UI", 12), wraplength=200, justify="right")
            user_label.pack(side=tk.RIGHT, padx=10, pady=10)
            jarvis_label = tk.Label(self.conversation_zone, text=f"Jarvis : {response_json['response']}", bg="#2f2f2f", fg="white", font=("Segoe UI", 12), wraplength=200, justify="left")
            jarvis_label.pack(side=tk.LEFT, padx=10, pady=10)
            self.typing_label.pack_forget()
        except requests.exceptions.RequestException:
            self.conversation_zone.pack_forget()
            self.conversation_zone = tk.Frame(self.root, bg="#1e1e1e")
            self.conversation_zone.pack(pady=20, fill="both", expand=True)
            error_label = tk.Label(self.conversation_zone, text="Jarvis hors ligne.", bg="#1e1e1e", fg="white", font=("Segoe UI", 12))
            error_label.pack(side=tk.LEFT, padx=10, pady=10)
            self.typing_label.pack_forget()

    def clear_conversation(self):
        self.conversation_zone.pack_forget()
        self.conversation_zone = tk.Frame(self.root, bg="#1e1e1e")
        self.conversation_zone.pack(pady=20, fill="both", expand=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = JarvisGUI(root)
    root.mainloop()
