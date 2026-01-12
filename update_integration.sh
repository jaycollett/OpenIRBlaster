#!/bin/bash
# Update the OpenIRBlaster integration in Home Assistant

set -e

HA_CONFIG="/mnt/ha_config"
INTEGRATION_NAME="openirblaster"

echo "🔄 Updating OpenIRBlaster integration..."

# Remove old pycache
echo "  Cleaning __pycache__..."
rm -rf "$HA_CONFIG/custom_components/$INTEGRATION_NAME/__pycache__"

# Copy new files
echo "  Copying files..."
cp -r "custom_components/$INTEGRATION_NAME"/* "$HA_CONFIG/custom_components/$INTEGRATION_NAME/"

echo "✅ Integration updated!"
echo ""
echo "Next steps:"
echo "1. Restart Home Assistant (Settings → System → Restart)"
echo "2. Check logs: Settings → System → Logs"
echo "3. Or run: ./view_logs.sh"
