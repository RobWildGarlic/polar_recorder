from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

ROOT = Path(__file__).resolve().parents[1]

# Ensure the repo root is on sys.path so `custom_components.*` can be imported
# and the HA loader can discover the integration.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom_components from this repository."""
    return None
