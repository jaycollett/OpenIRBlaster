"""Convert an OpenIRBlaster code library into HAIR .wig.json files.

This module is the single source of truth for the export. It is pure
stdlib with no Home Assistant imports at module level, so it works three
ways:

1. Imported by services.py for the ``openirblaster.export_to_hair``
   service, run from the UI while the integration is still installed.
2. Run directly as a script against a ``.storage`` file, for a user who
   already removed the integration:
       python3 wig_export.py ~/.homeassistant/.storage/openirblaster_ABC
3. Copied anywhere on its own. It imports nothing from this package.

The target format is HAIR's wig (https://github.com/DAB-LABS/HAIR). A
wig is one JSON file describing one remote, with raw Pronto hex as the
only payload. Required keys are ``format``, ``name`` and a non-empty
``signals`` list whose entries carry ``alias`` and ``pronto``.

Why the Pronto encoder is vendored rather than imported: the same
arithmetic lives in ``infrared_protocols.commands.pronto``, which ships
with Home Assistant 2026.4+, and in HAIR's own ``ir_command.raw_to_pronto``.
Depending on either would tie this tool to a specific HA version or to
HAIR being installed, and infrared-protocols requires Python 3.14, which
this project's CI does not run.

What is actually verified about the copy: it produces byte-identical
output to ``infrared_protocols`` 10.1.0, pinned by frozen vectors in
``tests/fixtures/pronto_reference.json`` that run everywhere, and by a
live comparison that runs wherever the library is installed.

It is NOT identical to ESPHome's ``pronto_protocol.cpp`` at every carrier.
The preamble frequency word is ``round(4145146 / hz)`` here, matching
infrared_protocols and HAIR (``ir_command.py``), while the ESPHome C++
truncates. They agree at 38 kHz and disagree at 40 kHz (104 against 103),
a 0.9% carrier difference that no receiver will notice. Matching the two
implementations that read these files is the right side to be on.

Carrier frequency survives the conversion. A wig has no carrier_hz
field, but the second word of a Pronto preamble encodes the carrier as a
divisor of a fixed reference frequency, so a code captured at 36 kHz is
still a 36 kHz code after export. The round trip is quantized to that
word, which is under 0.4% across the IR band.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

# --- Pronto encoding -------------------------------------------------
# Ported from infrared_protocols.commands.pronto.ProntoCommand, which is
# itself ported from ESPHome's pronto_protocol.cpp. Kept deliberately
# close to the original so the two can be diffed.

# The Pronto preamble's frequency word is a divisor of this.
PRONTO_REFERENCE_FREQUENCY = 4145146
PRONTO_DEFAULT_FREQUENCY = 38000
# Token 0000 marks a learned (modulated) code, the only form produced
# here. HAIR also accepts 0100, a learned code with no carrier.
PRONTO_PREAMBLE_LEARNED_TOKEN = b"\x00\x00"
# A Pronto timing word is 16 bits.
PRONTO_MAX_WORD = 0xFFFF


class WigExportError(Exception):
    """A code could not be converted. Carries a user-readable reason."""


def _time_base(modulation: int) -> float:
    """Base pulse length in microseconds for a carrier frequency."""
    return 1000000 / modulation


def _compensate_duration(value: int, time_base: float) -> int:
    """Convert one signed microsecond timing to a Pronto word.

    The 20us fudge matches the reference implementation: it compensates
    for a receiver reporting marks slightly long and spaces slightly
    short.
    """
    result = value - 20 if value > 0 else -value + 20
    return round((result + time_base / 2) / time_base)


def pulses_to_pronto(pulses: list[int], carrier_hz: int | None = None) -> str:
    """Encode signed microsecond timings as a Pronto hex string.

    Args:
        pulses: Signed microseconds, positive mark and negative space.
            This is exactly the OpenIRBlaster storage convention.
        carrier_hz: Carrier frequency. None means 38 kHz, the default
            every IR receiver in this hardware is tuned for.

    Returns:
        A space-separated lowercase hex string, for example
        "0000 006d 0004 0000 0156 00ac 0015 0017".

    Raises:
        WigExportError: The timings cannot be represented in Pronto.
    """
    if not pulses:
        raise WigExportError("pulse array is empty")
    if len(pulses) % 2:
        raise WigExportError(
            f"pulse array has an odd length ({len(pulses)}); Pronto encodes "
            "mark and space in pairs"
        )

    modulation = carrier_hz or PRONTO_DEFAULT_FREQUENCY
    if modulation <= 0:
        raise WigExportError(f"carrier frequency must be positive, got {modulation}")

    time_base = _time_base(modulation)

    words: list[int] = []
    for timing in pulses:
        word = _compensate_duration(timing, time_base)
        if word <= 0:
            raise WigExportError(
                f"timing {timing}us is too short to encode at {modulation} Hz "
                "(it rounds to zero, and Pronto timing words must not be zero)"
            )
        if word > PRONTO_MAX_WORD:
            raise WigExportError(
                f"timing {timing}us is too long to encode at {modulation} Hz "
                f"(exceeds the 16-bit Pronto word limit)"
            )
        words.append(word)

    data = b"".join(
        [
            PRONTO_PREAMBLE_LEARNED_TOKEN,
            struct.pack(">H", round(PRONTO_REFERENCE_FREQUENCY / modulation)),
            struct.pack(">H", len(pulses) // 2),  # once-sequence burst pairs
            struct.pack(">H", 0),  # repeat-sequence burst pairs
            *(struct.pack(">H", word) for word in words),
        ]
    )
    hex_text = data.hex()
    return " ".join(hex_text[i : i + 4] for i in range(0, len(hex_text), 4))


# --- Pulse array repair ----------------------------------------------

# Trailing gap appended to an odd-length capture. Long enough to read as
# an end-of-frame idle on any protocol, and it is a space, so it never
# puts extra energy on the emitter.
TRAILING_GAP_US = -38000


def normalize_pulses(pulses: list[int]) -> tuple[list[int], str | None]:
    """Return pulses safe to encode, plus a note when they were changed.

    A capture that ends on a mark has an odd element count, which Pronto
    cannot represent because it encodes burst pairs. Appending a trailing
    gap is the standard repair. It is reported rather than done silently,
    because a converter that quietly edits a payload is the thing this
    receipt exists to prevent.
    """
    if len(pulses) % 2 == 0:
        return list(pulses), None

    return (
        [*pulses, TRAILING_GAP_US],
        (
            f"odd pulse count ({len(pulses)}), appended a "
            f"{abs(TRAILING_GAP_US)}us trailing gap so it encodes as burst pairs"
        ),
    )


# --- Slugs -----------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "openirblaster") -> str:
    """Lowercase hyphen slug, matching HAIR's file naming convention."""
    slug = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    return slug or fallback


