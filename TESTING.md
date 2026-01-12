# OpenIRBlaster Local Testing Guide

## ✅ Installation Complete

The integration has been installed to: `/mnt/ha_config/custom_components/openirblaster/`

## Step 1: Restart Home Assistant

**Option A: Via UI**
1. Go to **Settings → System → Restart**
2. Wait for HA to come back online (~30-60 seconds)

**Option B: Via Command Line**
```bash
# If using Docker
docker restart homeassistant

# If using systemd
sudo systemctl restart home-assistant@homeassistant
```

## Step 2: Add the Integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration** (bottom right)
3. Search for **"OpenIRBlaster"**
4. Click on it to start setup

### Setup Form

You'll need to provide:
- **ESPHome Device Name**: The name of your ESP device (e.g., `openirblaster-64c999`)
  - Check ESPHome dashboard or your `example_firmware.yaml` for the name
- **Device ID** (optional): Defaults to device name if not provided
- **Learning Switch Entity ID** (optional): Auto-generated as `switch.{device}_ir_learning_mode`

**Example:**
```
ESPHome Device Name: openirblaster-64c999
Device ID: (leave blank, will use device name)
Learning Switch Entity ID: (leave blank, will auto-detect)
```

## Step 3: Verify Installation

After adding the integration, you should see:

### Entities Created
1. **button.openirblaster_{device}_learn** - Start learning session
2. **button.openirblaster_{device}_send_last** - Send last learned code (debug)
3. **sensor.openirblaster_{device}_last_learned_name** - Last learned code info
4. **sensor.openirblaster_{device}_last_learned_timestamp** - When last learned
5. **sensor.openirblaster_{device}_last_learned_pulse_count** - Pulse count

### Services Available
- `openirblaster.learn_start` - Start learning programmatically
- `openirblaster.send_code` - Send a stored code
- `openirblaster.delete_code` - Delete a code
- `openirblaster.rename_code` - Rename a code

## Step 4: Test Learning Workflow

### 4.1 Start Learning
1. Find the **"Learn IR Code"** button entity in your device page
2. Press it
3. The learning switch on your ESP device should turn on (check ESPHome logs)

### 4.2 Capture IR Code
1. Point your remote at the IR receiver
2. Press a button on your remote
3. The ESP device will capture the code and send an event to HA
4. Learning mode will automatically turn off

### 4.3 Save the Code
1. Go to **Settings → Devices & Services → OpenIRBlaster → Configure**
2. You should see a form to save the pending code
3. Enter:
   - **Code Name**: Descriptive name (e.g., "TV Power", "Volume Up")
   - **Tags** (optional): Comma-separated tags (e.g., "tv, samsung")
   - **Notes** (optional): Additional notes
4. Click **Submit**

### 4.4 Verify Code Saved
1. A new button entity should appear: `button.openirblaster_{device}_{code_id}`
2. The entity will be named after your code (e.g., "TV Power")
3. Check **Developer Tools → States** to see all entities

### 4.5 Test Transmission
1. Press the newly created button entity
2. Your TV (or device) should respond to the IR command
3. Check the logs for any errors

## Step 5: Monitor Logs

### Real-time Logs
```bash
./view_logs.sh
```

### Or manually
```bash
# View log file
tail -f /mnt/ha_config/home-assistant.log | grep openirblaster

# Docker logs
docker logs -f homeassistant 2>&1 | grep openirblaster
```

### What to Look For

**Successful Integration Load:**
```
INFO custom_components.openirblaster: Setting up OpenIRBlaster integration for entry ...
INFO custom_components.openirblaster: OpenIRBlaster integration loaded successfully
```

**Learning Session:**
```
INFO custom_components.openirblaster.learning: Starting learning session for device openirblaster-64c999
INFO custom_components.openirblaster.learning: Learned code captured: 38000 Hz, 67 pulses
```

**Code Saved:**
```
INFO custom_components.openirblaster.storage: Added code TV Power (tv_power)
```

**Code Sent:**
```
INFO custom_components.openirblaster.button: Sent code tv_power
```

## Step 6: Test Automation (Optional)

Create a simple automation to test the integration:

```yaml
automation:
  - alias: "Test OpenIRBlaster"
    trigger:
      - platform: state
        entity_id: input_boolean.test_ir
        to: "on"
    action:
      - service: openirblaster.send_code
        data:
          config_entry_id: "YOUR_ENTRY_ID"  # Get from UI or logs
          code_id: "tv_power"
```

## Troubleshooting

### Integration Not Appearing
1. Check logs for errors: `./view_logs.sh`
2. Verify manifest.json is valid
3. Ensure all Python files are present
4. Restart HA again

### ESPHome Device Not Found
1. Verify device is online in ESPHome dashboard
2. Check device name matches exactly (case-sensitive)
3. Ensure ESPHome integration is working in HA
4. Check entity ID: `switch.{device}_ir_learning_mode` exists

### Learning Not Working
1. Check ESPHome logs for IR receiver activity
2. Verify learning switch turns on (check ESPHome dashboard)
3. Point remote directly at IR receiver (TSOP38238 on GPIO4)
4. Try different remote or button
5. Check event in Developer Tools → Events → Listen for `esphome.openirblaster_learned`

### Codes Not Saving
1. Check options flow in integration settings
2. Look for errors in HA logs
3. Verify storage file: `/mnt/ha_config/.storage/openirblaster_*`
4. Check permissions on .storage directory

### Transmission Not Working
1. Verify ESPHome service exists: `esphome.{device}_send_ir_raw`
2. Check logs for service call errors
3. Test service manually in Developer Tools → Services
4. Ensure IR LED is connected to GPIO14

## Updating the Integration

After making code changes:

```bash
./update_integration.sh
```

Then restart Home Assistant.

## Useful Commands

```bash
# Update integration
./update_integration.sh

# Watch logs
./view_logs.sh

# Check integration files
ls -la /mnt/ha_config/custom_components/openirblaster/

# View storage
cat /mnt/ha_config/.storage/openirblaster_*

# Check ESPHome device
# (from ESPHome dashboard or logs)
```

## Getting Help

If you encounter issues:

1. **Check Logs**: Always start with the logs
2. **Verify Device**: Ensure ESPHome device is responding
3. **Test Manually**: Use Developer Tools to test services directly
4. **Check Events**: Listen for `esphome.openirblaster_learned` events
5. **Storage**: Verify `.storage/openirblaster_*.json` file exists and is valid JSON

## Next Steps

Once basic learning/sending works:
1. Learn codes for all your remotes
2. Create automations using the codes
3. Group buttons in dashboards
4. Use services in scripts
5. Share feedback and any issues found!
