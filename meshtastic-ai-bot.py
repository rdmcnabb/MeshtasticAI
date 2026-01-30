#!/usr/bin/env python3
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import requests
import logging
import os
from datetime import datetime
import serial.tools.list_ports
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# ================= CONFIG (env vars with defaults) =================
SERIAL_PORT = os.getenv("MESHTASTIC_SERIAL_PORT")  # None = auto-detect
AI_PREFIX = os.getenv("AI_PREFIX", "/AI")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Reliability settings
API_RETRIES = int(os.getenv("API_RETRIES", "3"))
API_RETRY_DELAY = int(os.getenv("API_RETRY_DELAY", "2"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "5"))
# ====================================================================

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def check_first_run():
    """Check if this is the first time running."""
    config_file = os.path.expanduser("~/.meshtastic-ai-bot-configured")
    return not os.path.exists(config_file)


def mark_configured():
    """Mark that initial setup is complete."""
    config_file = os.path.expanduser("~/.meshtastic-ai-bot-configured")
    with open(config_file, 'w') as f:
        f.write("configured")
    logger.info("Setup marked as complete")


def find_meshtastic_devices():
    """Find available serial devices that might be Meshtastic radios."""
    ports = serial.tools.list_ports.comports()
    meshtastic_ports = []
    for port in ports:
        # Look for common USB serial devices
        if 'USB' in port.device or 'ACM' in port.device or 'ttyUSB' in port.device:
            meshtastic_ports.append(port.device)
    return meshtastic_ports


def query_ollama(question, retries=API_RETRIES):
    """Query Ollama API with retry logic."""
    now = datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")
    current_day = now.strftime("%A")

    system_context = f"Current date and time: {current_day}, {current_time}."

    last_error = None
    for attempt in range(retries):
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
            if attempt < retries - 1:
                logger.warning(
                    f"Ollama API attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {API_RETRY_DELAY}s..."
                )
                time.sleep(API_RETRY_DELAY)
    return f"Error: {str(last_error)[:60]}"


def on_receive(packet, interface):
    if "decoded" not in packet:
        return

    decoded = packet["decoded"]
    if decoded.get("portnum") != "TEXT_MESSAGE_APP":
        return

    text = decoded.get("text", "").strip()
    if not text:
        return

    from_id = packet.get("fromId", "unknown")
    incoming_channel = packet.get("channel", 0)   # 0 is primary if missing

    logger.info(f"Received from {from_id} on ch {incoming_channel}: {text}")

    if not text.upper().startswith(AI_PREFIX.upper()):
        return

    question = text[len(AI_PREFIX):].strip()
    if not question:
        return

    logger.info(f"AI query detected on channel {incoming_channel}: {question}")

    answer = query_ollama(question)

    # Truncate safely based on byte count
    max_bytes = 200
    prefix = f"@{from_id} "
    suffix = "..."

    # Calculate available bytes for the answer
    available_bytes = max_bytes - len(prefix.encode('utf-8')) - len(suffix.encode('utf-8'))

    # Truncate answer by bytes, not characters
    answer_bytes = answer.encode('utf-8')
    if len(answer_bytes) > available_bytes:
        # Truncate and ensure we don't cut in the middle of a multi-byte character
        truncated = answer_bytes[:available_bytes].decode('utf-8', errors='ignore')
        reply = f"{prefix}{truncated}{suffix}"
    else:
        reply = f"{prefix}{answer}"

    reply_bytes = len(reply.encode('utf-8'))
    logger.debug(f"Send ch {incoming_channel} ({reply_bytes}B): {reply}")

    try:
        interface.sendText(
            text=reply,
            channelIndex=incoming_channel,
            # Optional: want private DM instead? Uncomment next line
            # destinationId=from_id
        )
        logger.info(f"Reply sent successfully on channel {incoming_channel}")
    except Exception as e:
        logger.error(f"Send failed on channel {incoming_channel}: {e}")
        # NO FALLBACK HERE – we want to know if it fails


def connect_interface():
    """Connect to Meshtastic device with error handling."""
    try:
        interface = meshtastic.serial_interface.SerialInterface(
            devPath=SERIAL_PORT
        )
        logger.info("Connected to Meshtastic device")
        return interface
    except FileNotFoundError as e:
        logger.error("No Meshtastic device found on serial port")
        logger.error(f"Tried port: {SERIAL_PORT or 'auto-detect'}")
        devices = find_meshtastic_devices()
        if devices:
            logger.error(f"Available devices: {', '.join(devices)}")
            logger.error(f"Set MESHTASTIC_SERIAL_PORT env var to use a specific port")
        return None
    except PermissionError as e:
        logger.error("Permission denied to access serial port")
        logger.error("Run: sudo usermod -a -G dialout $USER")
        logger.error("Then log out and back in")
        return None
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        logger.error("Make sure your radio is powered on and connected via USB")
        return None


