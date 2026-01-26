#!/usr/bin/env python3
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import requests

# ================= CONFIG =================
SERIAL_PORT = None          # None = auto-detect, or "/dev/ttyUSB0"
AI_PREFIX = "/AI"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.1"

# Reliability settings
API_RETRIES = 3             # Number of retry attempts for Ollama API
API_RETRY_DELAY = 2         # Seconds between retries
RECONNECT_DELAY = 5         # Seconds to wait before reconnecting
# ==========================================


def query_ollama(question, retries=API_RETRIES):
    """Query Ollama API with retry logic."""
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": f"Answer very concisely in under 120 characters: {question}",
                    "stream": False,
                    "options": {"temperature": 0.7}
                },
                timeout=90
            )
            response.raise_for_status()
            return response.json().get("response", "").strip() or "No response."
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"Ollama API attempt {attempt + 1} failed: {e}. Retrying in {API_RETRY_DELAY}s...")
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

    print(f"Received from {from_id} on channel {incoming_channel}: {text}")

    if not text.upper().startswith(AI_PREFIX.upper()):
        return

    question = text[len(AI_PREFIX):].strip()
    if not question:
        return

    print(f"AI query detected on channel {incoming_channel}: {question}")

    answer = query_ollama(question)

    # Truncate safely
    max_bytes = 200
    reply_base = f"@{from_id} {answer}"
    reply = reply_base
    if len(reply.encode('utf-8')) > max_bytes:
        reply = f"@{from_id} {answer[:100]}..."

    print(f"Preparing to send on channel {incoming_channel} only ({len(reply.encode('utf-8'))} bytes): {reply}")

    try:
        interface.sendText(
            text=reply,
            channelIndex=incoming_channel,
            # Optional: want private DM instead? Uncomment next line
            # destinationId=from_id
        )
        print(f"Reply sent successfully on channel {incoming_channel}")
    except Exception as e:
        print(f"Send failed on channel {incoming_channel}: {e}")
        # NO FALLBACK HERE – we want to know if it fails

def connect_interface():
    """Connect to Meshtastic device with error handling."""
    try:
        interface = meshtastic.serial_interface.SerialInterface(devPath=SERIAL_PORT)
        print(f"Connected to Meshtastic device")
        return interface
    except Exception as e:
        print(f"Failed to connect: {e}")
        return None


def main():
    print("Starting Meshtastic AI listener...")

    # Subscribe to receive events (only once)
    pub.subscribe(on_receive, "meshtastic.receive")

    interface = None

    try:
        while True:
            # Connect if not connected
            if interface is None:
                interface = connect_interface()
                if interface is None:
                    print(f"Retrying connection in {RECONNECT_DELAY}s...")
                    time.sleep(RECONNECT_DELAY)
                    continue
                print("Listening for messages... (Ctrl+C to exit)")

            # Check if connection is still alive
            try:
                time.sleep(1)
            except Exception as e:
                print(f"Connection lost: {e}")
                try:
                    interface.close()
                except:
                    pass
                interface = None
                print(f"Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if interface:
            interface.close()

if __name__ == "__main__":
    main()
