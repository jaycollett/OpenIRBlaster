#!/bin/bash
# View Home Assistant logs filtered for OpenIRBlaster

HA_CONFIG="/mnt/ha_config"

echo "📋 Watching Home Assistant logs for OpenIRBlaster..."
echo "   Press Ctrl+C to exit"
echo ""

# Try different log locations
if [ -f "$HA_CONFIG/home-assistant.log" ]; then
    tail -f "$HA_CONFIG/home-assistant.log" | grep --line-buffered -i "openirblaster\|custom_components.openirblaster"
elif command -v docker &> /dev/null && docker ps | grep -q homeassistant; then
    docker logs -f homeassistant 2>&1 | grep --line-buffered -i "openirblaster\|custom_components.openirblaster"
else
    echo "⚠️  Could not find Home Assistant logs."
    echo "    Try checking: $HA_CONFIG/home-assistant.log"
    echo "    Or use: docker logs -f homeassistant"
fi
