"""Test fixtures.

We deliberately avoid triggering ``custom_components/mikrotik_router/__init__.py``
(which transitively imports the whole coordinator + entity stack and
therefore the whole HA core). Instead, we stub the small set of HA names
the modules-under-test actually reference, then load each target module
directly from its file via ``importlib`` — bypassing the package init.

This keeps CI fast (no ``homeassistant`` install required) and keeps the
tests focused on pure logic (uniq-id construction, login_method
translation, etc.).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "custom_components" / "mikrotik_router"


# ---------------------------------------------------------------------------
# Module stubs for the small set of HA names actually referenced.
# ---------------------------------------------------------------------------


def _make_module(name: str, **attrs: object) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _async_redact_data(data, _to_redact):  # pragma: no cover - stub
    return data


class _DtUtil:  # pragma: no cover - stub
    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)


_make_module("homeassistant")
_make_module("homeassistant.components")
_make_module(
    "homeassistant.components.diagnostics",
    async_redact_data=_async_redact_data,
)
_make_module("homeassistant.util")
_make_module("homeassistant.util.dt", utcnow=_DtUtil.utcnow)


# const.py imports homeassistant.const.Platform; stub the bits it needs.
class _Platform:  # pragma: no cover - stub
    BUTTON = "button"
    BINARY_SENSOR = "binary_sensor"
    DEVICE_TRACKER = "device_tracker"
    SENSOR = "sensor"
    SWITCH = "switch"
    UPDATE = "update"


_make_module("homeassistant.const", Platform=_Platform)


# ---------------------------------------------------------------------------
# Direct-load helpers.
# ---------------------------------------------------------------------------


def _load_module(name: str, path: Path) -> types.ModuleType:
    """Load ``path`` as ``name`` without going through any package ``__init__``.

    Registers the loaded module in ``sys.modules`` so subsequent
    ``from X import Y`` lookups find it. We also register a synthetic
    top-level ``mikrotik_router`` package so the target modules'
    ``from .const import ...`` style relative imports resolve cleanly
    without triggering the real package init.
    """
    if "mikrotik_router" not in sys.modules:
        pkg = types.ModuleType("mikrotik_router")
        pkg.__path__ = [str(SRC)]
        sys.modules["mikrotik_router"] = pkg

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load const (relative-imported by the modules under test) and the
# two modules we test. Tests then ``from mikrotik_router.X import Y``.
_load_module("mikrotik_router.const", SRC / "const.py")
_load_module("mikrotik_router.apiparser", SRC / "apiparser.py")
_load_module("mikrotik_router.mikrotikapi", SRC / "mikrotikapi.py")
