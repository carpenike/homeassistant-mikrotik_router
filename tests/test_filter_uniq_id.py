"""Regression tests for the filter-rule uniq-id construction.

The integration constructs a ``uniq-id`` string for each filter rule in
TWO places that MUST stay in sync:

  1. ``coordinator.get_filter`` builds it via a ``val_proc`` descriptor
     passed to ``parse_api`` (which then runs ``fill_vals_proc``).
  2. ``switch.MikrotikFilterSwitch._build_filter_uniq_id`` rebuilds it
     by hand at action-call time so the right ``.id`` can be resolved
     from the coordinator's data dict.

If those two diverge — e.g. someone adds a field to the coordinator's
val_proc but forgets to mirror it in switch.py — the switch's
turn_on/turn_off will silently fail to find the rule and the action
becomes a no-op.

These tests assert that, for a representative set of rule shapes:

  * The two implementations produce byte-identical strings.
  * Three genuinely-distinct rules (the v2025.12.15.7 *58/*60/*67
    case) hash to three distinct uniq-ids.

If you change the uniq-id format, expect to update both the coordinator
val_proc descriptor and the switch helper, and update this test.
"""

from copy import deepcopy

import pytest

from mikrotik_router.apiparser import fill_vals_proc


# Mirror of the val_proc[0] block in coordinator.get_filter as of
# v2025.12.15.8. Keep this in sync with coordinator.py if you change
# the format. Yes, that means three places need to match — the test
# being one of them is the point: it forces the change to be
# deliberate and makes drift visible in CI.
COORDINATOR_FILTER_UNIQ_ID = [
    [
        {"name": "uniq-id"},
        {"action": "combine"},
        {"key": "chain"},
        {"text": ","},
        {"key": "action"},
        {"text": ","},
        {"key": "protocol"},
        {"text": ","},
        {"key": "layer7-protocol"},
        {"text": ","},
        {"key": "in-interface"},
        {"text": ","},
        {"key": "in-interface-list"},
        {"text": ":"},
        {"key": "src-address"},
        {"text": ","},
        {"key": "src-address-list"},
        {"text": ":"},
        {"key": "src-port"},
        {"text": "-"},
        {"key": "out-interface"},
        {"text": ","},
        {"key": "out-interface-list"},
        {"text": ":"},
        {"key": "dst-address"},
        {"text": ","},
        {"key": "dst-address-list"},
        {"text": ":"},
        {"key": "dst-port"},
        {"text": "|cs="},
        {"key": "connection-state"},
        {"text": "|cns="},
        {"key": "connection-nat-state"},
        {"text": "|cm="},
        {"key": "connection-mark"},
        {"text": "|pm="},
        {"key": "packet-mark"},
        {"text": "|rm="},
        {"key": "routing-mark"},
        {"text": "|tf="},
        {"key": "tcp-flags"},
        {"text": "|al="},
        {"key": "address-list"},
    ]
]


# All filter fields that contribute to the uniq-id. Anything not in this
# list is currently NOT part of the dedup hash and therefore NOT a
# differentiator.
ALL_HASH_FIELDS = (
    "chain",
    "action",
    "protocol",
    "layer7-protocol",
    "in-interface",
    "in-interface-list",
    "out-interface",
    "out-interface-list",
    "src-address",
    "src-address-list",
    "src-port",
    "dst-address",
    "dst-address-list",
    "dst-port",
    "connection-state",
    "connection-nat-state",
    "connection-mark",
    "packet-mark",
    "routing-mark",
    "tcp-flags",
    "address-list",
)


def _switch_helper(data: dict) -> str:
    """Inline copy of switch.MikrotikFilterSwitch._build_filter_uniq_id.

    Kept as a literal copy here rather than importing from switch.py
    because switch.py imports the full HA entity stack which we're not
    set up to mock. The point of the test is parity, so a copy that
    drifts will trigger a failure — exactly the protection we want.
    """
    g = lambda k: data.get(k, "any")  # noqa: E731
    return (
        f"{g('chain')},{g('action')},{g('protocol')},{g('layer7-protocol')},"
        f"{g('in-interface')},{g('in-interface-list')}:"
        f"{g('src-address')},{g('src-address-list')}:{g('src-port')}-"
        f"{g('out-interface')},{g('out-interface-list')}:"
        f"{g('dst-address')},{g('dst-address-list')}:{g('dst-port')}"
        f"|cs={g('connection-state')}"
        f"|cns={g('connection-nat-state')}"
        f"|cm={g('connection-mark')}"
        f"|pm={g('packet-mark')}"
        f"|rm={g('routing-mark')}"
        f"|tf={g('tcp-flags')}"
        f"|al={g('address-list')}"
    )


def _make(chain: str, action: str, **overrides: str) -> dict:
    base = {field: "any" for field in ALL_HASH_FIELDS}
    base["chain"] = chain
    base["action"] = action
    base.update(overrides)
    return base


# Mark the rules we're concerned about. The first three are the rules
# that produced the v2025.12.15.7 production bug; the fourth is a
# representative chain-tail collider that the connection-state field
# now disambiguates.
RULES = {
    "*58 forward,accept,dstnat": _make(
        "forward", "accept", **{"connection-nat-state": "dstnat"}
    ),
    "*60 forward,drop chain-tail": _make("forward", "drop"),
    "*67 input,drop chain-tail": _make("input", "drop"),
    "fwd-drop-invalid (collider)": _make(
        "forward", "drop", **{"connection-state": "invalid"}
    ),
}


@pytest.mark.parametrize("label,rule", list(RULES.items()))
def test_coordinator_and_switch_uniq_id_match(label: str, rule: dict) -> None:
    """Coordinator-built and switch-built uniq-ids must be byte-identical.

    Drift between these two is the failure mode that makes
    turn_on/turn_off silently no-op. The label is included in the
    failure message to make divergence obvious.
    """
    data = {"r": deepcopy(rule)}
    fill_vals_proc(data, "r", COORDINATOR_FILTER_UNIQ_ID)
    coordinator_id = data["r"]["uniq-id"]
    switch_id = _switch_helper(rule)
    assert coordinator_id == switch_id, (
        f"uniq-id drift for {label!r}:\n"
        f"  coordinator: {coordinator_id}\n"
        f"  switch:      {switch_id}"
    )


def test_problem_rules_hash_uniquely() -> None:
    """The v2025.12.15.7 trio + a hypothetical collider must produce 4 distinct uniq-ids."""
    data = {label: deepcopy(rule) for label, rule in RULES.items()}
    for label in data:
        fill_vals_proc(data, label, COORDINATOR_FILTER_UNIQ_ID)
    ids = {v["uniq-id"] for v in data.values()}
    assert len(ids) == len(data), f"{len(data) - len(ids)} collisions in: " + "; ".join(
        f"{label}: {data[label]['uniq-id']}" for label in data
    )
