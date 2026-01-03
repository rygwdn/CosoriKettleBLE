"""Pytest configuration for library tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock homeassistant modules before importing custom_components
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.bluetooth'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['bleak_retry_connector'] = MagicMock()
sys.modules['voluptuous'] = MagicMock()

# Add project root to path so custom_components can be imported
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
