#!/usr/bin/env python3
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import subprocess   # or use requests if your Llama runs an API (Ollama, vLLM, etc.)
import re

# ================= CONFIG =================
# Change these as needed
SERIAL_PORT = None          # None = auto-detect, or "/dev/ttyUSB0"
#
AI_PREFIX = "/AI"           # or r"\/AI\s+" for regex
LLAMA_CMD = ["ollama", "run", "llama3.1", "--"]  # Example for Ollama CLI; adjust to your setup
# If using HTTP API instead:
# Use requests.post("http://localhost:11434/api/generate", json={...})
# SERIAL_PORT = '/dev/ttyUSB0'
# ==========================================
#interface = meshtastic.serial_interface.SerialInterface(devPath=SERIAL_PORT)
#print(f"Connected to: {interface.devPath}") # This will confirm the actual port being used
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

    try:
        import requests
        response = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "llama3.1",  # ← your model
                "prompt": f"Answer very concisely in under 120 characters: {question}",
                "stream": False,
                "options": {"temperature": 0.7}
            },
            timeout=90
        )
        response.raise_for_status()
        answer = response.json().get("response", "").strip() or "No response."

    except Exception as e:
        answer = f"Error: {str(e)[:60]}"

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

def main():
    print("Starting Meshtastic AI listener...")
    try:
        interface = meshtastic.serial_interface.SerialInterface(devPath=SERIAL_PORT)
    except Exception as e:
        print(f"Failed to connect: {e}")
        print("Try specifying port with SERIAL_PORT = '/dev/ttyUSB0'")
        return

    # Subscribe to receive events
    pub.subscribe(on_receive, "meshtastic.receive")

    print("Listening for messages... (Ctrl+C to exit)")
    try:
        while True:
            time.sleep(1)  # keep the script alive
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        interface.close()

if __name__ == "__main__":
    main()
