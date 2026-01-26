#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import threading
import requests
import os
from datetime import datetime

# ================= CONFIG (env vars with defaults) =================
SERIAL_PORT = os.getenv("MESHTASTIC_SERIAL_PORT")
AI_PREFIX = os.getenv("AI_PREFIX", "/AI")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

# Reliability settings
API_RETRIES = int(os.getenv("API_RETRIES", "3"))
API_RETRY_DELAY = int(os.getenv("API_RETRY_DELAY", "2"))
# ====================================================================

# ================= COLOR THEMES =================
THEMES = {
    "Classic": {
        "bg": "SystemButtonFace",
        "fg": "black",
        "text_bg": "white",
        "text_fg": "black",
        "ai_color": "blue",
        "tree_bg": "white",
        "tree_fg": "black",
    },
    "Matrix": {
        "bg": "black",
        "fg": "#00ff00",
        "text_bg": "black",
        "text_fg": "#00ff00",
        "ai_color": "#ff0000",
        "tree_bg": "black",
        "tree_fg": "#00ff00",
    },
}
# ================================================


class MeshtasticAIGui:
    def __init__(self, root):
        self.root = root
        self.root.title("Meshtastic AI Bot")
        self.root.geometry("800x750")

        self.interface = None
        self.running = False
        self.listener_thread = None
        self.nodes = {}  # Track discovered nodes
        self.node_update_pending = False  # Throttle node updates
        self.current_theme = "Classic"

        self._create_menu()
        self._create_status_bar()
        self._create_main_sections()

        # Subscribe to meshtastic events
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_node_update, "meshtastic.node.updated")

        # Apply default theme
        self._apply_theme("Classic")

    def _create_menu(self):
        """Create the menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Service menu
        service_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Service", menu=service_menu)
        service_menu.add_command(label="Start", command=self.start_service)
        service_menu.add_command(label="Stop", command=self.stop_service)
        service_menu.add_separator()
        service_menu.add_command(label="Exit", command=self.on_exit)

        # Theme menu
        theme_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Theme", menu=theme_menu)
        for theme_name in THEMES.keys():
            theme_menu.add_command(
                label=theme_name,
                command=lambda t=theme_name: self._apply_theme(t)
            )

    def _create_status_bar(self):
        """Create the status bar at the bottom."""
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)

        self.status_indicator = tk.Canvas(status_frame, width=20, height=20)
        self.status_indicator.pack(side=tk.LEFT, padx=5)
        self.status_circle = self.status_indicator.create_oval(
            2, 2, 18, 18, fill="red"
        )

        self.status_label = ttk.Label(status_frame, text="Stopped")
        self.status_label.pack(side=tk.LEFT)

    def _create_main_sections(self):
        """Create the four main sections."""
        # Main container with paned windows for resizable sections
        main_pane = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 0: Node List (top section)
        nodes_frame = ttk.LabelFrame(main_pane, text="Nodes")
        main_pane.add(nodes_frame, weight=1)

        # Create treeview for nodes with scrollbar
        node_container = ttk.Frame(nodes_frame)
        node_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollbar
        node_scrollbar = ttk.Scrollbar(node_container)
        node_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview with columns
        self.node_tree = ttk.Treeview(
            node_container,
            columns=("id", "name", "snr", "last_seen"),
            show="headings",
            height=6,
            yscrollcommand=node_scrollbar.set
        )
        self.node_tree.pack(fill=tk.BOTH, expand=True)
        node_scrollbar.config(command=self.node_tree.yview)

        # Define columns
        self.node_tree.heading("id", text="Node ID")
        self.node_tree.heading("name", text="Name")
        self.node_tree.heading("snr", text="SNR")
        self.node_tree.heading("last_seen", text="Last Seen")

        self.node_tree.column("id", width=100)
        self.node_tree.column("name", width=150)
        self.node_tree.column("snr", width=60)
        self.node_tree.column("last_seen", width=100)

        # Section 1: Messages Received
        received_frame = ttk.LabelFrame(main_pane, text="Messages Received")
        main_pane.add(received_frame, weight=1)

        self.received_text = scrolledtext.ScrolledText(
            received_frame, height=8, state=tk.DISABLED
        )
        self.received_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 2: Replies Sent
        replies_frame = ttk.LabelFrame(main_pane, text="Replies Sent")
        main_pane.add(replies_frame, weight=1)

        self.replies_text = scrolledtext.ScrolledText(
            replies_frame, height=8, state=tk.DISABLED
        )
        self.replies_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 3: Send Message
        send_frame = ttk.LabelFrame(main_pane, text="Send Message")
        main_pane.add(send_frame, weight=1)

        # Channel selection
        channel_frame = ttk.Frame(send_frame)
        channel_frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(channel_frame, text="Channel:").pack(side=tk.LEFT)
        self.channel_var = tk.StringVar(value="0")
        self.channel_spinbox = ttk.Spinbox(
            channel_frame, from_=0, to=7, width=5,
            textvariable=self.channel_var
        )
        self.channel_spinbox.pack(side=tk.LEFT, padx=5)

        # Message input
        self.message_text = scrolledtext.ScrolledText(send_frame, height=4)
        self.message_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Send button
        self.send_button = ttk.Button(
            send_frame, text="Send Message", command=self.send_message
        )
        self.send_button.pack(pady=5)

    def _log_received(self, message):
        """Add a message to the received section."""
        self.root.after(0, self._append_to_text, self.received_text, message)

    def _log_reply(self, message, is_ai=False):
        """Add a message to the replies section."""
        self.root.after(
            0, self._append_to_text, self.replies_text, message, is_ai
        )

    def _append_to_text(self, text_widget, message, is_ai=False):
        """Thread-safe append to a text widget."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        text_widget.config(state=tk.NORMAL)
        # Get line count before insert (END includes trailing newline)
        start_idx = text_widget.index("end-1c linestart")
        text_widget.insert(tk.END, f"[{timestamp}] {message}\n")
        if is_ai:
            end_idx = text_widget.index("end-1c")
            text_widget.tag_add("ai_response", start_idx, end_idx)
        text_widget.see(tk.END)
        text_widget.config(state=tk.DISABLED)

    def _update_status(self, running):
        """Update the status indicator."""
        self.running = running
        if running:
            self.status_indicator.itemconfig(self.status_circle, fill="green")
            self.status_label.config(text="Listening")
        else:
            self.status_indicator.itemconfig(self.status_circle, fill="red")
            self.status_label.config(text="Stopped")

    def _apply_theme(self, theme_name):
        """Apply a color theme to the application."""
        if theme_name not in THEMES:
            return
        self.current_theme = theme_name
        theme = THEMES[theme_name]

        # Root window
        self.root.configure(bg=theme["bg"])

        # Text widgets
        for text_widget in [
            self.received_text, self.replies_text, self.message_text
        ]:
            text_widget.config(
                bg=theme["text_bg"],
                fg=theme["text_fg"],
                insertbackground=theme["text_fg"]
            )
            # Configure AI response tag
            text_widget.tag_configure(
                "ai_response", foreground=theme["ai_color"]
            )

        # Treeview styling
        style = ttk.Style()
        style.configure(
            "Treeview",
            background=theme["tree_bg"],
            foreground=theme["tree_fg"],
            fieldbackground=theme["tree_bg"]
        )
        style.map("Treeview", background=[("selected", "#0078d7")])

        # Status indicator background
        self.status_indicator.configure(bg=theme["bg"])

    def _on_node_update(self, node, interface):
        """Handle node updates from meshtastic."""
        # Throttle updates to prevent crashes
        if not self.node_update_pending:
            self.node_update_pending = True
            self.root.after(500, self._do_node_update)

    def _do_node_update(self):
        """Actually perform the node list update."""
        self.node_update_pending = False
        self._update_node_list()

    def _update_node_list(self):
        """Refresh the node list from the interface."""
        if not self.interface or not self.running:
            return

        try:
            # Get nodes from interface
            nodes = self.interface.nodes
            if not nodes:
                return

            # Get current items
            existing = set(self.node_tree.get_children())

            # Clear and repopulate
            for item in existing:
                self.node_tree.delete(item)

            for node_id, node_info in nodes.items():
                user = node_info.get("user", {})
                long_name = user.get("longName")
                short_name = user.get("shortName")
                name = long_name or short_name or "Unknown"
                snr = node_info.get("snr", "N/A")
                if snr != "N/A":
                    snr = f"{snr:.1f}" if isinstance(snr, float) else str(snr)
                last_heard = node_info.get("lastHeard")

                if last_heard:
                    dt = datetime.fromtimestamp(last_heard)
                    last_seen = dt.strftime("%H:%M:%S")
                else:
                    last_seen = "N/A"

                self.node_tree.insert(
                    "", tk.END, values=(node_id, name, snr, last_seen)
                )
        except Exception as e:
            print(f"Node update error: {e}")

    def _on_receive(self, packet, interface):
        """Handle received messages."""
        if "decoded" not in packet:
            return

        decoded = packet["decoded"]
        if decoded.get("portnum") != "TEXT_MESSAGE_APP":
            return

        text = decoded.get("text", "").strip()
        if not text:
            return

        from_id = packet.get("fromId", "unknown")
        channel = packet.get("channel", 0)

        self._log_received(f"From {from_id} (ch {channel}): {text}")

        # Check if it's an AI query
        if text.upper().startswith(AI_PREFIX.upper()):
            question = text[len(AI_PREFIX):].strip()
            if question:
                # Process in a thread to not block UI
                threading.Thread(
                    target=self._process_ai_query,
                    args=(question, from_id, channel, interface),
                    daemon=True
                ).start()

    def _process_ai_query(self, question, from_id, channel, interface):
        """Process an AI query and send response."""
        answer = self._query_ollama(question)

        # Truncate safely
        max_bytes = 200
        reply = f"@{from_id} {answer}"
        if len(reply.encode('utf-8')) > max_bytes:
            reply = f"@{from_id} {answer[:100]}..."

        try:
            interface.sendText(text=reply, channelIndex=channel)
            msg = f"AI to {from_id} (ch {channel}): {reply}"
            self._log_reply(msg, is_ai=True)
        except Exception as e:
            self._log_reply(f"FAILED to {from_id}: {e}")

    def _query_ollama(self, question):
        """Query Ollama API with retry logic."""
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")
        current_day = now.strftime("%A")
        system_context = f"Date and time: {current_day}, {current_time}."

        last_error = None
        for attempt in range(API_RETRIES):
            try:
                response = requests.post(
                    OLLAMA_URL,
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": (
                            f"{system_context} Answer concisely "
                            f"in under 120 chars: {question}"
                        ),
                        "stream": False,
                        "options": {"temperature": 0.7}
                    },
                    timeout=90
                )
                response.raise_for_status()
                result = response.json().get("response", "").strip()
                return result or "No response."
            except Exception as e:
                last_error = e
                if attempt < API_RETRIES - 1:
                    import time
                    time.sleep(API_RETRY_DELAY)
        return f"Error: {str(last_error)[:60]}"

    def start_service(self):
        """Start the Meshtastic listener service."""
        if self.running:
            messagebox.showinfo("Info", "Service is already running")
            return

        try:
            self.interface = meshtastic.serial_interface.SerialInterface(
                devPath=SERIAL_PORT
            )
            self._update_status(True)
            self._log_received("Service started - Connected to Meshtastic")
            # Load initial node list
            self.root.after(1000, self._update_node_list)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect: {e}")
            self._update_status(False)

    def stop_service(self):
        """Stop the Meshtastic listener service."""
        if not self.running:
            messagebox.showinfo("Info", "Service is not running")
            return

        try:
            if self.interface:
                self.interface.close()
                self.interface = None
            self._update_status(False)
            self._log_received("Service stopped")
            # Clear node list
            for item in self.node_tree.get_children():
                self.node_tree.delete(item)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop: {e}")

    def send_message(self):
        """Send a message to the mesh network."""
        if not self.running or not self.interface:
            messagebox.showwarning(
                "Warning", "Service is not running. Start it first."
            )
            return

        message = self.message_text.get("1.0", tk.END).strip()
        if not message:
            messagebox.showwarning("Warning", "Please enter a message")
            return

        try:
            channel = int(self.channel_var.get())
            self.interface.sendText(text=message, channelIndex=channel)
            self._log_reply(f"Sent (ch {channel}): {message}")
            self.message_text.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send: {e}")

    def on_exit(self):
        """Handle application exit."""
        if self.running:
            self.stop_service()
        self.root.quit()


def main():
    root = tk.Tk()
    app = MeshtasticAIGui(root)
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
