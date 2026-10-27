"""Guard against deprecated Home Assistant names.

HA keeps a deprecated name importable as `_DEPRECATED_<name>` until removal and
only logs a warning at runtime, so the other tests pass while the integration is
on its way to breaking. This test runs against every HA version in the CI matrix.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "custom_components" / "air_by_nature"


def _ha_imports() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("homeassistant"):
                found.extend((path.name, node.module, alias.name) for alias in node.names)
    return found


def test_scan_finds_imports() -> None:
    """The scan itself works (an empty scan would pass vacuously)."""
    assert ("sensor.py", "homeassistant.const", "UnitOfRatio") in _ha_imports()


@pytest.mark.parametrize(("file", "module", "name"), _ha_imports())
def test_no_deprecated_ha_imports(file: str, module: str, name: str) -> None:
    """Nothing is imported that HA has marked deprecated."""
    mod = importlib.import_module(module)
    assert not hasattr(mod, f"_DEPRECATED_{name}"), f"{file}: {module}.{name} is deprecated"
