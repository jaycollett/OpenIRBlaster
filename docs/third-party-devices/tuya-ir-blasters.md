# Tuya IR Blasters

**Contributed by:** [@Stoatwblr](https://github.com/Stoatwblr) (originally posted in [issue #5](https://github.com/jaycollett/OpenIRBlaster/issues/5))

OpenIRBlaster works as a near drop-in firmware replacement for many [Tuya-branded IR blasters](https://www.aliexpress.com/w/wholesale-tuya-ir-blaster.html). The RX/TX circuitry on these units is functionally similar to the OpenIRBlaster PCB - the main difference is the GPIO assignments and the fact that most of these boards are LibreTiny-based rather than ESP8266/ESP32.

## Tested Models and Pinouts

| Tuya Model | Board    | ir_tx | ir_rx | led | btn |
|------------|----------|-------|-------|-----|-----|
| S18        | CBU      | 7     | 8     | 24  | 26  |
| S06        | CBU      | 26    | 7     | 8   | 6   |
| S06        | CB3S     | 26    | 7     | 8   | 6   |
| S18        | C3BS *   | 26    | 7     | 8   | 6   |
| S06        | W3BS *   | 5     | 14    | 13  | 7   |

\* Reported on other forums; not personally verified by the contributor.

One very small unit (~3cm across) could not be opened but worked fine using the S18/CBU pinout - these devices appear to follow predictable patterns within a model line.

## Flashing

All tested units were flashable with [tuya-cloudcutter](https://github.com/tuya-cloudcutter/tuya-cloudcutter) using the **"S18 IR Repeater"** Tuya-generic profile, plus a bit of probing to find the actual pins on your specific board.

> **Heads-up:** Tuya-cloudcutter may not work on newer firmware revisions. If the over-the-air method fails, you'll need to open the case and access the serial port directly. The contributor strongly recommends opening the case if possible to trace connections before flashing.

## ESPHome Configuration

This is a partial YAML showing the Tuya-specific pieces (LibreTiny platform, pin assignments, status LED feedback for IR activity). Merge it with the [reference factory_flash.yaml](../../hardware/firmware/factory_flash.yaml) - in particular, keep the `esphome.project.name: "jaycollett.openirblaster"` declaration so the Home Assistant integration recognizes the device.

```yaml
ota:
  platform: esphome
  password: "XXXXXX"
  on_state_change:
    then:
      - repeat:
          count: 10
          then:
            - light.turn_on: led_pulse
            - delay: 0.5s
            - light.turn_off: led_pulse
            - delay: 0.5s

text_sensor:
  - platform: libretiny
    version:
      name: ${device_name} LibreTiny Version

remote_transmitter:
  id: ir_tx
  pin: 7  # from IRSend line - adjust per the pinout table above
  carrier_duty_percent: 50%
  on_transmit:
    then:
      - light.turn_on: led_pulse
  on_complete:
    then:
      - delay: 100ms
      - light.turn_off: led_pulse

remote_receiver:
  id: ir_rx
  # ... (use the receiver block from factory_flash.yaml)
  on_raw:
    then:
      - light.turn_on: led_pulse
      - if:
          condition:
            lambda: "return id(learn_enabled);"
          then:
            # ... (learning-mode handling from factory_flash.yaml)
            - switch.turn_off: ir_learning_mode
      - delay: 1s
      - light.turn_off: led_pulse

light:
  # status_led tracks WiFi/API connectivity
  - platform: status_led
    name: "Blue LED"
    id: led_status
    output: blue_led
    internal: True

  # binary light driven on IR TX/RX for visual feedback
  - platform: binary
    name: "Pulse LED"
    id: led_pulse
    output: blue_led
    internal: True

output:
  - platform: gpio
    id: blue_led
    pin:
      number: 24  # adjust per the pinout table above
      inverted: true

binary_sensor:
  - platform: gpio
    id: btn_press
    pin:
      number: 26  # adjust per the pinout table above
      mode:
        input: true
        pullup: true
      inverted: true
    on_press:
      then:
        - light.turn_on: led_pulse
        - delay: 2.5s
        - light.turn_off: led_pulse

button:
  - platform: output
    name: "Generic Output"
    output: blue_led
    duration: 500ms

# optional - exposes the serial header for debugging
uart:
  rx_pin: RX1
  tx_pin: TX1
  baud_rate: 9600
```

## Notes

- The `led_pulse` light is driven on both IR TX and RX events to give visual confirmation the device is doing something. This is gimmickry - omit if you don't want it.
- The on-board status LED can be repurposed for any GPIO-driven feedback. The contributor used the same pattern to add a power-meter pulse counter on a hacked unit.
- More teardowns and pin variants are posted on [Elektroda](https://www.elektroda.com/).

## References

- [Issue #5](https://github.com/jaycollett/OpenIRBlaster/issues/5) - original contribution thread
- [tuya-cloudcutter](https://github.com/tuya-cloudcutter/tuya-cloudcutter) - flashing tool
- [LibreTiny ESPHome](https://docs.libretiny.eu/docs/platform/esphome/) - platform docs
