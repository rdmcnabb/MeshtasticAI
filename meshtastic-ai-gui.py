#!/usr/bin/env python3
import sys
import os

# ================= CHECK FOR REQUIRED LIBRARIES =================
# This section checks if all required libraries are installed
# before the program tries to use them.

missing_libraries = []

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except ImportError:
    missing_libraries.append(("tkinter", "python3-tk"))

try:
    import meshtastic
    import meshtastic.serial_interface
except ImportError:
    missing_libraries.append(("meshtastic", "meshtastic"))

try:
    from pubsub import pub
except ImportError:
    missing_libraries.append(("pubsub", "pypubsub"))

try:
    import requests
except ImportError:
    missing_libraries.append(("requests", "requests"))

if missing_libraries:
    print("\n" + "=" * 60)
    print("  MISSING REQUIRED LIBRARIES")
    print("=" * 60)
    print("\nThis program needs some additional libraries to run.")
    print("Don't worry - they're easy to install!\n")
    print("Missing libraries:")
    for name, package in missing_libraries:
        print(f"  - {name}")
    print("\n" + "-" * 60)
    print("HOW TO INSTALL:")
    print("-" * 60)

    # Get just the pip package names (excluding tkinter which is special)
    pip_packages = [pkg for name, pkg in missing_libraries if pkg != "python3-tk"]
    has_tkinter_missing = any(pkg == "python3-tk" for _, pkg in missing_libraries)

    if pip_packages:
        print("\nStep 1: Open a terminal and run this command:\n")
        print(f"    pip install {' '.join(pip_packages)}")
        print("\n    Or if that doesn't work, try:")
        print(f"    pip3 install {' '.join(pip_packages)}")
        print(f"\n    Or on some systems:")
        print(f"    python3 -m pip install {' '.join(pip_packages)}")

    if has_tkinter_missing:
        print("\nFor tkinter (the graphical interface library):")
        print("\n  On Ubuntu/Debian Linux:")
        print("    sudo apt install python3-tk")
        print("\n  On Fedora Linux:")
        print("    sudo dnf install python3-tkinter")
        print("\n  On macOS (with Homebrew):")
        print("    brew install python-tk")

    print("\n" + "-" * 60)
    print("After installing, run this program again!")
    print("=" * 60 + "\n")
    sys.exit(1)

# ================================================================

# Standard library imports (these come with Python)
import threading
import json
import glob
import time
from datetime import datetime

# ================= CONSTANTS =================
MAX_MESSAGE_BYTES = 200  # Meshtastic message size limit
OLLAMA_TIMEOUT = 90  # Seconds to wait for AI response
NODE_REFRESH_INTERVAL = 30000  # Milliseconds between node list refreshes

# ================= CONFIG FILE =================
CONFIG_FILE = os.path.expanduser("~/.meshtastic-ai-config.json")

DEFAULT_CONFIG = {
    "serial_port": "",  # Empty = auto-detect
    "ai_enabled": True,  # Enable/disable AI features
    "ai_prefix": "/AI",
    "ollama_url": "http://127.0.0.1:11434/api/generate",
    "ollama_model": "llama3.1",
    "api_retries": 3,
    "api_retry_delay": 2,
    "default_channel": 1,
}


