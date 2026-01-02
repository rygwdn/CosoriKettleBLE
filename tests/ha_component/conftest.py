"""Pytest fixtures for Cosori Kettle BLE tests."""
import sys
from pathlib import Path

import pytest

# Add custom_components to Python path to allow package imports
# We'll mock the Home Assistant imports below
custom_components_path = Path(__file__).parent.parent.parent / "custom_components"
sys.path.insert(0, str(custom_components_path))

# Mock homeassistant and bleak modules to avoid import errors
from unittest.mock import MagicMock
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.bluetooth'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['homeassistant.helpers.entity_platform'] = MagicMock()
sys.modules['homeassistant.data_entry_flow'] = MagicMock()
sys.modules['homeassistant.components.climate'] = MagicMock()
sys.modules['homeassistant.components.sensor'] = MagicMock()
sys.modules['homeassistant.components.binary_sensor'] = MagicMock()
sys.modules['homeassistant.components.switch'] = MagicMock()
sys.modules['bleak'] = MagicMock()
sys.modules['bleak.backends'] = MagicMock()
sys.modules['bleak.backends.device'] = MagicMock()
sys.modules['bleak.exc'] = MagicMock()
sys.modules['bleak_retry_connector'] = MagicMock()
sys.modules['voluptuous'] = MagicMock()


@pytest.fixture
def hex_to_bytes():
    """Convert hex string to bytes."""
    def _hex_to_bytes(hex_str: str) -> bytes:
        # Remove spaces and colons
        hex_str = hex_str.replace(" ", "").replace(":", "")
        return bytes.fromhex(hex_str)
    return _hex_to_bytes


@pytest.fixture
def bytes_to_hex():
    """Convert bytes to hex string."""
    def _bytes_to_hex(data: bytes) -> str:
        return data.hex().upper()
    return _bytes_to_hex


@pytest.fixture
def registration_key():
    """Sample registration key for testing."""
    return bytes.fromhex("9903e01a3c3baa8f6c71cbb5167e7d5f")
