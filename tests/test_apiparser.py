"""Tests for ``apiparser.fill_vals_proc``.

This is the function that builds derived keys (notably ``uniq-id`` and
``name``) from a list of ``val_proc`` action descriptors. Bugs in this
helper or in the ``val_proc`` blocks that feed it have caused
production-visible silent collisions twice (see the v2025.12.15.7
filter-rule fix and the v2025.12.15.8 follow-up).

These tests lock in the current behavior so future refactors do not
regress, and document the historical contract:

  * ``combine`` concatenates ``key`` and ``text`` segments in order.
  * ``key`` segments resolve via ``data[uid][key]`` if present.
  * Missing ``key`` segments substitute the literal string ``"unknown"``
    AND emit a WARNING log (deduplicated per (derived_name, missing_key)
    tuple). The substitution is preserved so RouterOS schema drift does
    not hard-crash the coordinator; the warning makes the silent
    corruption observable.
"""

import logging

import pytest

from mikrotik_router import apiparser
from mikrotik_router.apiparser import fill_vals_proc


@pytest.fixture(autouse=True)
def _reset_warned_set():
    """Clear the per-process missing-key dedup so each test sees fresh warnings."""
    apiparser._MISSING_KEY_WARNED.clear()
    yield
    apiparser._MISSING_KEY_WARNED.clear()


# Standard val_proc block used throughout the integration to build a
# uniq-id from chain/action/protocol-style fields.
NAT_UNIQ_ID = [
    [
        {"name": "uniq-id"},
        {"action": "combine"},
        {"key": "chain"},
        {"text": ","},
        {"key": "action"},
    ]
]


def test_combine_joins_key_and_text_in_order() -> None:
    data = {"r1": {"chain": "srcnat", "action": "masquerade"}}
    fill_vals_proc(data, "r1", NAT_UNIQ_ID)
    assert data["r1"]["uniq-id"] == "srcnat,masquerade"


def test_combine_substitutes_unknown_for_missing_key() -> None:
    """Missing val_proc key resolves to ``"unknown"`` (graceful fallback)."""
    data = {"r1": {"chain": "srcnat"}}  # 'action' deliberately missing
    fill_vals_proc(data, "r1", NAT_UNIQ_ID)
    assert data["r1"]["uniq-id"] == "srcnat,unknown"


def test_missing_key_emits_warning(caplog) -> None:
    """A missing key MUST log a WARNING the first time it is seen.

    This is the diagnostic rail that converts the otherwise-silent
    collision bug into something observable at runtime. If you ever
    change the warning behavior, consider whether you've made the
    silent-collision bug class harder to find in production logs.
    """
    data = {"r1": {"chain": "srcnat"}}
    with caplog.at_level(
        logging.WARNING, logger="custom_components.mikrotik_router.apiparser"
    ):
        fill_vals_proc(data, "r1", NAT_UNIQ_ID)
    msgs = [
        rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING
    ]
    assert any(
        "missing key 'action'" in m and "uniq-id" in m for m in msgs
    ), f"expected a WARNING mentioning the missing 'action' key, got: {msgs}"


def test_missing_key_warning_is_deduplicated(caplog) -> None:
    """Same (derived_name, missing_key) pair only logs once per process."""
    val_proc = NAT_UNIQ_ID
    data = {f"r{i}": {"chain": "srcnat"} for i in range(5)}
    with caplog.at_level(
        logging.WARNING, logger="custom_components.mikrotik_router.apiparser"
    ):
        for uid in data:
            fill_vals_proc(data, uid, val_proc)
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert (
        len(warnings) == 1
    ), f"expected exactly 1 deduplicated warning across 5 calls, got {len(warnings)}"


def test_combine_distinct_inputs_produce_distinct_outputs() -> None:
    """Distinct rules must hash to distinct uniq-ids.

    This is the property that the deduplication logic in
    ``coordinator.get_filter`` (and equivalents) relies on.
    """
    data = {
        "r1": {"chain": "srcnat", "action": "masquerade"},
        "r2": {"chain": "dstnat", "action": "dst-nat"},
        "r3": {"chain": "srcnat", "action": "src-nat"},
    }
    for uid in data:
        fill_vals_proc(data, uid, NAT_UNIQ_ID)
    ids = {v["uniq-id"] for v in data.values()}
    assert len(ids) == len(data), f"uniq-id collision: {ids}"


def test_multiple_val_proc_blocks_are_independent() -> None:
    """Each top-level entry in val_proc populates one derived field."""
    val_proc = [
        [
            {"name": "uniq-id"},
            {"action": "combine"},
            {"key": "chain"},
            {"text": ","},
            {"key": "action"},
        ],
        [
            {"name": "name"},
            {"action": "combine"},
            {"key": "action"},
            {"text": ":"},
            {"key": "protocol"},
        ],
    ]
    data = {"r1": {"chain": "srcnat", "action": "masquerade", "protocol": "tcp"}}
    fill_vals_proc(data, "r1", val_proc)
    assert data["r1"]["uniq-id"] == "srcnat,masquerade"
    assert data["r1"]["name"] == "masquerade:tcp"


def test_combine_with_no_uid_writes_to_top_level() -> None:
    """When ``uid`` is None, the result is written into ``data`` directly."""
    data = {"chain": "input", "action": "drop"}
    fill_vals_proc(data, None, NAT_UNIQ_ID)
    assert data["uniq-id"] == "input,drop"
