#!/usr/bin/env python3
"""Convert an OpenIRBlaster code library into HAIR .wig.json files.

    python3 tools/openirblaster_to_wig.py ~/.homeassistant/.storage/openirblaster_ABC.json

This is a thin launcher. All of the work lives in
custom_components/openirblaster/wig_export.py, which is pure stdlib and
runs on its own. If you have already removed the integration, copy that
one file anywhere and run it directly:

    python3 wig_export.py <storage file>

Run with --help for grouping and output options.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "openirblaster"

if not (_MODULE_DIR / "wig_export.py").is_file():
    sys.exit(
        f"error: could not find wig_export.py at {_MODULE_DIR}.\n"
        "Run this from a checkout of the OpenIRBlaster repository, or run\n"
        "custom_components/openirblaster/wig_export.py directly."
    )

sys.path.insert(0, str(_MODULE_DIR))

import wig_export  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(wig_export.main())