def load_config():
    """Load configuration from file or return defaults."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                # Merge with defaults for any missing keys
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception as e:
            print(f"Warning: Failed to load config from {CONFIG_FILE}: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False


def detect_serial_ports():
    """Detect available serial ports."""
    ports = []
    # Common patterns for Meshtastic devices
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbserial*", "/dev/cu.usbmodem*"]
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    return sorted(ports)
# ===============================================

# ================= COLOR THEMES =================
THEMES = {
    "Classic": {
        "bg": "#d9d9d9",
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

        # Load configuration
        self.config = load_config()

        self.interface = None
        self.running = False
        self.listener_thread = None
        self.nodes = {}  # Track discovered nodes
        self.node_update_pending = False  # Throttle node updates
        self.current_theme = "Classic"
        self.refresh_timer_id = None
        self.refresh_interval = NODE_REFRESH_INTERVAL
        self.selected_node_id = None  # Selected node for DM
        self.session_start_time = None  # Track service session start
        self.session_timer_id = None  # Timer for updating session display

        self._create_menu()
        self._create_status_bar()
        self._create_main_sections()

        # Subscribe to meshtastic events
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_node_update, "meshtastic.node.updated")

        # Apply default theme
        self._apply_theme("Classic")

        # Check Ollama connection on startup (after window appears)
        self.root.after(500, self._check_ollama_connection)

    def _start_session_timer(self):
        """Start the session timer."""
        self.session_start_time = time.time()
        self._update_session_timer()

    def _stop_session_timer(self):
        """Stop the session timer and reset display."""
        if self.session_timer_id:
            self.root.after_cancel(self.session_timer_id)
            self.session_timer_id = None
        self.session_start_time = None
        self.session_timer_label.config(text="Session: --:--:--")

    def _update_session_timer(self):
        """Update the session timer display."""
        if self.session_start_time is None:
            return
        elapsed = int(time.time() - self.session_start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.session_timer_label.config(text=f"Session: {hours:02d}:{minutes:02d}:{seconds:02d}")
        # Update every second
        self.session_timer_id = self.root.after(1000, self._update_session_timer)

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

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(
            label="Refresh Nodes", command=self._refresh_nodes
        )
        tools_menu.add_separator()
        tools_menu.add_command(label="Settings", command=self._open_settings)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self._show_about)

    def _show_about(self):
        """Show the About dialog."""
        about_text = (
            "Meshtastic AI Bot\n\n"
            "A GUI for Meshtastic mesh networking\n"
            "with Ollama AI integration.\n\n"
            "Developed by Ronald D. McNabb\n"
            "with Claude Opus 4.5 (Anthropic)\n"
            "and Grok 4 (xAI)\n\n"
            "Powered by Meshtastic and Ollama"
        )
        messagebox.showinfo("About", about_text)

    def _create_status_bar(self):
        """Create the status bar at the bottom."""
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        # Meshtastic connection status
        ttk.Label(status_frame, text="Radio:").pack(side=tk.LEFT)

        self.status_indicator = tk.Canvas(status_frame, width=20, height=20)
        self.status_indicator.pack(side=tk.LEFT, padx=5)
        self.status_circle = self.status_indicator.create_oval(
            2, 2, 18, 18, fill="red"
        )

        self.status_label = ttk.Label(status_frame, text="Stopped")
        self.status_label.pack(side=tk.LEFT)

        # Separator
        ttk.Label(status_frame, text="  |  ").pack(side=tk.LEFT)

        # AI service status
        ttk.Label(status_frame, text="AI:").pack(side=tk.LEFT)

        self.ai_status_indicator = tk.Canvas(status_frame, width=20, height=20)
        self.ai_status_indicator.pack(side=tk.LEFT, padx=5)
        self.ai_status_circle = self.ai_status_indicator.create_oval(
            2, 2, 18, 18, fill="red"
        )

        self.ai_status_label = ttk.Label(status_frame, text="Not connected")
        self.ai_status_label.pack(side=tk.LEFT)

        # Separator
        ttk.Label(status_frame, text="  |  ").pack(side=tk.LEFT)

        # Session timer (on the right side)
        self.session_timer_label = ttk.Label(status_frame, text="Session: --:--:--")
        self.session_timer_label.pack(side=tk.RIGHT, padx=5)

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

        # Bind selection event
        self.node_tree.bind("<<TreeviewSelect>>", self._on_node_select)

        # Section 1: Messages Received
        received_frame = ttk.LabelFrame(main_pane, text="Messages Received")
        main_pane.add(received_frame, weight=1)

        self.received_text = scrolledtext.ScrolledText(
            received_frame, height=8, state=tk.DISABLED
        )
        self.received_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 2: Messages Sent
        replies_frame = ttk.LabelFrame(main_pane, text="Messages Sent")
        main_pane.add(replies_frame, weight=1)

        self.replies_text = scrolledtext.ScrolledText(
            replies_frame, height=8, state=tk.DISABLED
        )
        self.replies_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 3: Send Message
        send_frame = ttk.LabelFrame(main_pane, text="Send Message")
        main_pane.add(send_frame, weight=1)

        # Destination selection (node from list)
        dest_frame = ttk.Frame(send_frame)
        dest_frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(dest_frame, text="To:").pack(side=tk.LEFT)
        self.dest_label = ttk.Label(dest_frame, text="All (Broadcast)")
        self.dest_label.pack(side=tk.LEFT, padx=5)
        self.clear_dest_button = ttk.Button(
            dest_frame, text="Clear", command=self._clear_node_selection, width=6
        )
        self.clear_dest_button.pack(side=tk.LEFT, padx=5)

        # Channel selection
        channel_frame = ttk.Frame(send_frame)
        channel_frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(channel_frame, text="Channel:").pack(side=tk.LEFT)
        self.channel_var = tk.StringVar(value=str(self.config.get("default_channel", 1)))
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

    def _update_status(self, running, port=None):
        """Update the status indicator."""
        self.running = running
        if running:
            self.status_indicator.itemconfig(self.status_circle, fill="green")
            if port:
                self.status_label.config(text=f"Listening on port: {port}")
            else:
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

        # Status indicator backgrounds
        self.status_indicator.configure(bg=theme["bg"])
        self.ai_status_indicator.configure(bg=theme["bg"])

    def _update_ai_status(self, connected, message=None):
        """Update the AI status indicator."""
        if connected:
            self.ai_status_indicator.itemconfig(self.ai_status_circle, fill="green")
            self.ai_status_label.config(text=message or "Ready")
        else:
            self.ai_status_indicator.itemconfig(self.ai_status_circle, fill="red")
            self.ai_status_label.config(text=message or "Not connected")

    def _check_ollama_connection(self):
        """Check if Ollama AI service is reachable (non-blocking)."""
        # Check if AI is disabled
        if not self.config.get("ai_enabled", True):
            self._update_ai_status(False, "Disabled")
            return False

        ollama_url = self.config.get("ollama_url", DEFAULT_CONFIG["ollama_url"])
        ollama_model = self.config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])

        # Try to connect to Ollama (just check if server responds)
        try:
            # Use a short timeout for the check - just see if server is there
            # Try the base URL (remove /api/generate to get base)
            base_url = ollama_url.rsplit('/api/', 1)[0]
            response = requests.get(base_url, timeout=5)
            # If we get here, Ollama is running
            self._update_ai_status(True, f"Ready ({ollama_model})")
            return True
        except requests.exceptions.ConnectionError:
            self._update_ai_status(False, "Cannot connect")
        except requests.exceptions.Timeout:
            self._update_ai_status(False, "Timed out")
        except Exception as e:
            self._update_ai_status(False, "Error")

        # Silent failure - just update status indicator, don't block user
        return False

    def _on_node_select(self, event):
        """Handle node selection from treeview."""
        selection = self.node_tree.selection()
        if selection:
            item = selection[0]
            values = self.node_tree.item(item, "values")
            if values:
                node_id = values[0]
                node_name = values[1]
                self.selected_node_id = node_id
                self.dest_label.config(text=f"{node_name} ({node_id})")
        else:
            self._clear_node_selection()

    def _clear_node_selection(self):
        """Clear node selection and return to broadcast mode."""
        self.selected_node_id = None
        self.dest_label.config(text="All (Broadcast)")
        # Clear treeview selection
        for item in self.node_tree.selection():
            self.node_tree.selection_remove(item)

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

                # Use node_id as item id for easy reselection
                self.node_tree.insert(
                    "", tk.END, iid=node_id, values=(node_id, name, snr, last_seen)
                )

            # Restore selection if we had one
            if self.selected_node_id and self.node_tree.exists(self.selected_node_id):
                self.node_tree.selection_set(self.selected_node_id)
        except Exception as e:
            print(f"Node update error: {e}")

    def _refresh_nodes(self):
        """Clear and refresh the node list."""
        if not self.interface or not self.running:
            return

        # Clear existing nodes from treeview
        for item in self.node_tree.get_children():
            self.node_tree.delete(item)

        # Brief delay so user sees the clear, then repopulate
        self.root.after(500, self._update_node_list)

    def _start_refresh_timer(self):
        """Start the automatic node refresh timer."""
        self._stop_refresh_timer()
        self.refresh_timer_id = self.root.after(
            self.refresh_interval, self._on_refresh_timer
        )

    def _stop_refresh_timer(self):
        """Stop the automatic node refresh timer."""
        if self.refresh_timer_id:
            self.root.after_cancel(self.refresh_timer_id)
            self.refresh_timer_id = None

    def _on_refresh_timer(self):
        """Handle refresh timer tick."""
        if self.running:
            self._update_node_list()
            self._start_refresh_timer()

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

        # Check if it's an AI query (only if AI is enabled)
        if self.config.get("ai_enabled", True):
            ai_prefix = self.config.get("ai_prefix", "/AI")
            if text.upper().startswith(ai_prefix.upper()):
                question = text[len(ai_prefix):].strip()
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
        reply = f"@{from_id} {answer}"
        if len(reply.encode('utf-8')) > MAX_MESSAGE_BYTES:
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

        api_retries = self.config.get("api_retries", 3)
        api_retry_delay = self.config.get("api_retry_delay", 2)
        ollama_url = self.config.get("ollama_url", DEFAULT_CONFIG["ollama_url"])
        ollama_model = self.config.get("ollama_model", DEFAULT_CONFIG["ollama_model"])

        last_error = None
        for attempt in range(api_retries):
            try:
                response = requests.post(
                    ollama_url,
                    json={
                        "model": ollama_model,
                        "prompt": (
                            f"{system_context} Answer concisely "
                            f"in under 120 chars: {question}"
                        ),
                        "stream": False,
                        "options": {"temperature": 0.7}
                    },
                    timeout=OLLAMA_TIMEOUT
                )
                response.raise_for_status()
                result = response.json().get("response", "").strip()
                return result or "No response."
            except requests.exceptions.ConnectionError:
                last_error = "connection_error"
                if attempt < api_retries - 1:
                    time.sleep(api_retry_delay)
            except requests.exceptions.Timeout:
                last_error = "timeout"
                if attempt < api_retries - 1:
                    time.sleep(api_retry_delay)
            except requests.exceptions.HTTPError as e:
                # Check if it's a model not found error (404)
                if e.response is not None and e.response.status_code == 404:
                    return f"AI Error: Model '{ollama_model}' not found. Check Settings."
                last_error = f"http_error:{e}"
                if attempt < api_retries - 1:
                    time.sleep(api_retry_delay)
            except Exception as e:
                last_error = str(e)
                if attempt < api_retries - 1:
                    time.sleep(api_retry_delay)

        # Return user-friendly error messages
        if last_error == "connection_error":
            return f"AI Error: Cannot connect to Ollama. Is it running? ({ollama_url})"
        elif last_error == "timeout":
            return "AI Error: Ollama took too long to respond. Try again."
        elif isinstance(last_error, str) and last_error.startswith("http_error:"):
            return f"AI Error: {last_error[11:][:50]}"
        else:
            return f"AI Error: {str(last_error)[:50]}"

    def _open_settings(self):
        """Open the settings dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("550x460")
        dialog.transient(self.root)
        dialog.grab_set()

        # Create form
        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0

        # Serial Port
        ttk.Label(frame, text="Serial Port:").grid(row=row, column=0, sticky="w", pady=5)
        port_frame = ttk.Frame(frame)
        port_frame.grid(row=row, column=1, sticky="ew", pady=5)

        port_var = tk.StringVar()
        port_combo = ttk.Combobox(port_frame, textvariable=port_var, width=20)
        port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def refresh_ports():
            ports = detect_serial_ports()
            port_combo["values"] = ["(Auto-detect)"] + ports

            # Get currently configured port
            configured_port = self.config.get("serial_port", "")

            # Set the displayed value
            if configured_port and configured_port in ports:
                # Use the configured port if it exists
                port_var.set(configured_port)
            elif ports:
                # Default to first detected port (usually /dev/ttyUSB0 - most stable)
                port_var.set(ports[0])
            else:
                # No ports detected, show auto-detect
                port_var.set("(Auto-detect)")

        refresh_ports()

        ttk.Button(port_frame, text="Refresh", command=refresh_ports, width=7).pack(side=tk.LEFT, padx=2)

        # Port test button and status light
        port_status_canvas = tk.Canvas(port_frame, width=16, height=16)
        port_status_canvas.pack(side=tk.LEFT, padx=5)
        port_status_circle = port_status_canvas.create_oval(2, 2, 14, 14, fill="gray")

        def test_port():
            port_value = port_var.get()
            if port_value == "(Auto-detect)":
                port_value = None

            port_status_canvas.itemconfig(port_status_circle, fill="yellow")
            dialog.update()

            # Check if service is already running on this port
            if self.running and self.interface:
                current_port = getattr(self.interface, 'devPath', None)
                # If testing the same port that's already active, show green
                if port_value is None or port_value == current_port:
                    port_status_canvas.itemconfig(port_status_circle, fill="green")
                    return

            try:
                test_interface = meshtastic.serial_interface.SerialInterface(devPath=port_value)
                test_interface.close()
                port_status_canvas.itemconfig(port_status_circle, fill="green")
            except Exception as e:
                # Check if error is because port is already in use by our service
                if self.running and ("busy" in str(e).lower() or "in use" in str(e).lower()):
                    port_status_canvas.itemconfig(port_status_circle, fill="green")
                else:
                    port_status_canvas.itemconfig(port_status_circle, fill="red")
                    messagebox.showerror("Port Test Failed", f"Could not connect to port:\n{e}")

        ttk.Button(port_frame, text="Test", command=test_port, width=5).pack(side=tk.LEFT, padx=2)

        row += 1

        # AI Enabled checkbox
        ttk.Label(frame, text="AI Features:").grid(row=row, column=0, sticky="w", pady=5)
        ai_enabled_var = tk.BooleanVar(value=self.config.get("ai_enabled", True))
        ttk.Checkbutton(frame, text="Enable AI responses", variable=ai_enabled_var).grid(row=row, column=1, sticky="w", pady=5)

        row += 1

        # Ollama URL
        ttk.Label(frame, text="Ollama URL:").grid(row=row, column=0, sticky="w", pady=5)
        url_var = tk.StringVar(value=self.config.get("ollama_url", DEFAULT_CONFIG["ollama_url"]))
        ttk.Entry(frame, textvariable=url_var, width=40).grid(row=row, column=1, sticky="ew", pady=5)

        row += 1

        # Ollama Model
        ttk.Label(frame, text="Ollama Model:").grid(row=row, column=0, sticky="w", pady=5)
        model_frame = ttk.Frame(frame)
        model_frame.grid(row=row, column=1, sticky="ew", pady=5)

        model_var = tk.StringVar(value=self.config.get("ollama_model", DEFAULT_CONFIG["ollama_model"]))
        ttk.Entry(model_frame, textvariable=model_var, width=20).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # AI test button and status light
        ai_status_canvas = tk.Canvas(model_frame, width=16, height=16)
        ai_status_canvas.pack(side=tk.LEFT, padx=5)
        ai_status_circle = ai_status_canvas.create_oval(2, 2, 14, 14, fill="gray")

        def test_ai():
            url = url_var.get()
            model = model_var.get()

            ai_status_canvas.itemconfig(ai_status_circle, fill="yellow")
            dialog.update()

            try:
                # Test connection to Ollama
                base_url = url.rsplit('/api/', 1)[0]
                response = requests.get(base_url, timeout=5)

                # Try a simple query to verify model works
                test_response = requests.post(
                    url,
                    json={
                        "model": model,
                        "prompt": "Say hi",
                        "stream": False,
                        "options": {"num_predict": 5}
                    },
                    timeout=30
                )
                test_response.raise_for_status()

                ai_status_canvas.itemconfig(ai_status_circle, fill="green")
                # Also update main window AI status
                self._update_ai_status(True, f"Ready ({model})")
            except requests.exceptions.ConnectionError:
                ai_status_canvas.itemconfig(ai_status_circle, fill="red")
                messagebox.showerror("AI Test Failed", f"Cannot connect to Ollama.\n\nIs it running at {url}?")
            except requests.exceptions.HTTPError as e:
                ai_status_canvas.itemconfig(ai_status_circle, fill="red")
                if e.response is not None and e.response.status_code == 404:
                    messagebox.showerror("AI Test Failed", f"Model '{model}' not found.\n\nCheck the model name.")
                else:
                    messagebox.showerror("AI Test Failed", f"HTTP Error: {e}")
            except Exception as e:
                ai_status_canvas.itemconfig(ai_status_circle, fill="red")
                messagebox.showerror("AI Test Failed", f"Error: {e}")

        ttk.Button(model_frame, text="Test AI", command=test_ai, width=7).pack(side=tk.LEFT, padx=2)

        row += 1

        # AI Prefix
        ttk.Label(frame, text="AI Prefix:").grid(row=row, column=0, sticky="w", pady=5)
        prefix_var = tk.StringVar(value=self.config.get("ai_prefix", DEFAULT_CONFIG["ai_prefix"]))
        ttk.Entry(frame, textvariable=prefix_var, width=40).grid(row=row, column=1, sticky="ew", pady=5)

        row += 1

        # Default Channel
        ttk.Label(frame, text="Default Channel:").grid(row=row, column=0, sticky="w", pady=5)
        channel_var = tk.StringVar(value=str(self.config.get("default_channel", 1)))
        ttk.Spinbox(frame, from_=0, to=7, textvariable=channel_var, width=5).grid(row=row, column=1, sticky="w", pady=5)

        row += 1

        # API Retries
        ttk.Label(frame, text="API Retries:").grid(row=row, column=0, sticky="w", pady=5)
        retries_var = tk.StringVar(value=str(self.config.get("api_retries", 3)))
        ttk.Spinbox(frame, from_=1, to=10, textvariable=retries_var, width=5).grid(row=row, column=1, sticky="w", pady=5)

        row += 1

        frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def save_settings():
            port_value = port_var.get()
            if port_value == "(Auto-detect)":
                port_value = ""

            self.config["serial_port"] = port_value
            self.config["ai_enabled"] = ai_enabled_var.get()
            self.config["ollama_url"] = url_var.get()
            self.config["ollama_model"] = model_var.get()
            self.config["ai_prefix"] = prefix_var.get()
            self.config["default_channel"] = int(channel_var.get())
            self.config["api_retries"] = int(retries_var.get())

            if save_config(self.config):
                # Update main window AI status after saving
                self._check_ollama_connection()
                messagebox.showinfo("Settings", "Settings saved successfully!")
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to save settings")

        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def start_service(self):
        """Start the Meshtastic listener service."""
        if self.running:
            messagebox.showinfo("Info", "Service is already running")
            return

        try:
            serial_port = self.config.get("serial_port", "")
            # Empty string means auto-detect
            dev_path = serial_port if serial_port else None
            self.interface = meshtastic.serial_interface.SerialInterface(
                devPath=dev_path
            )
            # Get the actual port used (from config or auto-detected)
            actual_port = self.interface.devPath if hasattr(self.interface, 'devPath') else dev_path
            self._update_status(True, actual_port)
            self._log_received(f"Service started - Connected to Meshtastic on {actual_port}")
            # Clear and refresh node list
            self.root.after(1000, self._refresh_nodes)
            # Start refresh timer
            self._start_refresh_timer()
            # Start session timer
            self._start_session_timer()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect: {e}")
            self._update_status(False)

    def stop_service(self):
        """Stop the Meshtastic listener service."""
        if not self.running:
            messagebox.showinfo("Info", "Service is not running")
            return

        # Stop refresh timer
        self._stop_refresh_timer()
        # Stop session timer
        self._stop_session_timer()

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
            # Get our own node ID
            my_info = self.interface.getMyNodeInfo()
            my_id = my_info.get("user", {}).get("id", "local") if my_info else "local"

            # Send to specific node or broadcast
            if self.selected_node_id:
                self.interface.sendText(
                    text=message,
                    channelIndex=channel,
                    destinationId=self.selected_node_id
                )
                dest_str = f"to {self.selected_node_id}"
            else:
                self.interface.sendText(text=message, channelIndex=channel)
                dest_str = "broadcast"

            self._log_reply(f"Sent {dest_str} (ch {channel}): {message}")
            # Also show in Messages Received so we see the full conversation
            self._log_received(f"From {my_id} {dest_str} (ch {channel}): {message}")
            self.message_text.delete("1.0", tk.END)

            # Check if local message is an AI query and process it (only if AI enabled)
            if self.config.get("ai_enabled", True):
                ai_prefix = self.config.get("ai_prefix", "/AI")
                if message.upper().startswith(ai_prefix.upper()):
                    question = message[len(ai_prefix):].strip()
                    if question:
                        threading.Thread(
                            target=self._process_ai_query,
                            args=(question, my_id, channel, self.interface),
                            daemon=True
                        ).start()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send: {e}")

    def on_exit(self):
        """Handle application exit."""
        if self.running:
            self.stop_service()
        # Unsubscribe from pubsub events
        pub.unsubscribe(self._on_receive, "meshtastic.receive")
        pub.unsubscribe(self._on_node_update, "meshtastic.node.updated")
        self.root.quit()


def main():
    root = tk.Tk()
    app = MeshtasticAIGui(root)
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()


if __name__ == "__main__":
    main()