# --- Storage reading -------------------------------------------------


def read_storage(path: Path) -> dict[str, Any]:
    """Load an OpenIRBlaster .storage file and return its data block.

    Home Assistant wraps stored data in a versioned envelope, so the
    codes live under "data". A raw data block is also accepted, which is
    what the integration hands over when it calls this in-process.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WigExportError(f"{path.name} is not a JSON object")

    data = raw.get("data", raw)
    if not isinstance(data, dict):
        raise WigExportError(f"{path.name} has no usable data block")
    if not isinstance(data.get("codes"), list):
        raise WigExportError(
            f"{path.name} has no codes array; is this an OpenIRBlaster "
            "storage file?"
        )
    return data


# --- Grouping --------------------------------------------------------

GROUP_FILE = "file"
GROUP_TAG = "tag"
GROUP_PREFIX = "prefix"
GROUP_CHOICES = (GROUP_FILE, GROUP_TAG, GROUP_PREFIX)

UNGROUPED_LABEL = "Other"


def group_codes(
    codes: list[dict[str, Any]], group_by: str, default_name: str
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Split a flat code list into (remote name, codes) pairs.

    One wig is one remote, and an OpenIRBlaster library is a flat list
    per device, so anything other than "file" is a guess at the user's
    intent. The guesses are offered because a 40-button wig covering
    three devices is worse than an imperfect split the user can fix
    inside HAIR.
    """
    if group_by == GROUP_FILE:
        return [(default_name, list(codes))]

    buckets: dict[str, list[dict[str, Any]]] = {}
    for code in codes:
        if group_by == GROUP_TAG:
            tags = [t for t in (code.get("tags") or []) if str(t).strip()]
            key = str(tags[0]).strip() if tags else UNGROUPED_LABEL
        else:  # GROUP_PREFIX
            name = str(code.get("name") or "").strip()
            parts = name.split()
            key = parts[0] if len(parts) > 1 else UNGROUPED_LABEL
        buckets.setdefault(key, []).append(code)

    # Stable order, with the catch-all bucket last so it reads as the
    # remainder it is.
    ordered = sorted(k for k in buckets if k != UNGROUPED_LABEL)
    if UNGROUPED_LABEL in buckets:
        ordered.append(UNGROUPED_LABEL)
    return [(key, buckets[key]) for key in ordered]