def interactive_setup():
    """Interactive first-time setup menu."""
    global SERIAL_PORT
    test_interface = None

    while True:
        print("\n" + "=" * 60)
        print("FIRST TIME SETUP")
        print("=" * 60)
        print("\nPlease configure your Meshtastic radio before starting the bot.")
        print("\nMenu Options:")
        print("  1. List available devices")
        print("  2. Test connection")
        print("  3. Set serial port manually")
        if test_interface is not None:
            print("  4. START BOT (connection successful!)")
        else:
            print("  4. START BOT (unavailable - test connection first)")
        print("  5. Exit")
        print("\nNote: Make sure your radio is:")
        print("  - Powered on")
        print("  - Connected via USB")
        print("  - Already configured (use Meshtastic app/CLI first if needed)")

        try:
            choice = input("\nEnter your choice (1-5): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nExiting setup...")
            return None

        if choice == "1":
            # List devices
            print("\nScanning for USB serial devices...")
            devices = find_meshtastic_devices()
            if not devices:
                print("No USB serial devices found!")
                print("Please connect your radio via USB.")
            else:
                print(f"\nFound {len(devices)} device(s):")
                for i, device in enumerate(devices, 1):
                    print(f"  {i}. {device}")
                if SERIAL_PORT:
                    print(f"\nCurrently set: {SERIAL_PORT}")
                else:
                    print(f"\nCurrently set: auto-detect")

        elif choice == "2":
            # Test connection
            print("\nTesting connection...")
            print(f"Trying port: {SERIAL_PORT or 'auto-detect'}")

            try:
                test_interface = meshtastic.serial_interface.SerialInterface(
                    devPath=SERIAL_PORT
                )
                print("✓ Connection successful!")
                print("✓ Radio is responding")
                print("\nYou can now start the bot (option 4)")
            except FileNotFoundError:
                print("✗ No device found")
                print("Try:")
                print("  - Option 1 to list available devices")
                print("  - Option 3 to set a specific port")
                test_interface = None
            except PermissionError:
                print("✗ Permission denied")
                print("Run: sudo usermod -a -G dialout $USER")
                print("Then log out and back in")
                test_interface = None
            except Exception as e:
                print(f"✗ Connection failed: {e}")
                print("Make sure radio is powered on and connected")
                test_interface = None

        elif choice == "3":
            # Set serial port manually
            print("\nAvailable devices:")
            devices = find_meshtastic_devices()
            if devices:
                for i, device in enumerate(devices, 1):
                    print(f"  {i}. {device}")
                print(f"  {len(devices) + 1}. Enter custom path")
                print(f"  {len(devices) + 2}. Use auto-detect")

                try:
                    port_choice = input(f"\nSelect device (1-{len(devices) + 2}): ").strip()
                    port_idx = int(port_choice) - 1

                    if 0 <= port_idx < len(devices):
                        SERIAL_PORT = devices[port_idx]
                        print(f"✓ Serial port set to: {SERIAL_PORT}")
                        test_interface = None  # Reset test status
                    elif port_idx == len(devices):
                        custom_path = input("Enter custom serial port path: ").strip()
                        SERIAL_PORT = custom_path
                        print(f"✓ Serial port set to: {SERIAL_PORT}")
                        test_interface = None
                    elif port_idx == len(devices) + 1:
                        SERIAL_PORT = None
                        print("✓ Serial port set to: auto-detect")
                        test_interface = None
                except (ValueError, IndexError):
                    print("Invalid selection")
            else:
                print("No devices found. Enter custom path or press Enter for auto-detect:")
                custom = input("Serial port: ").strip()
                SERIAL_PORT = custom if custom else None
                print(f"✓ Serial port set to: {SERIAL_PORT or 'auto-detect'}")
                test_interface = None

        elif choice == "4":
            # Start bot
            if test_interface is not None:
                print("\n✓ Starting bot...")
                mark_configured()
                return test_interface
            else:
                print("\n✗ Cannot start - connection test required first!")
                print("Please use option 2 to test your connection")

        elif choice == "5":
            # Exit
            print("\nExiting setup...")
            if test_interface:
                test_interface.close()
            return None

        else:
            print("\nInvalid choice. Please enter 1-5.")


def main():
    logger.info("Starting Meshtastic AI listener...")

    # Check for first run - interactive setup
    if check_first_run():
        interface = interactive_setup()
        if interface is None:
            logger.info("Setup cancelled. Exiting.")
            return
        logger.info("Setup complete! Starting bot...")
    else:
        # Not first run, try to connect normally
        interface = None

    # Subscribe to receive events (only once)
    pub.subscribe(on_receive, "meshtastic.receive")

    # interface may already be set from interactive_setup()
    retry_count = 0
    max_retries = 3

    try:
        # If interface already exists (from setup), skip to listening
        if interface is not None:
            logger.info("Listening for messages... (Ctrl+C to exit)")

        while True:
            # Connect if not connected
            if interface is None:
                interface = connect_interface()
                if interface is None:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error("")
                        logger.error("=" * 60)
                        logger.error("Failed to connect after 3 attempts.")
                        logger.error("=" * 60)
                        logger.error("")
                        logger.error("Troubleshooting steps:")
                        logger.error("  1. Ensure radio is powered on")
                        logger.error("  2. Check USB cable is connected")
                        logger.error("  3. Verify permissions: sudo usermod -a -G dialout $USER")
                        logger.error("  4. Test with: python3 -m meshtastic --info")
                        logger.error("  5. Try unplugging and replugging the USB cable")
                        logger.error("")
                        logger.error("If radio is not configured, delete this file to see setup:")
                        logger.error(f"  rm ~/.meshtastic-ai-bot-configured")
                        logger.error("")
                        return
                    logger.warning(f"Retry {retry_count}/{max_retries} in {RECONNECT_DELAY}s...")
                    time.sleep(RECONNECT_DELAY)
                    continue

                # Successfully connected
                retry_count = 0  # Reset for reconnection attempts
                logger.info("Listening for messages... (Ctrl+C to exit)")

            # Check if connection is still alive
            try:
                time.sleep(1)
            except Exception as e:
                logger.error(f"Connection lost: {e}")
                try:
                    interface.close()
                except Exception:
                    pass
                interface = None
                # For reconnections, allow up to 3 retries before giving up
                if retry_count >= max_retries:
                    logger.error("Too many reconnection failures. Exiting.")
                    return
                logger.warning(f"Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if interface:
            interface.close()


if __name__ == "__main__":
    main()
