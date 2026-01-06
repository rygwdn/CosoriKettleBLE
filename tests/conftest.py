"""Pytest configuration for library tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Mock missing optional dependencies before any imports
sys.modules['aiousbwatcher'] = MagicMock()
sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()
sys.modules['serial.tools.list_ports_common'] = MagicMock()

# Add project root to path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# pytest-homeassistant-custom-component provides proper fixtures and mocking
# for homeassistant modules


@pytest.fixture(autouse=True)
def disable_frame_helper():
    """Disable frame helper usage checks in tests."""
    # Patch the frame.report_usage to do nothing
    with patch('homeassistant.helpers.frame.report_usage'):
        yield
