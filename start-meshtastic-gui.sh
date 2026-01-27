#!/bin/bash
# Launcher script for Meshtastic AI GUI

# Kill any existing instances
pkill -f "python.*meshtastic-ai-gui" 2>/dev/null
sleep 1

# Start the app with nohup to prevent termination
cd /home/ronald/python3
nohup python3 meshtastic-ai-gui.py > /dev/null 2>&1 &

# Wait and verify it started
sleep 2
if pgrep -f "meshtastic-ai-gui" > /dev/null; then
    echo "Meshtastic AI GUI started successfully"
else
    echo "Failed to start - trying again..."
    nohup python3 meshtastic-ai-gui.py > /dev/null 2>&1 &
    sleep 2
    pgrep -f "meshtastic-ai-gui" > /dev/null && echo "Started on retry" || echo "Failed to start"
fi
