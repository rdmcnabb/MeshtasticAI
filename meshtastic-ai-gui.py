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
    import meshtastic.tcp_interface
    import meshtastic.ble_interface
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

try:
    import asyncio
    from bleak import BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

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
VERSION = "2.4.0"
MAX_MESSAGE_BYTES = 200  # Meshtastic message size limit
OLLAMA_TIMEOUT = 90  # Seconds to wait for AI response
NODE_REFRESH_INTERVAL = 30000  # Milliseconds between node list refreshes

# ================= CONFIG FILE =================
CONFIG_FILE = os.path.expanduser("~/.meshtastic-ai-config.json")

DEFAULT_CONFIG = {
    "connection_type": "serial",  # serial, tcp, or ble
    "serial_port": "",  # Empty = auto-detect
    "tcp_host": "",  # IP address or hostname for TCP connection
    "ble_address": "",  # Bluetooth device address
    "auto_start": True,  # Auto-start service on launch
    "ai_enabled": True,  # Enable/disable AI features
    "ai_prefix": "/AI",
    "ollama_url": "http://127.0.0.1:11434/api/generate",
    "ollama_model": "llama3.1",
    "api_retries": 3,
    "api_retry_delay": 2,
    "default_channel": 1,
    "window_geometry": "",  # Window size and position
    "theme": "Classic",  # Remember selected theme
    "font_size": 10,  # Font size for text areas
    "auto_reconnect": True,  # Auto-reconnect on disconnect
    "sound_notifications": True,  # Play sound on incoming messages
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
    "Dark": {
        "bg": "#2b2b2b",
        "fg": "#e0e0e0",
        "text_bg": "#1e1e1e",
        "text_fg": "#d4d4d4",
        "ai_color": "#569cd6",
        "tree_bg": "#1e1e1e",
        "tree_fg": "#d4d4d4",
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
    "Ocean": {
        "bg": "#1a3a4a",
        "fg": "#b8d4e3",
        "text_bg": "#0d2633",
        "text_fg": "#a8c8d8",
        "ai_color": "#4fc3f7",
        "tree_bg": "#0d2633",
        "tree_fg": "#a8c8d8",
    },
    "Amber": {
        "bg": "#2a2015",
        "fg": "#ffb300",
        "text_bg": "#1a1510",
        "text_fg": "#ffa000",
        "ai_color": "#ff6f00",
        "tree_bg": "#1a1510",
        "tree_fg": "#ffa000",
    },
}
# ================================================


class MeshtasticAIGui:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Meshtastic AI Bot v{VERSION}")

        # Load configuration first to get window geometry
        self.config = load_config()

        # Restore window geometry or use default
        saved_geometry = self.config.get("window_geometry", "")
        if saved_geometry:
            self.root.geometry(saved_geometry)
        else:
            self.root.geometry("800x750")

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
        self.connection_check_id = None  # Timer for connection health check
        self.messages_received = 0  # Count of received messages
        self.messages_sent = 0  # Count of sent messages
        self.mini_mode = False  # Track mini mode state
        self.normal_geometry = None  # Store normal window size

        self._create_menu()
        self._create_status_bar()
        self._create_main_sections()

        # Subscribe to meshtastic events
        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_node_update, "meshtastic.node.updated")

        # Apply saved theme or default
        saved_theme = self.config.get("theme", "Classic")
        self._apply_theme(saved_theme if saved_theme in THEMES else "Classic")

        # Apply saved font size
        self._apply_font_size(self.config.get("font_size", 10))

        # Check Ollama connection on startup (after window appears)
        self.root.after(500, self._check_ollama_connection)

        # Auto-start service if enabled
        if self.config.get("auto_start", True):
            self.root.after(1000, self.start_service)

        # Keyboard shortcuts
        self.root.bind("<Control-Return>", lambda e: self.send_message())
        self.root.bind("<Control-m>", lambda e: self._toggle_mini_mode())
        self.root.bind("<Escape>", lambda e: self._clear_message_input())

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

    def _update_message_counters(self):
        """Update the message counter display."""
        self.message_counter_label.config(
            text=f"Rx: {self.messages_received} | Tx: {self.messages_sent}"
        )

    def _show_counter_menu(self, event):
        """Show context menu for message counters."""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Reset Counters", command=self._reset_counters)
        menu.tk_popup(event.x_root, event.y_root)

    def _reset_counters(self):
        """Reset message counters to zero."""
        self.messages_received = 0
        self.messages_sent = 0
        self._update_message_counters()

    def _toggle_mini_mode(self):
        """Toggle between mini mode and normal mode."""
        if self.mini_mode:
            # Restore normal mode
            self.mini_mode = False
            if hasattr(self, 'mini_window') and self.mini_window:
                self.mini_window.destroy()
                self.mini_window = None
            self.root.deiconify()  # Show main window
        else:
            # Enter mini mode - create a small separate window
            self.mini_mode = True
            x = self.root.winfo_x()
            y = self.root.winfo_y()

            # Hide main window
            self.root.withdraw()

            # Create mini window
            self.mini_window = tk.Toplevel()
            self.mini_window.title("Mini")
            self.mini_window.geometry(f"320x30+{x}+{y}")
            self.mini_window.overrideredirect(True)  # No decorations
            self.mini_window.attributes('-topmost', True)

            # Create mini status bar
            mini_frame = ttk.Frame(self.mini_window)
            mini_frame.pack(fill=tk.BOTH, expand=True)

            # Radio status
            ttk.Label(mini_frame, text="Radio:").pack(side=tk.LEFT, padx=2)
            self.mini_radio_indicator = tk.Canvas(mini_frame, width=16, height=16)
            self.mini_radio_indicator.pack(side=tk.LEFT)
            radio_color = "green" if self.running else "red"
            self.mini_radio_circle = self.mini_radio_indicator.create_oval(2, 2, 14, 14, fill=radio_color)

            ttk.Label(mini_frame, text=" | AI:").pack(side=tk.LEFT)
            self.mini_ai_indicator = tk.Canvas(mini_frame, width=16, height=16)
            self.mini_ai_indicator.pack(side=tk.LEFT)
            ai_color = self.ai_status_indicator.itemcget(self.ai_status_circle, 'fill')
            self.mini_ai_circle = self.mini_ai_indicator.create_oval(2, 2, 14, 14, fill=ai_color)

            ttk.Label(mini_frame, text=" | ").pack(side=tk.LEFT)
            self.mini_counter_label = ttk.Label(mini_frame, text=f"Rx:{self.messages_received} Tx:{self.messages_sent}")
            self.mini_counter_label.pack(side=tk.LEFT)

            self.mini_session_label = ttk.Label(mini_frame, text="")
            self.mini_session_label.pack(side=tk.RIGHT, padx=5)
            self._update_mini_session()

            # Bind events for drag and click
            self._drag_start_x = 0
            self._drag_start_y = 0
            self._drag_moved = False

            mini_frame.bind("<Button-1>", self._mini_mode_click)
            mini_frame.bind("<B1-Motion>", self._mini_mode_drag)
            mini_frame.bind("<ButtonRelease-1>", self._mini_mode_release)

            # Handle window close
            self.mini_window.protocol("WM_DELETE_WINDOW", self._toggle_mini_mode)

    def _update_mini_session(self):
        """Update the mini mode session timer."""
        if not self.mini_mode or not hasattr(self, 'mini_window') or not self.mini_window:
            return
        if self.session_start_time:
            elapsed = int(time.time() - self.session_start_time)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.mini_session_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.mini_session_label.config(text="--:--:--")
        # Update mini counters too
        self.mini_counter_label.config(text=f"Rx:{self.messages_received} Tx:{self.messages_sent}")
        # Schedule next update
        if self.mini_mode:
            self.mini_window.after(1000, self._update_mini_session)

    def _mini_mode_click(self, event):
        """Handle click in mini mode - record position for drag detection."""
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_moved = False

    def _mini_mode_drag(self, event):
        """Handle drag in mini mode - move window."""
        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y
        if abs(dx) > 5 or abs(dy) > 5:
            self._drag_moved = True
            x = self.mini_window.winfo_x() + dx
            y = self.mini_window.winfo_y() + dy
            self.mini_window.geometry(f"+{x}+{y}")
            self._drag_start_x = event.x_root
            self._drag_start_y = event.y_root

    def _mini_mode_release(self, event):
        """Handle mouse release in mini mode - exit if it was a click, not drag."""
        if not self._drag_moved:
            self._toggle_mini_mode()

    def _create_menu(self):
        """Create the menu bar."""
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)

        # Service menu
        service_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Service", menu=service_menu)
        service_menu.add_command(label="Start", command=self.start_service)
        service_menu.add_command(label="Stop", command=self.stop_service)
        service_menu.add_separator()
        service_menu.add_command(label="Exit", command=self.on_exit)

        # Theme menu
        theme_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Theme", menu=theme_menu)
        for theme_name in THEMES.keys():
            theme_menu.add_command(
                label=theme_name,
                command=lambda t=theme_name: self._apply_theme(t)
            )

        # View menu
        view_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Mini Mode", command=self._toggle_mini_mode)

        # Tools menu
        tools_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(
            label="Refresh Nodes", command=self._refresh_nodes
        )
        tools_menu.add_separator()
        tools_menu.add_command(label="Radio Connection", command=self._open_radio_config)
        tools_menu.add_command(label="Settings", command=self._open_settings)

        # Help menu
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts", command=self._show_shortcuts)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)

    def _show_shortcuts(self):
        """Show the keyboard shortcuts dialog."""
        shortcuts_text = (
            "Keyboard Shortcuts\n"
            "─────────────────────\n\n"
            "Ctrl+Enter    Send message\n"
            "Ctrl+M        Toggle mini mode\n"
            "Escape        Clear message input\n\n"
            "Mouse Actions\n"
            "─────────────────────\n\n"
            "Right-click Rx/Tx    Reset counters\n"
            "Click node           Select for DM\n"
            "Double-click node    View node info"
        )
        messagebox.showinfo("Keyboard Shortcuts", shortcuts_text)

    def _show_about(self):
        """Show the About dialog."""
        about_text = (
            f"Meshtastic AI Bot v{VERSION}\n\n"
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
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        # Meshtastic connection status
        ttk.Label(self.status_frame, text="Radio:").pack(side=tk.LEFT)

        self.status_indicator = tk.Canvas(self.status_frame, width=20, height=20)
        self.status_indicator.pack(side=tk.LEFT, padx=5)
        self.status_circle = self.status_indicator.create_oval(
            2, 2, 18, 18, fill="red"
        )

        self.status_label = ttk.Label(self.status_frame, text="Stopped")
        self.status_label.pack(side=tk.LEFT)

        # Separator
        ttk.Label(self.status_frame, text="  |  ").pack(side=tk.LEFT)

        # AI service status
        ttk.Label(self.status_frame, text="AI:").pack(side=tk.LEFT)

        self.ai_status_indicator = tk.Canvas(self.status_frame, width=20, height=20)
        self.ai_status_indicator.pack(side=tk.LEFT, padx=5)
        self.ai_status_circle = self.ai_status_indicator.create_oval(
            2, 2, 18, 18, fill="red"
        )

        self.ai_status_label = ttk.Label(self.status_frame, text="Not connected")
        self.ai_status_label.pack(side=tk.LEFT)

        # Separator
        ttk.Label(self.status_frame, text="  |  ").pack(side=tk.LEFT)

        # Message counters
        self.message_counter_label = ttk.Label(self.status_frame, text="Rx: 0 | Tx: 0")
        self.message_counter_label.pack(side=tk.LEFT)
        # Right-click to reset counters
        self.message_counter_label.bind("<Button-3>", self._show_counter_menu)

        # Session timer (on the right side)
        self.session_timer_label = ttk.Label(self.status_frame, text="Session: --:--:--")
        self.session_timer_label.pack(side=tk.RIGHT, padx=5)

    def _create_main_sections(self):
        """Create the four main sections."""
        # Main container with paned windows for resizable sections
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 0: Node List (top section)
        nodes_frame = ttk.LabelFrame(self.main_pane, text="Nodes")
        self.main_pane.add(nodes_frame, weight=1)

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
        # Bind double-click to show node info
        self.node_tree.bind("<Double-1>", self._show_node_info)

        # Section 1: Messages Received
        received_frame = ttk.LabelFrame(self.main_pane, text="Messages Received")
        self.main_pane.add(received_frame, weight=1)

        self.received_text = scrolledtext.ScrolledText(
            received_frame, height=8, state=tk.DISABLED
        )
        self.received_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 2: Messages Sent
        replies_frame = ttk.LabelFrame(self.main_pane, text="Messages Sent")
        self.main_pane.add(replies_frame, weight=1)

        self.replies_text = scrolledtext.ScrolledText(
            replies_frame, height=8, state=tk.DISABLED
        )
        self.replies_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Section 3: Send Message
        send_frame = ttk.LabelFrame(self.main_pane, text="Send Message")
        self.main_pane.add(send_frame, weight=1)

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
                self.status_label.config(text=f"Connected: {port}")
            else:
                self.status_label.config(text="Connected")
        else:
            self.status_indicator.itemconfig(self.status_circle, fill="red")
            if port:
                self.status_label.config(text=port)  # Show "Connecting..." messages
            else:
                self.status_label.config(text="Stopped")
        # Force UI refresh
        self.root.update_idletasks()

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

    def _apply_font_size(self, size):
        """Apply font size to text widgets."""
        font = ("TkFixedFont", size)
        for text_widget in [
            self.received_text, self.replies_text, self.message_text
        ]:
            text_widget.config(font=font)

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

    def _show_node_info(self, event):
        """Show detailed information about a node on double-click."""
        selection = self.node_tree.selection()
        if not selection:
            return

        item = selection[0]
        values = self.node_tree.item(item, "values")
        if not values:
            return

        node_id = values[0]

        # Get full node info from interface
        if not self.interface or not self.running:
            messagebox.showinfo("Node Info", f"Node ID: {node_id}\n\nService not running.")
            return

        try:
            nodes = self.interface.nodes
            node_info = nodes.get(node_id, {})
        except Exception:
            node_info = {}

        if not node_info:
            messagebox.showinfo("Node Info", f"Node ID: {node_id}\n\nNo additional info available.")
            return

        # Build info string
        user = node_info.get("user", {})
        long_name = user.get("longName", "Unknown")
        short_name = user.get("shortName", "?")
        hw_model = user.get("hwModel", "Unknown")
        mac_addr = user.get("macaddr", "Unknown")

        snr = node_info.get("snr", "N/A")
        if snr != "N/A" and isinstance(snr, (int, float)):
            snr = f"{snr:.1f} dB"

        last_heard = node_info.get("lastHeard")
        if last_heard:
            last_heard_str = datetime.fromtimestamp(last_heard).strftime("%Y-%m-%d %H:%M:%S")
        else:
            last_heard_str = "Never"

        # Position info
        position = node_info.get("position", {})
        lat = position.get("latitude", "N/A")
        lon = position.get("longitude", "N/A")
        alt = position.get("altitude", "N/A")

        # Format values with padding for centered look
        def fmt(label, value, width=20):
            return f"  {label:<14}{str(value):<{width}}  "

        info_text = (
            f"{'Node Information':^40}\n"
            f"{'─' * 40}\n\n"
            f"{fmt('Node ID:', node_id)}\n"
            f"{fmt('Long Name:', long_name)}\n"
            f"{fmt('Short Name:', short_name)}\n"
            f"{fmt('Hardware:', hw_model)}\n"
            f"{fmt('MAC Address:', mac_addr)}\n\n"
            f"{fmt('Signal (SNR):', snr)}\n"
            f"{fmt('Last Heard:', last_heard_str)}\n\n"
            f"{'Position':^40}\n"
            f"{'─' * 40}\n"
            f"{fmt('Latitude:', lat)}\n"
            f"{fmt('Longitude:', lon)}\n"
            f"{fmt('Altitude:', alt)}\n"
        )

        messagebox.showinfo(f"Node: {short_name}", info_text)

    def _clear_message_input(self):
        """Clear the message input field."""
        self.message_text.delete("1.0", tk.END)

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

        # Update received counter
        self.messages_received += 1
        self.root.after(0, self._update_message_counters)

        # Play notification sound if enabled
        if self.config.get("sound_notifications", True):
            self.root.after(0, self.root.bell)

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
            # Also show in received area and update counters
            self._log_received(msg)
            self.messages_sent += 1
            self.messages_received += 1
            self.root.after(0, self._update_message_counters)
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

    def _open_radio_config(self):
        """Open the radio connection configuration dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Radio Connection")
        dialog.geometry("450x400")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(frame, text="Connection Type", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        # Connection type variable
        conn_type_var = tk.StringVar(value=self.config.get("connection_type", "serial"))

        # Radio buttons for connection type
        radio_frame = ttk.Frame(frame)
        radio_frame.grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Radiobutton(radio_frame, text="Serial (USB)", variable=conn_type_var,
                        value="serial", command=lambda: update_fields()).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(radio_frame, text="TCP (WiFi)", variable=conn_type_var,
                        value="tcp", command=lambda: update_fields()).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(radio_frame, text="Bluetooth (BLE)", variable=conn_type_var,
                        value="ble", command=lambda: update_fields()).pack(side=tk.LEFT)

        # Separator
        ttk.Separator(frame, orient="horizontal").grid(row=2, column=0, columnspan=2, sticky="ew", pady=15)

        # Dynamic settings frame
        settings_frame = ttk.Frame(frame)
        settings_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=5)

        # Variables for each connection type
        serial_port_var = tk.StringVar(value=self.config.get("serial_port", "") or "(Auto-detect)")
        tcp_host_var = tk.StringVar(value=self.config.get("tcp_host", ""))
        ble_address_var = tk.StringVar(value=self.config.get("ble_address", ""))

        # Widgets dict to track them
        widgets = {}

        def clear_settings_frame():
            for widget in settings_frame.winfo_children():
                widget.destroy()

        def update_fields():
            clear_settings_frame()
            conn_type = conn_type_var.get()

            if conn_type == "serial":
                ttk.Label(settings_frame, text="Serial Port:").grid(row=0, column=0, sticky="w", pady=5)
                # Get available ports
                ports = ["(Auto-detect)"]
                for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usbmodem*", "/dev/cu.usbserial*"]:
                    ports.extend(glob.glob(pattern))
                port_combo = ttk.Combobox(settings_frame, textvariable=serial_port_var, values=ports, width=30)
                port_combo.grid(row=0, column=1, sticky="w", pady=5, padx=5)
                widgets["serial_port"] = port_combo

                ttk.Label(settings_frame, text="Leave as Auto-detect to automatically\nfind the connected radio.",
                          foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

            elif conn_type == "tcp":
                ttk.Label(settings_frame, text="Host/IP Address:").grid(row=0, column=0, sticky="w", pady=5)
                host_entry = ttk.Entry(settings_frame, textvariable=tcp_host_var, width=30)
                host_entry.grid(row=0, column=1, sticky="w", pady=5, padx=5)
                widgets["tcp_host"] = host_entry

                ttk.Label(settings_frame, text="Enter the IP address of your radio.\nExample: 192.168.1.100",
                          foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

            elif conn_type == "ble":
                ttk.Label(settings_frame, text="BLE Address:").grid(row=0, column=0, sticky="w", pady=5)
                ble_entry = ttk.Entry(settings_frame, textvariable=ble_address_var, width=30)
                ble_entry.grid(row=0, column=1, sticky="w", pady=5, padx=5)
                widgets["ble_address"] = ble_entry

                ttk.Label(settings_frame, text="Enter the Bluetooth address or name.\nExample: AA:BB:CC:DD:EE:FF",
                          foreground="gray").grid(row=1, column=0, columnspan=2, sticky="w", pady=5)

                # Scan/Manage button
                def scan_ble():
                    if not BLEAK_AVAILABLE:
                        messagebox.showwarning("BLE Scan", "BLE scanning requires the 'bleak' library.\nInstall with: pip install bleak")
                        return

                    # Create BLE management dialog
                    scan_dialog = tk.Toplevel(dialog)
                    scan_dialog.title("BLE Device Manager")
                    scan_dialog.geometry("500x450")
                    scan_dialog.transient(dialog)
                    scan_dialog.grab_set()

                    main_frame = ttk.Frame(scan_dialog, padding=10)
                    main_frame.pack(fill=tk.BOTH, expand=True)

                    # Store devices
                    paired_devices = []
                    scanned_devices = []

                    # === PAIRED DEVICES SECTION ===
                    ttk.Label(main_frame, text="Paired Devices", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

                    paired_frame = ttk.Frame(main_frame)
                    paired_frame.pack(fill=tk.X, pady=5)

                    paired_listbox = tk.Listbox(paired_frame, height=5, font=("TkFixedFont", 9))
                    paired_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                    paired_scroll = ttk.Scrollbar(paired_frame, orient=tk.VERTICAL, command=paired_listbox.yview)
                    paired_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                    paired_listbox.config(yscrollcommand=paired_scroll.set)

                    def get_paired_devices():
                        """Get list of paired Bluetooth devices using bluetoothctl."""
                        try:
                            import subprocess
                            result = subprocess.run(
                                ["bluetoothctl", "paired-devices"],
                                capture_output=True, text=True, timeout=5
                            )
                            devices = []
                            for line in result.stdout.strip().split('\n'):
                                if line.startswith("Device "):
                                    parts = line.split(" ", 2)
                                    if len(parts) >= 3:
                                        addr = parts[1]
                                        name = parts[2]
                                        devices.append({"address": addr, "name": name})
                            return devices
                        except Exception as e:
                            return []

                    def refresh_paired():
                        paired_listbox.delete(0, tk.END)
                        paired_devices.clear()
                        devices = get_paired_devices()
                        for d in devices:
                            name = d["name"]
                            # Highlight Meshtastic devices
                            if "meshtastic" in name.lower() or "mesh" in name.lower():
                                display = f"[MESH] {name} ({d['address']})"
                            else:
                                display = f"{name} ({d['address']})"
                            paired_listbox.insert(tk.END, display)
                            paired_devices.append(d)
                        if not devices:
                            paired_listbox.insert(tk.END, "(No paired devices found)")

                    # Paired devices buttons
                    paired_btn_frame = ttk.Frame(main_frame)
                    paired_btn_frame.pack(fill=tk.X, pady=5)

                    def select_paired():
                        selection = paired_listbox.curselection()
                        if not selection or not paired_devices:
                            return
                        idx = selection[0]
                        if idx < len(paired_devices):
                            ble_address_var.set(paired_devices[idx]["address"])
                            scan_dialog.destroy()

                    def unpair_device():
                        selection = paired_listbox.curselection()
                        if not selection or not paired_devices:
                            return
                        idx = selection[0]
                        if idx < len(paired_devices):
                            addr = paired_devices[idx]["address"]
                            name = paired_devices[idx]["name"]
                            if messagebox.askyesno("Unpair Device", f"Remove pairing for {name}?"):
                                try:
                                    import subprocess
                                    subprocess.run(["bluetoothctl", "remove", addr], timeout=5)
                                    refresh_paired()
                                except Exception as e:
                                    messagebox.showerror("Error", f"Failed to unpair: {e}")

                    ttk.Button(paired_btn_frame, text="Use Selected", command=select_paired).pack(side=tk.LEFT, padx=2)
                    ttk.Button(paired_btn_frame, text="Refresh", command=refresh_paired).pack(side=tk.LEFT, padx=2)
                    ttk.Button(paired_btn_frame, text="Unpair", command=unpair_device).pack(side=tk.LEFT, padx=2)

                    # === SEPARATOR ===
                    ttk.Separator(main_frame, orient="horizontal").pack(fill=tk.X, pady=10)

                    # === SCAN FOR NEW DEVICES SECTION ===
                    ttk.Label(main_frame, text="Scan for New Devices", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

                    scan_frame = ttk.Frame(main_frame)
                    scan_frame.pack(fill=tk.BOTH, expand=True, pady=5)

                    scanned_listbox = tk.Listbox(scan_frame, height=6, font=("TkFixedFont", 9))
                    scanned_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                    scan_scroll = ttk.Scrollbar(scan_frame, orient=tk.VERTICAL, command=scanned_listbox.yview)
                    scan_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                    scanned_listbox.config(yscrollcommand=scan_scroll.set)

                    status_label = ttk.Label(main_frame, text="Click 'Scan' to find nearby devices", foreground="gray")
                    status_label.pack(pady=5)

                    def do_scan():
                        async def scan_async():
                            try:
                                devices = await BleakScanner.discover(timeout=5.0)
                                return devices
                            except Exception as e:
                                return str(e)
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            result = loop.run_until_complete(scan_async())
                            loop.close()
                            return result
                        except Exception as e:
                            return str(e)

                    def on_scan_complete(devices):
                        if isinstance(devices, str):
                            status_label.config(text=f"Scan error: {devices}", foreground="red")
                            return

                        scanned_listbox.delete(0, tk.END)
                        scanned_devices.clear()

                        # Get paired addresses to filter them out
                        paired_addrs = {d["address"].upper() for d in paired_devices}

                        # Filter for unpaired devices with names
                        meshtastic = []
                        others = []
                        for d in devices:
                            if d.address.upper() in paired_addrs:
                                continue  # Skip already paired
                            if not d.name:
                                continue  # Skip unnamed
                            if "meshtastic" in d.name.lower() or "mesh" in d.name.lower():
                                meshtastic.append(d)
                            else:
                                others.append(d)

                        for d in meshtastic:
                            scanned_listbox.insert(tk.END, f"[MESH] {d.name} ({d.address})")
                            scanned_devices.append(d)

                        if meshtastic and others:
                            scanned_listbox.insert(tk.END, "--- Other devices ---")
                            scanned_devices.append(None)

                        for d in others:
                            scanned_listbox.insert(tk.END, f"{d.name} ({d.address})")
                            scanned_devices.append(d)

                        total = len(meshtastic) + len(others)
                        status_label.config(
                            text=f"Found {total} new devices ({len(meshtastic)} Meshtastic)",
                            foreground="green" if meshtastic else "black"
                        )

                    def run_scan():
                        status_label.config(text="Scanning... (5 seconds)", foreground="blue")
                        scan_dialog.update()
                        def scan_thread():
                            devices = do_scan()
                            scan_dialog.after(0, lambda: on_scan_complete(devices))
                        thread = threading.Thread(target=scan_thread, daemon=True)
                        thread.start()

                    def pair_device():
                        selection = scanned_listbox.curselection()
                        if not selection:
                            messagebox.showwarning("Pair", "Select a device to pair")
                            return
                        idx = selection[0]
                        if idx >= len(scanned_devices) or scanned_devices[idx] is None:
                            return

                        device = scanned_devices[idx]
                        addr = device.address
                        name = device.name

                        # Show PIN dialog
                        pin_dialog = tk.Toplevel(scan_dialog)
                        pin_dialog.title("Pair Device")
                        pin_dialog.geometry("420x450")
                        pin_dialog.transient(scan_dialog)
                        pin_dialog.grab_set()

                        pin_frame = ttk.Frame(pin_dialog, padding=15)
                        pin_frame.pack(fill=tk.BOTH, expand=True)

                        ttk.Label(pin_frame, text=f"Pairing with: {name}", font=("TkDefaultFont", 10, "bold")).pack(pady=(0, 15))

                        # Pairing mode selection
                        mode_frame = ttk.LabelFrame(pin_frame, text="Pairing Mode", padding=10)
                        mode_frame.pack(fill=tk.X, pady=(0, 15))

                        pair_mode = tk.StringVar(value="fixed")

                        ttk.Radiobutton(mode_frame, text="Fixed PIN (default: 123456)",
                                       variable=pair_mode, value="fixed").pack(anchor="w", pady=2)
                        ttk.Radiobutton(mode_frame, text="Radio will display PIN (2-step process)",
                                       variable=pair_mode, value="display").pack(anchor="w", pady=2)
                        ttk.Radiobutton(mode_frame, text="No PIN required",
                                       variable=pair_mode, value="none").pack(anchor="w", pady=2)

                        # PIN entry
                        pin_entry_frame = ttk.Frame(pin_frame)
                        pin_entry_frame.pack(fill=tk.X, pady=15)

                        ttk.Label(pin_entry_frame, text="PIN Code:").pack(side=tk.LEFT, padx=(0, 10))
                        pin_var = tk.StringVar(value="123456")
                        pin_entry = ttk.Entry(pin_entry_frame, textvariable=pin_var, width=12, font=("TkFixedFont", 16))
                        pin_entry.pack(side=tk.LEFT)

                        help_text = ("• Fixed PIN: Enter known PIN (usually 123456), then click Pair\n"
                                    "• Radio displays: Click 'Request PIN' first, read PIN from radio,\n"
                                    "  enter it above, then click 'Send PIN'\n"
                                    "• No PIN: Just click Pair")
                        ttk.Label(pin_frame, text=help_text, foreground="gray",
                                 font=("TkDefaultFont", 9), justify=tk.LEFT).pack(pady=10, anchor="w")

                        pair_status = ttk.Label(pin_frame, text="", foreground="blue", font=("TkDefaultFont", 10))
                        pair_status.pack(pady=10)

                        # Store the pairing process for 2-step mode
                        pair_process = {"proc": None, "waiting_for_pin": False}

                        def request_pin():
                            """Step 1 for display mode: Request pairing to make radio show PIN."""
                            pair_status.config(text="Requesting PIN from radio...\nCheck radio screen for PIN!", foreground="orange")
                            pin_var.set("")  # Clear PIN field for user to enter
                            pin_dialog.update()

                            def request_thread():
                                try:
                                    import subprocess
                                    import time

                                    # Step 1: Power on
                                    subprocess.run(["bluetoothctl", "power", "on"], timeout=5, capture_output=True)

                                    # Step 2: Start bluetoothctl session
                                    pair_process["proc"] = subprocess.Popen(
                                        ["bluetoothctl"],
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True
                                    )

                                    # Step 3: Set up agent (matches your working steps exactly)
                                    pair_process["proc"].stdin.write("agent KeyboardOnly\n")
                                    pair_process["proc"].stdin.flush()
                                    time.sleep(0.5)

                                    pair_process["proc"].stdin.write("default-agent\n")
                                    pair_process["proc"].stdin.flush()
                                    time.sleep(0.5)

                                    # Step 4: Start scanning
                                    pair_process["proc"].stdin.write("scan on\n")
                                    pair_process["proc"].stdin.flush()

                                    # Step 5: Wait for device to be discovered (longer wait)
                                    pin_dialog.after(0, lambda: pair_status.config(
                                        text="Scanning for device...", foreground="blue"))
                                    time.sleep(5)

                                    # Step 6: Pair
                                    pair_process["proc"].stdin.write(f"pair {addr}\n")
                                    pair_process["proc"].stdin.flush()
                                    pair_process["waiting_for_pin"] = True

                                    pin_dialog.after(0, lambda: pair_status.config(
                                        text="PIN requested!\nCheck your radio screen for PIN,\nenter it above, then click 'Send PIN'",
                                        foreground="green"))
                                except Exception as e:
                                    pin_dialog.after(0, lambda: pair_status.config(
                                        text=f"Error: {str(e)[:40]}", foreground="red"))

                            thread = threading.Thread(target=request_thread, daemon=True)
                            thread.start()

                        def send_pin():
                            """Step 2 for display mode: Send the PIN user entered."""
                            if not pair_process["waiting_for_pin"] or not pair_process["proc"]:
                                pair_status.config(text="Click 'Request PIN' first!", foreground="red")
                                return

                            pin = pin_var.get()
                            if not pin:
                                pair_status.config(text="Please enter the PIN from your radio", foreground="red")
                                return

                            pair_status.config(text="Sending PIN...", foreground="blue")
                            pin_dialog.update()

                            def send_thread():
                                try:
                                    import subprocess
                                    import time

                                    proc = pair_process["proc"]

                                    # Send just the PIN
                                    proc.stdin.write(f"{pin}\n")
                                    proc.stdin.flush()

                                    # Wait for pairing to complete
                                    time.sleep(4)

                                    # Trust the device
                                    proc.stdin.write(f"trust {addr}\n")
                                    proc.stdin.flush()
                                    time.sleep(1)

                                    # Kill the bluetoothctl process (don't wait for quit)
                                    try:
                                        proc.terminate()
                                        proc.wait(timeout=2)
                                    except:
                                        try:
                                            proc.kill()
                                        except:
                                            pass

                                    pair_process["waiting_for_pin"] = False
                                    pair_process["proc"] = None

                                    # Verify pairing using fresh command
                                    time.sleep(1)
                                    check = subprocess.run(
                                        ["bluetoothctl", "paired-devices"],
                                        capture_output=True, text=True, timeout=5
                                    )
                                    if addr.upper() in check.stdout.upper():
                                        pin_dialog.after(0, on_pair_success)
                                    else:
                                        pin_dialog.after(0, lambda: on_pair_failure("Pairing not confirmed. Try again."))
                                except Exception as e:
                                    pin_dialog.after(0, lambda: on_pair_failure(str(e)))

                            thread = threading.Thread(target=send_thread, daemon=True)
                            thread.start()

                        def do_pair():
                            mode = pair_mode.get()
                            if mode == "display":
                                # For display mode, user should use Request PIN / Send PIN buttons
                                pair_status.config(text="Use 'Request PIN' button first for this mode", foreground="orange")
                                return

                            if mode == "none":
                                pair_status.config(text="Pairing without PIN...", foreground="blue")
                            else:
                                pair_status.config(text="Pairing with PIN...", foreground="blue")
                            pin_dialog.update()

                            def pair_thread():
                                try:
                                    import subprocess
                                    import time

                                    mode = pair_mode.get()
                                    pin = pin_var.get() if mode != "none" else ""

                                    # Step 1: Power on Bluetooth
                                    subprocess.run(["bluetoothctl", "power", "on"], timeout=5, capture_output=True)

                                    # Step 2: Remove any existing pairing first
                                    subprocess.run(["bluetoothctl", "remove", addr], timeout=5, capture_output=True)
                                    time.sleep(0.5)

                                    # Step 3: Set up agent based on mode
                                    pair_proc = subprocess.Popen(
                                        ["bluetoothctl"],
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True
                                    )

                                    if mode == "none":
                                        # NoInputNoOutput agent for no PIN
                                        commands = f"agent NoInputNoOutput\ndefault-agent\nscan on\n"
                                    else:
                                        # KeyboardOnly agent for PIN entry
                                        commands = f"agent KeyboardOnly\ndefault-agent\nscan on\n"

                                    pair_proc.stdin.write(commands)
                                    pair_proc.stdin.flush()

                                    # Wait for device to be discovered
                                    time.sleep(3)

                                    # Now pair
                                    pair_proc.stdin.write(f"pair {addr}\n")
                                    pair_proc.stdin.flush()

                                    # Wait for pairing prompt
                                    time.sleep(3)

                                    # Send PIN if required
                                    if mode != "none" and pin:
                                        pair_proc.stdin.write(f"{pin}\n")
                                        pair_proc.stdin.flush()
                                        time.sleep(1)
                                        # Sometimes need to confirm
                                        pair_proc.stdin.write("yes\n")
                                        pair_proc.stdin.flush()

                                    time.sleep(2)

                                    # Trust the device
                                    pair_proc.stdin.write(f"trust {addr}\nquit\n")
                                    pair_proc.stdin.flush()

                                    stdout, _ = pair_proc.communicate(timeout=15)

                                    # Check if pairing succeeded by verifying paired devices
                                    time.sleep(1)
                                    check = subprocess.run(
                                        ["bluetoothctl", "paired-devices"],
                                        capture_output=True, text=True, timeout=5
                                    )

                                    if addr.upper() in check.stdout.upper():
                                        pin_dialog.after(0, on_pair_success)
                                    else:
                                        pin_dialog.after(0, lambda: on_pair_failure("Device not in paired list. Check PIN or try again."))

                                except subprocess.TimeoutExpired:
                                    pin_dialog.after(0, lambda: on_pair_failure("Pairing timed out"))
                                except Exception as e:
                                    pin_dialog.after(0, lambda: on_pair_failure(str(e)))

                            def on_pair_success():
                                pair_status.config(text="Paired successfully!", foreground="green")
                                pin_dialog.after(1500, pin_dialog.destroy)
                                refresh_paired()

                            def on_pair_failure(error):
                                pair_status.config(text=f"Failed: {error[:40]}", foreground="red")

                            thread = threading.Thread(target=pair_thread, daemon=True)
                            thread.start()

                        # Buttons for 2-step process (display mode)
                        step_btn_frame = ttk.Frame(pin_frame)
                        step_btn_frame.pack(pady=5)
                        ttk.Button(step_btn_frame, text="1. Request PIN", command=request_pin, width=14).pack(side=tk.LEFT, padx=5)
                        ttk.Button(step_btn_frame, text="2. Send PIN", command=send_pin, width=14).pack(side=tk.LEFT, padx=5)

                        # Buttons for fixed/no PIN modes
                        btn_frame = ttk.Frame(pin_frame)
                        btn_frame.pack(pady=10)
                        ttk.Button(btn_frame, text="Pair", command=do_pair, width=10).pack(side=tk.LEFT, padx=10)
                        ttk.Button(btn_frame, text="Cancel", command=pin_dialog.destroy, width=10).pack(side=tk.LEFT, padx=10)

                    # Scan buttons
                    scan_btn_frame = ttk.Frame(main_frame)
                    scan_btn_frame.pack(fill=tk.X, pady=5)

                    ttk.Button(scan_btn_frame, text="Scan", command=run_scan).pack(side=tk.LEFT, padx=2)
                    ttk.Button(scan_btn_frame, text="Pair Selected", command=pair_device).pack(side=tk.LEFT, padx=2)

                    # Close button
                    ttk.Button(main_frame, text="Close", command=scan_dialog.destroy).pack(pady=10)

                    # Initial load of paired devices
                    refresh_paired()

                ttk.Button(settings_frame, text="Manage...", command=scan_ble).grid(row=0, column=2, padx=5)

        # Initialize fields
        update_fields()

        # Current connection status
        status_frame = ttk.Frame(frame)
        status_frame.grid(row=4, column=0, columnspan=2, sticky="w", pady=15)

        current_type = self.config.get("connection_type", "serial").upper()
        status_text = f"Current: {current_type}"
        if self.running:
            status_text += " (Connected)"
        else:
            status_text += " (Not connected)"
        ttk.Label(status_frame, text=status_text, foreground="blue").pack()

        # Auto-reconnect option
        reconnect_frame = ttk.Frame(frame)
        reconnect_frame.grid(row=5, column=0, columnspan=2, sticky="w", pady=10)
        auto_reconnect_var = tk.BooleanVar(value=self.config.get("auto_reconnect", True))
        ttk.Checkbutton(reconnect_frame, text="Auto-reconnect on disconnect", variable=auto_reconnect_var).pack()

        # Test connection section
        test_frame = ttk.Frame(frame)
        test_frame.grid(row=6, column=0, columnspan=2, sticky="w", pady=10)

        test_status_canvas = tk.Canvas(test_frame, width=16, height=16)
        test_status_canvas.pack(side=tk.LEFT, padx=(0, 8))
        test_status_circle = test_status_canvas.create_oval(2, 2, 14, 14, fill="gray")

        test_label = ttk.Label(test_frame, text="Not tested", foreground="gray")
        test_label.pack(side=tk.LEFT, padx=(0, 10))

        def test_connection():
            conn_type = conn_type_var.get()

            # Get connection parameters based on type
            if conn_type == "serial":
                port_value = serial_port_var.get()
                if port_value == "(Auto-detect)":
                    port_value = None
                test_target = port_value or "auto-detect"
            elif conn_type == "tcp":
                test_target = tcp_host_var.get()
                if not test_target:
                    test_status_canvas.itemconfig(test_status_circle, fill="red")
                    test_label.config(text="No IP address entered", foreground="red")
                    return
            elif conn_type == "ble":
                test_target = ble_address_var.get()
                if not test_target:
                    test_status_canvas.itemconfig(test_status_circle, fill="red")
                    test_label.config(text="No BLE address entered", foreground="red")
                    return

            # Show testing status
            test_status_canvas.itemconfig(test_status_circle, fill="yellow")
            timeout_hint = " (15s timeout)" if conn_type == "ble" else ""
            test_label.config(text=f"Testing {conn_type}...{timeout_hint}", foreground="orange")
            dialog.update()

            def do_test():
                import concurrent.futures

                def create_interface():
                    if conn_type == "serial":
                        port_value = serial_port_var.get()
                        dev_path = None if port_value == "(Auto-detect)" else port_value
                        return meshtastic.serial_interface.SerialInterface(devPath=dev_path)
                    elif conn_type == "tcp":
                        return meshtastic.tcp_interface.TCPInterface(hostname=test_target)
                    elif conn_type == "ble":
                        return meshtastic.ble_interface.BLEInterface(address=test_target)

                try:
                    # Use timeout for connection (BLE can hang)
                    timeout = 15 if conn_type == "ble" else 10
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(create_interface)
                        test_interface = future.result(timeout=timeout)

                    # Success - close the test interface
                    test_interface.close()
                    dialog.after(0, lambda: on_test_success(test_target))
                except concurrent.futures.TimeoutError:
                    dialog.after(0, lambda: on_test_failure(f"Connection timed out ({timeout}s)"))
                except Exception as e:
                    dialog.after(0, lambda: on_test_failure(str(e)))

            def on_test_success(target):
                # Check if already in use by our service
                test_status_canvas.itemconfig(test_status_circle, fill="green")
                test_label.config(text=f"Connected to {target}", foreground="green")

            def on_test_failure(error):
                # Check if error is because port is in use by our service
                if self.running and ("busy" in error.lower() or "in use" in error.lower() or "resource" in error.lower()):
                    test_status_canvas.itemconfig(test_status_circle, fill="green")
                    test_label.config(text="In use by active connection", foreground="green")
                else:
                    test_status_canvas.itemconfig(test_status_circle, fill="red")
                    test_label.config(text=f"Failed: {error[:30]}...", foreground="red")

            # Run test in thread to keep UI responsive
            thread = threading.Thread(target=do_test, daemon=True)
            thread.start()

        ttk.Button(test_frame, text="Test Connection", command=test_connection).pack(side=tk.LEFT)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=15, pady=10)

        def save_radio_config():
            conn_type = conn_type_var.get()
            self.config["connection_type"] = conn_type

            if conn_type == "serial":
                port_value = serial_port_var.get()
                if port_value == "(Auto-detect)":
                    port_value = ""
                self.config["serial_port"] = port_value
            elif conn_type == "tcp":
                self.config["tcp_host"] = tcp_host_var.get()
            elif conn_type == "ble":
                self.config["ble_address"] = ble_address_var.get()

            self.config["auto_reconnect"] = auto_reconnect_var.get()

            if save_config(self.config):
                messagebox.showinfo("Radio Connection", "Configuration saved!\nRestart the service to apply changes.")
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to save configuration")

        ttk.Button(button_frame, text="Save", command=save_radio_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

        frame.columnconfigure(1, weight=1)

    def _open_settings(self):
        """Open the settings dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("550x480")
        dialog.transient(self.root)
        dialog.grab_set()

        # Create form
        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        row = 0

        # Auto-start checkbox
        ttk.Label(frame, text="Startup:").grid(row=row, column=0, sticky="w", pady=5)
        auto_start_var = tk.BooleanVar(value=self.config.get("auto_start", True))
        ttk.Checkbutton(frame, text="Auto-start service on launch", variable=auto_start_var).grid(row=row, column=1, sticky="w", pady=5)

        row += 1

        # Sound notifications checkbox
        ttk.Label(frame, text="Notifications:").grid(row=row, column=0, sticky="w", pady=5)
        sound_var = tk.BooleanVar(value=self.config.get("sound_notifications", True))
        ttk.Checkbutton(frame, text="Play sound on incoming messages", variable=sound_var).grid(row=row, column=1, sticky="w", pady=5)

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

        # Font Size
        ttk.Label(frame, text="Font Size:").grid(row=row, column=0, sticky="w", pady=5)
        font_size_var = tk.StringVar(value=str(self.config.get("font_size", 10)))
        ttk.Spinbox(frame, from_=8, to=18, textvariable=font_size_var, width=5).grid(row=row, column=1, sticky="w", pady=5)

        row += 1

        frame.columnconfigure(1, weight=1)

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        def save_settings():
            self.config["auto_start"] = auto_start_var.get()
            self.config["ai_enabled"] = ai_enabled_var.get()
            self.config["sound_notifications"] = sound_var.get()
            self.config["ollama_url"] = url_var.get()
            self.config["ollama_model"] = model_var.get()
            self.config["ai_prefix"] = prefix_var.get()
            self.config["default_channel"] = int(channel_var.get())
            self.config["api_retries"] = int(retries_var.get())
            self.config["font_size"] = int(font_size_var.get())

            if save_config(self.config):
                # Update main window AI status after saving
                self._check_ollama_connection()
                # Apply font size to text widgets
                self._apply_font_size(self.config["font_size"])
                messagebox.showinfo("Settings", "Settings saved successfully!")
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to save settings")

        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

    def _create_interface(self):
        """Create the appropriate interface based on connection type."""
        conn_type = self.config.get("connection_type", "serial")

        if conn_type == "serial":
            serial_port = self.config.get("serial_port", "")
            dev_path = serial_port if serial_port else None
            interface = meshtastic.serial_interface.SerialInterface(devPath=dev_path)
            conn_info = interface.devPath if hasattr(interface, 'devPath') else dev_path or "auto"
        elif conn_type == "tcp":
            tcp_host = self.config.get("tcp_host", "")
            if not tcp_host:
                raise ValueError("TCP host not configured. Please set the IP address in Radio Connection settings.")
            interface = meshtastic.tcp_interface.TCPInterface(hostname=tcp_host)
            conn_info = tcp_host
        elif conn_type == "ble":
            ble_address = self.config.get("ble_address", "")
            if not ble_address:
                raise ValueError("BLE address not configured. Please set the address in Radio Connection settings.")

            # Ensure Bluetooth is on, but DON'T connect - let meshtastic handle it
            import subprocess
            try:
                subprocess.run(["bluetoothctl", "power", "on"], timeout=5, capture_output=True)
                # Disconnect any existing OS-level connection so meshtastic can connect
                subprocess.run(["bluetoothctl", "disconnect", ble_address], timeout=5, capture_output=True)
            except Exception:
                pass

            interface = meshtastic.ble_interface.BLEInterface(address=ble_address)
            conn_info = ble_address
        else:
            raise ValueError(f"Unknown connection type: {conn_type}")

        return interface, conn_type, conn_info

    def start_service(self):
        """Start the Meshtastic listener service."""
        if self.running:
            messagebox.showinfo("Info", "Service is already running")
            return

        if hasattr(self, '_connecting') and self._connecting:
            messagebox.showinfo("Info", "Connection attempt in progress...")
            return

        # Get connection info for status display
        conn_type = self.config.get("connection_type", "serial")
        if conn_type == "tcp":
            conn_info = self.config.get("tcp_host", "")
        elif conn_type == "ble":
            conn_info = self.config.get("ble_address", "")
        else:
            conn_info = self.config.get("serial_port", "") or "auto"

        self._connecting = True
        self._update_status(False, f"Connecting to {conn_info}...")
        self._log_received(f"Attempting {conn_type.upper()} connection to {conn_info}...")

        def connect_thread():
            try:
                interface, conn_type, conn_info = self._create_interface()
                # Schedule UI update on main thread - use default args to capture values
                self.root.after(0, lambda i=interface, t=conn_type, c=conn_info: self._on_connect_success(i, t, c))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self._on_connect_failure(msg))
            finally:
                # Ensure _connecting is always reset
                self._connecting = False

        thread = threading.Thread(target=connect_thread, daemon=True)
        thread.start()

    def _on_connect_success(self, interface, conn_type, conn_info):
        """Handle successful connection (called on main thread)."""
        self._connecting = False
        self.interface = interface
        self.running = True
        self._update_status(True, conn_info)
        self._log_received(f"Service started - Connected via {conn_type.upper()} ({conn_info})")
        # Clear and refresh node list
        self.root.after(1000, self._refresh_nodes)
        # Start refresh timer
        self._start_refresh_timer()
        # Start session timer
        self._start_session_timer()
        # Start connection health check
        self._start_connection_check()

    def _on_connect_failure(self, error_msg):
        """Handle connection failure (called on main thread)."""
        self._connecting = False
        self._update_status(False)
        self._log_received(f"Connection failed: {error_msg}")
        messagebox.showerror("Connection Error", f"Failed to connect:\n{error_msg}")

    def stop_service(self):
        """Stop the Meshtastic listener service."""
        # Cancel any pending connection attempt
        if hasattr(self, '_connecting') and self._connecting:
            self._connecting = False
            self._update_status(False)
            self._log_received("Connection attempt cancelled")
            return

        if not self.running:
            messagebox.showinfo("Info", "Service is not running")
            return

        # Stop refresh timer
        self._stop_refresh_timer()
        # Stop session timer
        self._stop_session_timer()
        # Stop connection check
        self._stop_connection_check()

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

    def _start_connection_check(self):
        """Start periodic connection health check."""
        self._stop_connection_check()
        self._check_connection_health()

    def _stop_connection_check(self):
        """Stop the connection health check timer."""
        if hasattr(self, 'connection_check_id') and self.connection_check_id:
            self.root.after_cancel(self.connection_check_id)
            self.connection_check_id = None

    def _check_connection_health(self):
        """Check if the Meshtastic connection is still alive."""
        if not self.running or not self.interface:
            return

        try:
            # Try to access the interface to check if it's still connected
            # This will raise an exception if the device is disconnected
            _ = self.interface.myInfo
        except Exception:
            # Connection lost - attempt auto-reconnect if enabled
            if self.config.get("auto_reconnect", True):
                self._log_received("Connection lost - attempting to reconnect...")
                self._attempt_reconnect()
            else:
                self._log_received("Connection lost")
                self._handle_disconnect()
            return

        # Schedule next check (every 10 seconds)
        self.connection_check_id = self.root.after(10000, self._check_connection_health)

    def _handle_disconnect(self):
        """Handle a disconnection without showing dialog."""
        self.running = False
        self._stop_refresh_timer()
        self._stop_session_timer()
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass
            self.interface = None
        self._update_status(False)
        # Clear node list
        for item in self.node_tree.get_children():
            self.node_tree.delete(item)

    def _attempt_reconnect(self):
        """Attempt to reconnect to the Meshtastic device."""
        # First clean up the old connection
        self._handle_disconnect()

        # Wait a moment then try to reconnect
        self.root.after(2000, self._do_reconnect)

    def _do_reconnect(self):
        """Perform the actual reconnection attempt."""
        if hasattr(self, '_connecting') and self._connecting:
            # Already trying to connect, skip
            return

        conn_type = self.config.get("connection_type", "serial")
        self._connecting = True
        self._log_received(f"Attempting {conn_type.upper()} reconnection...")

        def reconnect_thread():
            try:
                interface, conn_type, conn_info = self._create_interface()
                self.root.after(0, lambda: self._on_reconnect_success(interface, conn_type, conn_info))
            except Exception as e:
                self.root.after(0, lambda: self._on_reconnect_failure(str(e)))

        thread = threading.Thread(target=reconnect_thread, daemon=True)
        thread.start()

    def _on_reconnect_success(self, interface, conn_type, conn_info):
        """Handle successful reconnection (called on main thread)."""
        self._connecting = False
        self.interface = interface
        self.running = True
        self._update_status(True, conn_info)
        self._log_received(f"Reconnected via {conn_type.upper()} ({conn_info})")
        self.root.after(1000, self._refresh_nodes)
        self._start_refresh_timer()
        self._start_session_timer()
        self._start_connection_check()

    def _on_reconnect_failure(self, error_msg):
        """Handle reconnection failure (called on main thread)."""
        self._connecting = False
        self._log_received(f"Reconnect failed: {error_msg} - retrying in 5 seconds...")
        # Retry in 5 seconds if auto-reconnect is still enabled
        if self.config.get("auto_reconnect", True):
            self.root.after(5000, self._do_reconnect)

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

            # Update counters (sent + received since it echoes to received area)
            self.messages_sent += 1
            self.messages_received += 1
            self._update_message_counters()

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
        # Save window geometry and theme before exit
        self.config["window_geometry"] = self.root.geometry()
        self.config["theme"] = self.current_theme
        save_config(self.config)
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
