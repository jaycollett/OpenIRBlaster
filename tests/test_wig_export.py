"""Tests for the HAIR wig export.

Two of these tests reach outside the repo when the material is there:
one imports infrared_protocols to prove the vendored Pronto encoder
matches the reference implementation, and one imports HAIR's own parser
to prove the output is accepted by the thing that has to read it. Both
skip cleanly when the dependency is absent, which is the normal case on
CI, so the documented-schema assertions below are what always runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from custom_components.openirblaster.wig_export import (
    GROUP_PREFIX,
    GROUP_TAG,
    TRAILING_GAP_US,
    WIG_FORMAT,
    WigExportError,
    build_wig,
    export_storage_data,
    export_storage_file,
    group_codes,
    main,
    normalize_pulses,
    pulses_to_pronto,
    read_storage,
    resolve_storage_file,
    slugify,
)

# A real learned code: the fixture the rest of the suite uses for a
# Samsung TV power button (tests/conftest.py mock_stored_code).
REAL_PULSES = [9000, -4500, 560, -560, 560, -1680, 560, -560]


def _storage(codes: list[dict], device_name: str = "Living Room Blaster") -> dict:
    return {
        "version": 1,
        "device": {
            "config_entry_id": "01HZABCDEFGHIJK",
            "name": device_name,
            "device_id": "openirblaster-test123",
        },
        "codes": codes,
    }


def _code(code_name: str, **overrides) -> dict:
    code = {
        "id": code_name.lower().replace(" ", "_"),
        "name": code_name,
        "carrier_hz": 38000,
        "pulses": list(REAL_PULSES),
        "created_at": "2026-04-01T12:34:56+00:00",
        "updated_at": "2026-04-01T12:34:56+00:00",
        "tags": [],
        "notes": "",
    }
    code.update(overrides)
    return code


# --- Pronto encoding -------------------------------------------------


def test_pulses_to_pronto_shape():
    """Output is space-separated lowercase 4-digit hex with a 0000 header."""
    pronto = pulses_to_pronto(REAL_PULSES, 38000)
    words = pronto.split(" ")

    assert all(len(w) == 4 for w in words)
    assert all(c in "0123456789abcdef" for w in words for c in w)
    assert words[0] == "0000", "must be the learned-code header HAIR accepts"
    # preamble is 4 words, then one word per timing
    assert len(words) == 4 + len(REAL_PULSES)
    # once-sequence burst pairs, repeat-sequence burst pairs
    assert int(words[2], 16) == len(REAL_PULSES) // 2
    assert int(words[3], 16) == 0


@pytest.mark.parametrize("carrier", [36000, 38000, 40000, 56000])
def test_carrier_survives_conversion(carrier):
    """A wig has no carrier field, so the carrier must ride in the Pronto.

    The second preamble word is the carrier as a divisor of a fixed
    reference frequency. Decoding it back must land within a fraction of
    a percent of what was captured, which is what makes a 36 kHz code
    still a 36 kHz code after export.
    """
    pronto = pulses_to_pronto(REAL_PULSES, carrier)
    freq_word = int(pronto.split(" ")[1], 16)
    decoded = round(4145146 / freq_word)

    assert abs(decoded - carrier) / carrier < 0.005, (
        f"{carrier} Hz decoded back as {decoded} Hz"
    )


def test_carrier_none_defaults_to_38khz():
    assert pulses_to_pronto(REAL_PULSES) == pulses_to_pronto(REAL_PULSES, 38000)


def test_non_default_carrier_differs_from_default():
    """A 36 kHz code must not be indistinguishable from a 38 kHz one."""
    assert pulses_to_pronto(REAL_PULSES, 36000) != pulses_to_pronto(REAL_PULSES, 38000)


def test_odd_length_pulses_rejected_by_encoder():
    with pytest.raises(WigExportError, match="odd length"):
        pulses_to_pronto(REAL_PULSES[:-1], 38000)


def test_empty_pulses_rejected():
    with pytest.raises(WigExportError, match="empty"):
        pulses_to_pronto([], 38000)


def test_timing_too_long_for_a_pronto_word():
    with pytest.raises(WigExportError, match="too long"):
        pulses_to_pronto([9000, -5_000_000], 38000)


REFERENCE_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "pronto_reference.json").read_text()
)["vectors"]


@pytest.mark.parametrize(
    "vector", REFERENCE_VECTORS, ids=[v["name"] for v in REFERENCE_VECTORS]
)
def test_matches_frozen_infrared_protocols_output(vector):
    """The vendored encoder must agree with the library it was ported from.

    These vectors are frozen output of infrared_protocols 10.1.0, checked
    into the repo so this guard runs on CI, where the library cannot be
    installed (it needs Python 3.14 and CI runs 3.12). Without the freeze
    this test skipped everywhere and guarded nothing.
    """
    assert (
        pulses_to_pronto(vector["pulses"], vector["carrier_hz"]) == vector["pronto"]
    )


def test_frozen_vectors_still_match_the_live_library():
    """Catch the fixture itself going stale against a newer library.

    Skips where infrared_protocols is absent, which is the normal case.
    The frozen test above is the one that always runs.
    """
    pronto_mod = pytest.importorskip(
        "infrared_protocols.commands.pronto",
        reason="infrared_protocols not installed (needs Python 3.14)",
    )

    for vector in REFERENCE_VECTORS:
        live = pronto_mod.ProntoCommand.from_raw_timings(
            list(vector["pulses"]), modulation=vector["carrier_hz"]
        ).to_pronto_hex()
        assert live == vector["pronto"], (
            f"fixture is stale for {vector['name']}; regenerate it with "
            "tests/fixtures/regenerate_pronto_reference.py and review the diff"
        )


def test_frequency_word_rounds_rather_than_truncates():
    """Pin the one place we knowingly differ from ESPHome's C++.

    ESPHome truncates 4145146/hz; infrared_protocols and HAIR round it.
    At 40 kHz that is 103 against 104. We follow the two implementations
    that read these files, so this is deliberate and worth pinning.
    """
    word = int(pulses_to_pronto(REAL_PULSES, 40000).split(" ")[1], 16)

    assert word == 104, "should round, matching infrared_protocols and HAIR"
    assert word != 103, "truncating would match ESPHome instead"


# --- Odd-length repair -----------------------------------------------


def test_normalize_pulses_pads_odd_and_reports():
    odd = REAL_PULSES[:-1]
    fixed, note = normalize_pulses(odd)

    assert len(fixed) == len(odd) + 1
    assert fixed[-1] == TRAILING_GAP_US
    assert fixed[:-1] == odd, "existing timings must not be altered"
    assert note is not None and "odd pulse count" in note


def test_normalize_pulses_leaves_even_alone():
    fixed, note = normalize_pulses(REAL_PULSES)
    assert fixed == REAL_PULSES
    assert note is None


def test_odd_length_code_still_exports(tmp_path):
    """The padding guard has to actually save the code, not just report it."""
    data = _storage([_code("TV Power", pulses=REAL_PULSES[:-1])])
    result = export_storage_data(data, tmp_path)

    assert result.signal_count == 1
    assert result.skipped == 0
    assert any("trailing gap" in line for line in result.receipts)

    wig = json.loads(result.files[0].read_text())
    assert len(wig["signals"]) == 1


# --- Wig documents ---------------------------------------------------


def test_build_wig_required_keys_only():
    wig, _ = build_wig("Living Room TV", [_code("Power"), _code("Volume Up")])

    assert wig["format"] == WIG_FORMAT
    assert wig["name"] == "Living Room TV"
    assert [s["alias"] for s in wig["signals"]] == ["Power", "Volume Up"]
    # Optional recipe fields carry no true value from a converter, so
    # they must be left for HAIR to default.
    for signal in wig["signals"]:
        assert set(signal) == {"alias", "pronto"}


def test_build_wig_records_provenance():
    wig, _ = build_wig(
        "TV", [_code("Power")], "openirblaster_ABC.json", "sha256:deadbeef"
    )
    assert wig["converted_from"] == "openirblaster_ABC.json"
    assert wig["converted_from_sha256"] == "sha256:deadbeef"


def test_build_wig_returns_none_when_nothing_converts():
    wig, receipts = build_wig("Empty", [_code("Broken", pulses=[])])
    assert wig is None
    assert any("no pulse data" in line for line in receipts)


def test_tags_and_notes_are_reported_not_merged():
    wig, receipts = build_wig(
        "TV", [_code("Power", tags=["tv", "lounge"], notes="Samsung remote")]
    )

    assert "notes" not in wig
    assert set(wig["signals"][0]) == {"alias", "pronto"}
    assert any("tags not carried over: tv, lounge" in r for r in receipts)
    assert any("note not carried over: Samsung remote" in r for r in receipts)


def test_code_without_a_name_is_skipped():
    wig, receipts = build_wig("TV", [_code("Power"), _code("X", name="  ")])
    assert len(wig["signals"]) == 1
    assert any("no name" in line for line in receipts)


# --- Grouping --------------------------------------------------------


def test_group_by_file_is_one_wig():
    groups = group_codes([_code("A"), _code("B")], "file", "Blaster")
    assert groups == [("Blaster", [_code("A"), _code("B")])]


def test_group_by_tag_splits_and_keeps_remainder_last():
    codes = [
        _code("Power", tags=["tv"]),
        _code("Play", tags=["soundbar"]),
        _code("Orphan"),
    ]
    names = [name for name, _ in group_codes(codes, GROUP_TAG, "Blaster")]
    assert names == ["soundbar", "tv", "Other"]


def test_group_by_prefix_uses_first_word():
    codes = [_code("TV Power"), _code("TV Mute"), _code("Soundbar Play")]
    grouped = dict(group_codes(codes, GROUP_PREFIX, "Blaster"))
    assert len(grouped["TV"]) == 2
    assert len(grouped["Soundbar"]) == 1


def test_grouping_produces_distinct_files(tmp_path):
    codes = [_code("TV Power"), _code("Soundbar Play")]
    result = export_storage_data(_storage(codes), tmp_path, group_by=GROUP_PREFIX)

    assert len(result.files) == 2
    assert {p.name for p in result.files} == {"tv.wig.json", "soundbar.wig.json"}


# --- Storage reading -------------------------------------------------


def test_read_storage_unwraps_the_ha_envelope(tmp_path):
    path = tmp_path / "openirblaster_ABC.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "minor_version": 1,
                "key": "openirblaster_ABC",
                "data": _storage([_code("Power")]),
            }
        )
    )
    assert len(read_storage(path)["codes"]) == 1


def test_read_storage_rejects_a_foreign_file(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"data": {"something": "else"}}))
    with pytest.raises(WigExportError, match="no codes array"):
        read_storage(path)


def test_export_never_modifies_the_source(tmp_path):
    source = tmp_path / "openirblaster_ABC.json"
    payload = json.dumps({"version": 1, "data": _storage([_code("Power")])})
    source.write_text(payload)

    export_storage_file(source, tmp_path / "out")

    assert source.read_text() == payload


def test_export_storage_file_stamps_the_source_hash(tmp_path):
    source = tmp_path / "openirblaster_ABC.json"
    source.write_text(json.dumps({"version": 1, "data": _storage([_code("Power")])}))

    result = export_storage_file(source, tmp_path / "out")
    wig = json.loads(result.files[0].read_text())

    assert wig["converted_from"] == "openirblaster_ABC.json"
    assert wig["converted_from_sha256"].startswith("sha256:")
    assert len(wig["converted_from_sha256"]) == len("sha256:") + 64


# --- Whole-file behaviour --------------------------------------------


def test_receipt_written_only_when_there_is_something_to_say(tmp_path):
    clean = tmp_path / "clean"
    export_storage_data(_storage([_code("Power")]), clean)
    assert not (clean / "openirblaster-export-receipt.txt").exists()

    dirty = tmp_path / "dirty"
    export_storage_data(_storage([_code("Power", tags=["tv"])]), dirty)
    assert (dirty / "openirblaster-export-receipt.txt").exists()


def test_slug_collisions_get_distinct_filenames(tmp_path):
    codes = [_code("TV Power", tags=["Living Room"]), _code("TV Mute", tags=["living room"])]
    result = export_storage_data(_storage(codes), tmp_path, group_by=GROUP_TAG)
    assert len({p.name for p in result.files}) == len(result.files)


def test_unknown_grouping_rejected(tmp_path):
    with pytest.raises(WigExportError, match="unknown grouping"):
        export_storage_data(_storage([_code("Power")]), tmp_path, group_by="nope")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Living Room TV", "living-room-tv"),
        ("TV  //  Power", "tv-power"),
        ("!!!", "openirblaster"),
        ("Bedroom-AC", "bedroom-ac"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


# --- CLI -------------------------------------------------------------


def test_cli_round_trip(tmp_path, capsys):
    source = tmp_path / "openirblaster_ABC.json"
    source.write_text(
        json.dumps({"version": 1, "data": _storage([_code("TV Power")])})
    )
    out = tmp_path / "wigs"

    assert main([str(source), "-o", str(out)]) == 0

    written = list(out.glob("*.wig.json"))
    assert len(written) == 1
    assert "1 code(s) exported" in capsys.readouterr().out


def test_cli_missing_file_exits_nonzero(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 2
    err = capsys.readouterr().err
    assert "does not exist" in err
    # The real file has no extension, so say so rather than leaving the
    # user to guess at the name they were given by older docs.
    assert ".storage/openirblaster_<entry_id>" in err
    assert "openirblaster_<entry_id>.json" not in err


# --- Forgiving storage paths -----------------------------------------
#
# The store key is written verbatim, so the file on disk is
# openirblaster_<entry_id> with no extension. Releases up to 1.3.1
# documented it with a .json suffix, and shell completion offers
# whichever of the two exists, so both spellings have to land on the
# same file.


def test_resolve_storage_file_prefers_the_path_as_given(tmp_path):
    exact = tmp_path / "openirblaster_ABC"
    exact.write_text("{}")
    decoy = tmp_path / "openirblaster_ABC.json"
    decoy.write_text("{}")

    assert resolve_storage_file(exact) == exact
    assert resolve_storage_file(decoy) == decoy


def test_resolve_storage_file_drops_a_json_suffix_that_is_not_there(tmp_path):
    real = tmp_path / "openirblaster_ABC"
    real.write_text("{}")

    assert resolve_storage_file(tmp_path / "openirblaster_ABC.json") == real


def test_resolve_storage_file_adds_a_json_suffix_when_that_is_the_file(tmp_path):
    real = tmp_path / "openirblaster_ABC.json"
    real.write_text("{}")

    assert resolve_storage_file(tmp_path / "openirblaster_ABC") == real


def test_resolve_storage_file_returns_none_when_neither_spelling_exists(tmp_path):
    assert resolve_storage_file(tmp_path / "openirblaster_ABC") is None
    assert resolve_storage_file(tmp_path / "openirblaster_ABC.json") is None


def test_cli_falls_back_from_a_wrongly_suffixed_path(tmp_path, capsys):
    source = tmp_path / "openirblaster_ABC"
    source.write_text(
        json.dumps({"version": 1, "data": _storage([_code("TV Power")])})
    )
    out = tmp_path / "wigs"

    assert main([str(tmp_path / "openirblaster_ABC.json"), "-o", str(out)]) == 0

    captured = capsys.readouterr()
    assert len(list(out.glob("*.wig.json"))) == 1
    assert "openirblaster_ABC.json does not exist" in captured.err
    assert str(source) in captured.err


def test_cli_falls_back_to_a_json_sibling(tmp_path, capsys):
    source = tmp_path / "openirblaster_ABC.json"
    source.write_text(
        json.dumps({"version": 1, "data": _storage([_code("TV Power")])})
    )
    out = tmp_path / "wigs"

    assert main([str(tmp_path / "openirblaster_ABC"), "-o", str(out)]) == 0

    captured = capsys.readouterr()
    written = list(out.glob("*.wig.json"))
    assert len(written) == 1
    assert str(source) in captured.err
    # Provenance follows the file actually read, not the path typed.
    assert json.loads(written[0].read_text())["converted_from"] == source.name


def test_cli_reports_when_nothing_converts(tmp_path, capsys):
    source = tmp_path / "openirblaster_ABC.json"
    source.write_text(
        json.dumps({"version": 1, "data": _storage([_code("Broken", pulses=[])])})
    )

    assert main([str(source), "-o", str(tmp_path / "out")]) == 1
    assert "No codes could be converted" in capsys.readouterr().err


# --- Never clobber the destination -----------------------------------


def test_existing_wig_is_never_overwritten(tmp_path):
    """The destination is HAIR's live library, not a staging area.

    A user can export, import, rename the remote, edit it, add codes, then
    re-run the export for a second blaster. Replacing the file at that
    point destroys work the tool did not create.
    """
    existing = tmp_path / "living-room-blaster.wig.json"
    preserved = '{"format": "hair-wig/3", "name": "Edited By Hand"}\n'
    existing.write_text(preserved)

    result = export_storage_data(
        _storage([_code("TV Power")], device_name="Living Room Blaster"), tmp_path
    )

    assert existing.read_text() == preserved, "an existing wig was overwritten"
    assert result.files, "the export should still write something"
    assert result.files[0] != existing
    assert result.files[0].name == "living-room-blaster-2.wig.json"
    assert any("already there" in line for line in result.receipts)


def test_repeated_exports_keep_stacking_rather_than_replacing(tmp_path):
    data = _storage([_code("TV Power")], device_name="Blaster")

    names = []
    for _ in range(3):
        result = export_storage_data(data, tmp_path)
        names.append(result.files[0].name)

    assert names == ["blaster.wig.json", "blaster-2.wig.json", "blaster-3.wig.json"]
    assert len(list(tmp_path.glob("*.wig.json"))) == 3


def test_existing_receipt_is_never_overwritten(tmp_path):
    data = _storage([_code("TV Power", tags=["tv"])])

    first = export_storage_data(data, tmp_path)
    second = export_storage_data(data, tmp_path)

    assert first.receipt_path is not None
    assert second.receipt_path is not None
    assert first.receipt_path != second.receipt_path
    assert first.receipt_path.exists()


# --- One bad code must not abort the export --------------------------


@pytest.mark.parametrize(
    "carrier", ["38kHz", "not a number", {}, [], "", "0x9000"]
)
def test_non_numeric_carrier_does_not_abort(tmp_path, carrier):
    """A hand-edited storage file must not cost the user the other codes."""
    data = _storage([_code("Bad", carrier_hz=carrier), _code("Good")])

    result = export_storage_data(data, tmp_path)

    assert result.signal_count == 2, "both codes should still export"
    wig = json.loads(result.files[0].read_text())
    assert {s["alias"] for s in wig["signals"]} == {"Bad", "Good"}


def test_non_numeric_carrier_falls_back_to_default_and_says_so(tmp_path):
    data = _storage([_code("Bad", carrier_hz="38kHz")])

    result = export_storage_data(data, tmp_path)

    wig = json.loads(result.files[0].read_text())
    # Encoded at the 38 kHz default rather than guessed at.
    assert wig["signals"][0]["pronto"] == pulses_to_pronto(REAL_PULSES, 38000)
    assert any("not a number" in line for line in result.receipts)


@pytest.mark.parametrize("bad", ["a string", 42, None, ["nested"]])
def test_non_dict_code_entry_does_not_abort(tmp_path, bad):
    data = _storage([bad, _code("Good")])

    result = export_storage_data(data, tmp_path)

    assert result.signal_count == 1
    assert any("expected an object" in line for line in result.receipts)


def test_a_whole_library_of_junk_reports_rather_than_raises(tmp_path):
    data = _storage(["junk", 7, {"id": "x"}, {"id": "y", "name": "Y", "pulses": "no"}])

    result = export_storage_data(data, tmp_path)

    assert result.files == []
    assert len(result.receipts) >= 4


# --- Acceptance by HAIR's own parser ---------------------------------


def _load_hair_wig_format():
    """Import HAIR's parser from a local checkout, or return None.

    Looks where a developer would plausibly have HAIR cloned, and honours
    an explicit HAIR_REPO override. There is deliberately no fallback to a
    temporary directory: a path that vanishes turns this into a test that
    silently stops running.
    """
    import importlib.util
    import os
    import types

    candidates = []
    if override := os.environ.get("HAIR_REPO"):
        candidates.append(Path(override) / "custom_components" / "hair")
    candidates += [
        Path.home() / "SourceCode" / "HAIR" / "custom_components" / "hair",
        Path(__file__).parent.parent.parent / "HAIR" / "custom_components" / "hair",
    ]

    root = next((c for c in candidates if (c / "wig_format.py").is_file()), None)
    if root is None:
        return None

    pkg = types.ModuleType("_hair_under_test")
    pkg.__path__ = [str(root)]
    sys.modules["_hair_under_test"] = pkg
    for name in ("const", "pronto_validator", "wig_format"):
        spec = importlib.util.spec_from_file_location(
            f"_hair_under_test.{name}", root / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"_hair_under_test.{name}"] = module
        spec.loader.exec_module(module)
    return sys.modules["_hair_under_test.wig_format"]


def test_output_parses_in_hair():
    """The file HAIR has to read must be accepted by HAIR's own parser."""
    wig_format = _load_hair_wig_format()
    if wig_format is None:
        pytest.skip("no HAIR checkout available to validate against")

    wig, _ = build_wig(
        "Living Room TV",
        [
            _code("Power", carrier_hz=38000),
            _code("Volume Up", carrier_hz=36000),
            _code("Odd", pulses=REAL_PULSES[:-1]),
        ],
        "openirblaster_ABC.json",
        "sha256:" + "0" * 64,
    )
    # build_wig does not pad; the export path does. Do what it does.
    for signal, code in zip(wig["signals"], ("Power", "Volume Up")):
        assert signal["alias"] == code

    result = wig_format.parse_wig(json.dumps(wig))

    assert result.errors == [], f"HAIR rejected the wig: {result.errors}"
    assert result.wig is not None
    assert result.wig.name == "Living Room TV"
    assert result.wig.converted_from == "openirblaster_ABC.json"


def test_every_carrier_passes_hair_pronto_validation():
    wig_format = _load_hair_wig_format()
    if wig_format is None:
        pytest.skip("no HAIR checkout available to validate against")

    validate = sys.modules["_hair_under_test.pronto_validator"].validate_pronto
    for carrier in (36000, 38000, 40000, 56000):
        outcome = validate(pulses_to_pronto(REAL_PULSES, carrier))
        assert outcome.valid, f"{carrier} Hz produced invalid Pronto: {outcome.errors}"
        assert outcome.frequency_khz == pytest.approx(carrier / 1000, rel=0.005)


def test_cli_blames_the_destination_for_a_write_failure(tmp_path, capsys):
    """An unwritable output directory must not be reported as a read error."""
    source = tmp_path / "openirblaster_ABC.json"
    source.write_text(json.dumps({"version": 1, "data": _storage([_code("Power")])}))

    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o500)
    try:
        assert main([str(source), "-o", str(blocked / "wigs")]) == 1
        err = capsys.readouterr().err
        assert "could not write" in err
        assert "could not read" not in err
    finally:
        blocked.chmod(0o700)
