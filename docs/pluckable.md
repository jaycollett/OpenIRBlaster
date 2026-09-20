# Plucking codes into HAIR

OpenIRBlaster is pluckable. HAIR can pull your learned codes straight out of this integration and keep them as its own, without you pointing a remote at anything or copying files around.

This page covers how it works and what was implemented. If you just want to move your codes, the [README](../README.md#moving-your-codes-to-hair) has the steps.

## Move your codes before you delete anything

Every code you learned here carries the carrier frequency measured at the moment it was captured. Home Assistant's infrared platform does not report a carrier, because ESPHome sends none through `ir_rf_proxy`, so a code you learn again later comes back at the 38 kHz default.

Most remotes are 38 kHz and would not notice. A device that runs at 36 or 40 kHz would, and for those the difference is the code working or not working. The measured value exists in one place only, the integration's storage file, and re-learning cannot recover it.

Plucking preserves it. So does the file export. Do one of them before you remove the integration or delete `.storage/openirblaster_<entry_id>.json`.

## How plucking works

HAIR does not read this integration's storage and does not talk to the hardware. It uses one seam, which is that Home Assistant's `infrared` platform lets a command be sent to a named emitter entity.

HAIR registers an emitter of its own that does not drive an LED. When a command is routed to it, it captures the command and files it as a signal. So:

```
HAIR asks OpenIRBlaster to replay "TV Power"
   through emitter = HAIR's capture entity
        -> OpenIRBlaster builds a command from its stored code
        -> infrared.async_send_command(that emitter, command)
        -> HAIR captures it and stores it
```

No infrared is broadcast during a pluck. Your devices do not react, and you can pluck a whole library at your desk.

## What is implemented

The contract is HAIR's, published at [`docs/making-your-integration-pluckable.md`](https://github.com/DAB-LABS/HAIR/blob/main/docs/making-your-integration-pluckable.md). Its four requirements map to this code as follows.

**Replay a stored code by name.** `openirblaster.send_learned_ir_command` takes a `command` field holding the name the code was learned under, for example "TV Power". Matching ignores case and surrounding whitespace, and a code id is accepted as a fallback so older scripts keep working. An unknown name raises an error listing the names that do exist.

**Accept a caller-chosen target emitter.** The `emitter_entity_id` field names the emitter to send through. Point it at an emitter on your own hardware and the code goes on the air exactly as it always has. Point it at HAIR's capture entity and HAIR keeps it instead. That one parameter is the whole trick.

**Build a real platform command.** The stored pulse array becomes an `infrared` platform `Command` whose `get_raw_timings()` returns the timings exactly as captured, in signed microseconds, positive for mark and negative for space. The stored carrier becomes the command's modulation, so a 36 kHz code arrives at HAIR as a 36 kHz code. Codes with no stored carrier default to 38 kHz.

**Await the full send.** The service awaits `infrared.async_send_command` to completion. HAIR captures inside that await, so a pluck cannot race.

Two supporting pieces. A `remote` entity per device advertises `RemoteEntityFeature.LEARN_COMMAND`, which is how HAIR's blaster picker discovers the device; without it OpenIRBlaster is never offered as something to pluck from. And [`pluckable/openirblaster.yaml`](../pluckable/openirblaster.yaml) is the registry entry describing the service shape to HAIR, validated against HAIR's own schema checker.

## Version requirements

The `infrared` platform arrived in Home Assistant 2026.4, and the shape this code sends has been current since 2026.5. HAIR's capture entity needs 2026.6, so 2026.6 is the practical floor for plucking, and that is HAIR's requirement rather than this integration's.

Nothing here is imported until the service is first called. The integration still loads and runs on Home Assistant 2024.12 with no infrared platform present, and calling the service on such a system gives a message saying so rather than a confusing failure.

## Two details worth knowing

The service accepts a `device` field and ignores it. HAIR always sends one, because vendors like Tuya group codes under an appliance name. The OpenIRBlaster library is a flat list, so there is nothing to group by, and rejecting the field would fail every pluck.

Being pluckable is additive. `remote.send_command` and the per-code buttons still transmit through your own hardware over the ESPHome service, unchanged.

## Checking it without HAIR

From Developer Tools, Actions, call `openirblaster.send_learned_ir_command` with `emitter_entity_id` set to a real emitter on your device. The code should fire. That confirms the service shape, which is the part specific to this integration.
