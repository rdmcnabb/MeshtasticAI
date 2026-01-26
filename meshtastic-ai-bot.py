#!/usr/bin/env python3
import meshtastic
import meshtastic.serial_interface
from pubsub import pub
import time
import requests
import logging
import os
from datetime import datetime

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

    # Truncate safely
    max_bytes = 200
    reply_base = f"@{from_id} {answer}"
    reply = reply_base
    if len(reply.encode('utf-8')) > max_bytes:
        reply = f"@{from_id} {answer[:100]}..."

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
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return None


def main():
    logger.info("Starting Meshtastic AI listener...")

    # Subscribe to receive events (only once)
    pub.subscribe(on_receive, "meshtastic.receive")

    interface = None

    try:
        while True:
            # Connect if not connected
            if interface is None:
                interface = connect_interface()
                if interface is None:
                    logger.warning(f"Retry in {RECONNECT_DELAY}s...")
                    time.sleep(RECONNECT_DELAY)
                    continue
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
                logger.warning(f"Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if interface:
            interface.close()


if __name__ == "__main__":
    main()
