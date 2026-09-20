#!/usr/bin/env python3
"""Regenerate tests/fixtures/pronto_reference.json.

The fixture freezes the output of infrared_protocols, which is the
implementation wig_export.py's vendored Pronto encoder was ported from.
Freezing it is what lets the drift guard run on CI, where the library
cannot be installed: it needs Python 3.14 and CI runs 3.12.

Run this only when you mean to track an upstream change, and read the
diff before committing it. A changed vector means the vendored encoder
and the library now disagree, which is exactly what the test exists to
catch, so a regenerated fixture should be accompanied by a matching
change in wig_export.py.

Needs Python 3.14 and infrared-protocols installed:

    pip install 'infrared-protocols==10.1.0'
    python tests/fixtures/regenerate_pronto_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

from infrared_protocols.commands.pronto import ProntoCommand

NEC = [9000, -4500, 560, -560, 560, -1690, 560, -39000]

CASES: list[tuple[str, list[int], int | None]] = [
    ("nec_38k", NEC, 38000),
    ("nec_36k", NEC, 36000),
    ("nec_40k", NEC, 40000),
    ("nec_56k", NEC, 56000),
    ("nec_default", NEC, None),
    ("short_pair", [560, -560], 38000),
    (
        "sony_12bit",
        [2400, -600, 1200, -600, 600, -600, 1200, -600, 600, -600, 600, -600, 1200, -26000],
        40000,
    ),
    ("rc5_ish", [889, -889, 1778, -1778, 889, -889, 889, -889, 1778, -90000], 36000),
    ("long_gap", [9000, -4500, 560, -60000], 38000),
    ("many_pairs", [9000, -4500] + [560, -560, 560, -1690] * 16 + [560, -39000], 38000),
]


def main() -> None:
    vectors = [
        {
            "name": name,
            "pulses": pulses,
            "carrier_hz": carrier,
            "pronto": ProntoCommand.from_raw_timings(
                list(pulses), modulation=carrier
            ).to_pronto_hex(),
        }
        for name, pulses, carrier in CASES
    ]

    payload = {
        "_comment": (
            "Frozen output of infrared_protocols "
            "ProntoCommand.from_raw_timings, the implementation "
            "wig_export.py's vendored encoder was ported from. Regenerate "
            "with tests/fixtures/regenerate_pronto_reference.py only when "
            "intentionally tracking an upstream change."
        ),
        "source": (
            "infrared_protocols.commands.pronto.ProntoCommand.from_raw_timings"
        ),
        "source_version": "10.1.0",
        "vectors": vectors,
    }

    out = Path(__file__).parent / "pronto_reference.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(vectors)} vectors")


if __name__ == "__main__":
    main()
