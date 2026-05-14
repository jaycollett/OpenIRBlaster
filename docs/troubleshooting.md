# Troubleshooting

This page covers common issues and solutions for the OpenIRBlaster.

## Power & Connection Issues

### Device won't power on
- **Check USB-C cable**: Some cables are charge-only. Try a different cable.
- **Verify power source**: Ensure your USB power source provides at least 1A at 5V.
- **Inspect solder joints**: Cold solder joints on the USB-C connector or AZ1117 regulator are common culprits.

### Device powers on but won't connect to WiFi
- **Check credentials**: Double-check your WiFi SSID and password in the ESPHome configuration.
- **2.4GHz only**: The ESP8266 only supports 2.4GHz networks, not 5GHz.
- **Signal strength**: Move the device closer to your router during initial setup.

### ESPHome can't find the device
- **Same network**: Ensure your computer running ESPHome is on the same network as the device.
- **mDNS issues**: Some routers block mDNS. Try using the device's IP address directly.
- **Firewall**: Check that your firewall allows traffic on port 6053 (ESPHome native API).

## IR Transmission Issues

### Device doesn't control my equipment
- **Line of sight**: Ensure at least one of the IR LEDs has clear line of sight to the target device.
- **Learn the codes**: Use the IR receiver to learn your device's specific codes rather than using generic ones.
- **Carrier frequency**: Most devices use 38kHz, but some use 36kHz or 40kHz.
- **Remote is RF, not IR**: Many modern remotes (Samsung One Connect, Roku Voice, some Apple TV remotes, all BT/RF universal remotes) do not emit IR at all. Verify your remote actually emits IR by pointing it at any phone camera in video mode and pressing a button - if you don't see a faint purple/white flash on the LED, the remote is RF or Bluetooth and OpenIRBlaster cannot capture it.

### IR transmission is weak or intermittent
- **Check LED orientation**: Ensure IR LEDs are installed with correct polarity (longer leg = anode).
- **MOSFET solder joint**: Verify the IRLML6344 MOSFET has good solder connections.
- **Power supply**: Weak IR can indicate insufficient current. Each LED draws ~100mA when transmitting.

### Verifying IR LED operation
- **Cellphone camera trick**: If you're unsure whether the IR LEDs are actually working, use your cellphone camera in video mode while transmitting a code. The camera sensor can detect IR light that's invisible to the naked eye - you'll see a faint purple/white glow from the LEDs when they're transmitting.

### IR receiver not learning codes
- **Distance**: Hold your remote 2-6 inches from the receiver during learning.
- **Direct aim**: Point the remote directly at the TSOP38238 receiver.
- **Check logs**: Monitor ESPHome logs to see if any signal is being received.
- **Interference**: Fluorescent lights and sunlight can interfere with IR reception.
- **Confirm the remote emits IR**: See the camera trick above. RF and Bluetooth remotes cannot be captured.
- **ESPHome sees the code but the integration doesn't react**: This indicates the `esphome.openirblaster_learned` event reached HA but the integration's learning session wasn't armed when it fired (timeout, state mismatch, or the device's `mac_address` doesn't match what was stored at setup). See [Storage Format & Manual Editing](storage-format.md) for a manual workaround until you can capture the trigger.

## Home Assistant Integration Issues

### Device shows as unavailable in HA
- **API password**: Ensure the API password matches between ESPHome config and HA.
- **Network connectivity**: Verify the device is still connected to WiFi.
- **Restart HA**: Sometimes a Home Assistant restart resolves stale connections.

### Buttons/switches don't appear in HA
- **Reload integration**: Go to Settings > Devices & Services > ESPHome > Reload.
- **Check YAML**: Verify your ESPHome config has the correct entity definitions.

## Hardware Assembly Issues

### Smoke or burning smell during power-on
**IMMEDIATELY DISCONNECT POWER**
- Check for solder bridges between adjacent pads
- Verify component polarity (especially the AZ1117 regulator)
- Inspect for reversed components

### Components getting hot
- **AZ1117 regulator**: Mild warmth is normal; hot to touch indicates a short.
- **MOSFET**: Should stay cool during normal operation.
- **ESP-12F**: Moderate warmth during WiFi activity is normal.

## Getting More Help

If you're still stuck:

1. **Check existing issues**: [GitHub Issues](https://github.com/jaycollett/OpenIRBlaster/issues)
2. **Open a new issue**: Include your ESPHome logs and describe the problem in detail
3. **Community forums**: [Home Assistant Community](https://community.home-assistant.io/)

---

*Found a solution not listed here? PRs against this file are welcome.*