# --- Wig building ----------------------------------------------------

WIG_FORMAT = "hair-wig/3"
WIG_SUFFIX = ".wig.json"
RECEIPT_NAME = "openirblaster-export-receipt.txt"


def build_wig(
    name: str,
    codes: list[dict[str, Any]],
    source_filename: str | None = None,
    source_sha256: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Build one wig document from a list of stored codes.

    Returns the document and a list of receipt lines describing anything
    dropped or changed. Returns (None, receipts) when no code converted,
    because a wig with an empty signals list is invalid.

    Only the required keys are written. send_count, send_spacing_ms,
    ditto_count and bypass_protocol are all optional with defaults HAIR
    applies on parse, and a converter has nothing true to say about any
    of them.
    """
    receipts: list[str] = []
    signals: list[dict[str, Any]] = []

    for index, code in enumerate(codes):
        # One bad entry must never cost a user the rest of their library.
        # Storage can be hand-edited (docs/storage-format.md documents the
        # procedure), so anything in here can be any shape. Every failure
        # below is recorded and skipped rather than raised.
        if not isinstance(code, dict):
            receipts.append(
                f"entry {index}: skipped, expected an object and found "
                f"{type(code).__name__}"
            )
            continue

        code_id = str(code.get("id") or "?")
        try:
            alias = str(code.get("name") or "").strip()
            if not alias:
                receipts.append(f"{code_id}: skipped, no name to use as an alias")
                continue

            pulses = code.get("pulses")
            if not isinstance(pulses, list) or not pulses:
                receipts.append(f"{code_id} ({alias}): skipped, no pulse data")
                continue

            try:
                pulses = [int(p) for p in pulses]
            except (TypeError, ValueError):
                receipts.append(
                    f"{code_id} ({alias}): skipped, pulses are not integers"
                )
                continue

            pulses, repair = normalize_pulses(pulses)
            if repair:
                receipts.append(f"{code_id} ({alias}): {repair}")

            carrier = code.get("carrier_hz")
            if carrier is not None and not isinstance(carrier, bool):
                try:
                    carrier = int(carrier)
                except (TypeError, ValueError):
                    receipts.append(
                        f"{code_id} ({alias}): carrier_hz is {carrier!r}, which is "
                        "not a number; encoding at the 38 kHz default instead"
                    )
                    carrier = None
            else:
                carrier = None

            pronto = pulses_to_pronto(pulses, carrier or None)

            signals.append({"alias": alias, "pronto": pronto})

            # Tags and notes have no home in a wig. They are reported so a
            # user can paste back anything they care about, rather than
            # merged into the wig's single top-level notes field where they
            # would be attributed to no particular code.
            tags = [
                str(t).strip() for t in (code.get("tags") or []) if str(t).strip()
            ]
            notes = str(code.get("notes") or "").strip()
            if tags:
                receipts.append(
                    f"{code_id} ({alias}): tags not carried over: {', '.join(tags)}"
                )
            if notes:
                receipts.append(
                    f"{code_id} ({alias}): note not carried over: {notes}"
                )
        except WigExportError as err:
            receipts.append(f"{code_id}: skipped, {err}")
        except Exception as err:  # noqa: BLE001 - one bad code must not abort the rest
            receipts.append(
                f"{code_id}: skipped, unexpected problem reading this code "
                f"({type(err).__name__}: {err})"
            )

    if not signals:
        return None, receipts

    wig: dict[str, Any] = {
        "format": WIG_FORMAT,
        "name": name,
        "signals": signals,
    }
    # Provenance. converted_from is the source file name, matching how
    # HAIR's own exporter fills it (wig_export.py uses device.source_file).
    if source_filename:
        wig["converted_from"] = source_filename
    if source_sha256:
        wig["converted_from_sha256"] = source_sha256
    return wig, receipts


def serialize_wig(wig: dict[str, Any]) -> str:
    """Render a wig the way HAIR's own serializer does."""
    return json.dumps(wig, indent=4, ensure_ascii=False) + "\n"


# --- Top level -------------------------------------------------------


class ExportResult:
    """What an export produced, for reporting to a user."""

    def __init__(self) -> None:
        self.files: list[Path] = []
        self.signal_count: int = 0
        self.skipped: int = 0
        self.receipts: list[str] = []
        self.receipt_path: Path | None = None

    @property
    def summary(self) -> str:
        parts = [
            f"{self.signal_count} code(s) exported to {len(self.files)} wig file(s)"
        ]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        return ", ".join(parts)


def export_storage_data(
    data: dict[str, Any],
    out_dir: Path,
    group_by: str = GROUP_FILE,
    source_filename: str | None = None,
    source_sha256: str | None = None,
) -> ExportResult:
    """Convert a storage data block into wig files on disk.

    Writes <out_dir>/<slug>.wig.json plus a single receipt file when
    anything was dropped or changed. Never reads or writes the source.
    """
    if group_by not in GROUP_CHOICES:
        raise WigExportError(
            f"unknown grouping {group_by!r}, expected one of {', '.join(GROUP_CHOICES)}"
        )

    codes = data.get("codes") or []
    device = data.get("device") or {}
    default_name = str(device.get("name") or "OpenIRBlaster").strip() or "OpenIRBlaster"

    result = ExportResult()
    out_dir.mkdir(parents=True, exist_ok=True)
    used_slugs: set[str] = set()

    for remote_name, group in group_codes(codes, group_by, default_name):
        wig, receipts = build_wig(
            remote_name, group, source_filename, source_sha256
        )
        result.receipts.extend(receipts)
        if wig is None:
            result.skipped += len(group)
            continue

        result.skipped += len(group) - len(wig["signals"])
        result.signal_count += len(wig["signals"])

        # Never overwrite. The destination is HAIR's live library, not a
        # staging area, so a name already on disk may be a wig the user has
        # since renamed, edited or added codes to. Re-running the export
        # (for a second blaster, say) must not destroy that work, and a
        # file it did not write is not this tool's to replace. Checking
        # used_slugs alone would only dedupe within one run.
        slug = slugify(remote_name)
        candidate, counter = slug, 2
        while (
            candidate in used_slugs
            or (out_dir / f"{candidate}{WIG_SUFFIX}").exists()
        ):
            candidate = f"{slug}-{counter}"
            counter += 1
        used_slugs.add(candidate)

        if candidate != slug:
            receipts_note = (
                f"{remote_name}: {slug}{WIG_SUFFIX} was already there, so this "
                f"was written as {candidate}{WIG_SUFFIX} instead"
            )
            result.receipts.append(receipts_note)

        path = out_dir / f"{candidate}{WIG_SUFFIX}"
        path.write_text(serialize_wig(wig), encoding="utf-8")
        result.files.append(path)

    if result.receipts:
        # Same no-clobber rule: an earlier run's receipt is a record the
        # user may still need.
        receipt_path = out_dir / RECEIPT_NAME
        counter = 2
        while receipt_path.exists():
            receipt_path = out_dir / f"openirblaster-export-receipt-{counter}.txt"
            counter += 1
        header = [
            "OpenIRBlaster to HAIR export receipt",
            "",
            "Everything below was dropped or changed during conversion.",
            "Tags and notes have no equivalent in the wig format, so they",
            "are listed here rather than merged into the wig.",
            "",
        ]
        receipt_path.write_text(
            "\n".join([*header, *result.receipts]) + "\n", encoding="utf-8"
        )
        result.receipt_path = receipt_path

    return result


def export_storage_file(
    storage_path: Path, out_dir: Path, group_by: str = GROUP_FILE
) -> ExportResult:
    """Convert a .storage file on disk into wig files."""
    raw_bytes = storage_path.read_bytes()
    digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    data = read_storage(storage_path)
    return export_storage_data(
        data,
        out_dir,
        group_by=group_by,
        source_filename=storage_path.name,
        source_sha256=digest,
    )


# --- CLI -------------------------------------------------------------


def resolve_storage_file(path: Path) -> Path | None:
    """Return the storage file the user meant, or None if there is none.

    Home Assistant writes the store key verbatim, so the real file is
    ``.storage/openirblaster_<entry_id>`` with no extension. Older
    releases of this project documented it with a ``.json`` suffix, and
    shell completion will happily hand over either name, so a path that
    is only wrong by that suffix is resolved to the file next to it.
    """
    if path.is_file():
        return path
    if path.suffix == ".json":
        sibling = path.with_name(path.name[: -len(".json")])
    else:
        sibling = path.with_name(path.name + ".json")
    if sibling.is_file():
        return sibling
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wig_export",
        description=(
            "Convert an OpenIRBlaster code library into HAIR .wig.json files. "
            "Reads a Home Assistant .storage file and never modifies it."
        ),
        epilog=(
            "Stop Home Assistant before copying the storage file, or copy it "
            "and work on the copy. Home Assistant caches .storage in memory "
            "and rewrites it on the next save."
        ),
    )
    parser.add_argument(
        "storage_file",
        type=Path,
        help="path to .storage/openirblaster_<entry_id> (no file extension)",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "where to write the wigs. Defaults to ./hair/wigs, which is "
            "where HAIR looks when placed in your Home Assistant config "
            "directory."
        ),
    )
    parser.add_argument(
        "-g",
        "--group-by",
        choices=GROUP_CHOICES,
        default=GROUP_FILE,
        help=(
            "how to split codes into remotes. file: one wig for everything "
            "(default). tag: one wig per first tag. prefix: one wig per "
            "first word of the code name."
        ),
    )
    args = parser.parse_args(argv)

    storage_file = resolve_storage_file(args.storage_file)
    if storage_file is None:
        print(f"error: {args.storage_file} does not exist", file=sys.stderr)
        print(
            "The storage file has no extension. Look for "
            ".storage/openirblaster_<entry_id>",
            file=sys.stderr,
        )
        return 2
    if storage_file != args.storage_file:
        print(
            f"note: {args.storage_file} does not exist, reading "
            f"{storage_file} instead",
            file=sys.stderr,
        )

    out_dir = args.out_dir or Path("hair/wigs")

    try:
        data = read_storage(storage_file)
        digest = "sha256:" + hashlib.sha256(storage_file.read_bytes()).hexdigest()
    except WigExportError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError) as err:
        print(f"error: could not read {storage_file}: {err}", file=sys.stderr)
        return 1

    try:
        result = export_storage_data(
            data,
            out_dir,
            group_by=args.group_by,
            source_filename=storage_file.name,
            source_sha256=digest,
        )
    except WigExportError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except OSError as err:
        print(f"error: could not write to {out_dir}: {err}", file=sys.stderr)
        return 1

    if not result.files:
        print("No codes could be converted. Nothing was written.", file=sys.stderr)
        for line in result.receipts:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(result.summary)
    for path in result.files:
        print(f"  {path}")
    if result.receipt_path is not None:
        print(f"  {result.receipt_path} ({len(result.receipts)} note(s))")
    print()
    print("Copy these into <home assistant config>/hair/wigs/ and HAIR will")
    print("pick them up. Keep your .storage file until you have checked that")
    print("the codes work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
