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

        self.label = tk.Label(self.root, text="JARVIS", bg="#1e1e1e", fg="white", font=("Arial", 24))
        self.label.pack(pady=20)

        self.subtitle = tk.Label(self.root, text="GreatOS v0.1", bg="#1e1e1e", fg="#cccccc", font=("Arial", 12))
        self.subtitle.pack()

        self.conversation_zone = scrolledtext.ScrolledText(self.root, width=70, height=20, bg="#1e1e1e", fg="white")
        self.conversation_zone.pack(pady=20)

        self.input_field = tk.Entry(self.root, width=50, bg="#1e1e1e", fg="white", insertbackground="white")
        self.input_field.pack(side=tk.LEFT, padx=10)

        self.send_button = tk.Button(self.root, text="Send", command=self.send_message, bg="#1e1e1e", fg="white")
        self.send_button.pack(side=tk.LEFT, padx=10)

        self.root.bind("<Return>", self.send_message_enter)

    def send_message(self):
        message = self.input_field.get()
        self.input_field.delete(0, tk.END)

        threading.Thread(target=self.post_message, args=(message,)).start()

    def send_message_enter(self, event):
        self.send_message()

    def post_message(self, message):
        try:
            response = requests.post("http://localhost:8000/jarvis/ask", json={"message": message})
            response.raise_for_status()
            response_json = response.json()
            self.conversation_zone.insert(tk.END, f"Vous : {message}\n")
            self.conversation_zone.insert(tk.END, f"Jarvis : {response_json['response']}\n")
        except requests.exceptions.RequestException:
            self.conversation_zone.insert(tk.END, "Jarvis hors ligne.\n")

if __name__ == "__main__":
    import pyinstaller
    pyinstaller.run([
        '--onefile',
        '--windowed',
        'gui/app.py'
    ])
