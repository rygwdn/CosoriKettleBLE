## Project Overview

Home Assistant custom component for controlling Cosori smart kettles via BLE. The integration provides direct Bluetooth control from Home Assistant to monitor temperature and control heating, with both a standalone Python library and full Home Assistant integration.

## Commands

```bash
# Run all tests
uv run pytest
```

Python environment: `uv` with Python ~3.13.0 in `.venv/`

## Architecture Overview

This project has three layers that work together:

### 1. Standalone Python Library (`custom_components/cosori_kettle_ble/cosori_kettle/`)

A reusable library for controlling Cosori kettles, usable outside Home Assistant:

- **`protocol.py`** - Low-level BLE protocol implementation
- **`client.py`** - BLE communication layer using bleak
- **`kettle.py`** - High-level async API

### 2. Home Assistant Coordinator (`coordinator.py`)

Bridges the library to Home Assistant's data model

### 3. Home Assistant Entity Platforms

Standard HA entity implementations:

- **`climate.py`** - Main thermostat UI
- **`sensor.py`** - Temperature and setpoint sensors
- **`binary_sensor.py`** - On base, heating status
- **`switch.py`** - Heating on/off control
- **`config_flow.py`** - Discovery and pairing flow

## Protocol Details

The kettle uses a proprietary BLE protocol with two versions:

### V0 (Legacy)
- Basic temperature control
- Simple checksum (sum of bytes)

### V1 (Current)
- Advanced features: delayed start, hold timers, baby formula mode
- Registration/pairing with 16-byte key
- Iterative subtraction checksum

### BLE Communication

**Service UUID:** `0xFFF0`
- **RX (Notify):** `0xFFF1` - Device → App
- **TX (Write):** `0xFFF2` - App → Device

**Frame Structure:**
```
[Magic 0xA5][Header][Length][Seq][Payload...][Checksum]
```

**Key Packet Types:**
- Status Request (CMD_POLL 0x40): 10 bytes, polls for status
- Extended Status (ACK): 35 bytes, full status response
- Compact Status (CMD_CTRL 0x41): 18 bytes, periodic unsolicited updates
- Control Commands (CMD_SET_MODE 0xF0, etc.): 9-15 bytes

**Critical Implementation Details:**
1. **Temperatures are Fahrenheit** - no conversion in protocol layer
2. **On-base detection** - byte at payload[14] in extended status only
3. **BLE TX chunking** - packets >20 bytes split into chunks
4. **BLE RX streaming** - reassemble complete frames from notification stream
5. **Sequence numbers** - increment per message (wraps at 256)
6. **ACK matching** - responses have header 0x12, match by sequence number

## Data Flow

```
┌─────────────────┐
│  Climate Entity │ ← User sets temperature/mode in UI
└────────┬────────┘
         ↓
┌─────────────────┐
│   Coordinator   │ ← Calls async_set_mode()
│   (15s polls)   │
└────────┬────────┘
         ↓
┌─────────────────┐
│  BLE Client     │ ← Sends CMD_SET_MODE frame via TX
│  (client.py)    │ ← Receives ACK/status via RX notifications
└────────┬────────┘
         ↓
┌─────────────────┐
│   Protocol      │ ← Builds frames with checksums
│  (protocol.py)  │ ← Parses incoming frames
└─────────────────┘
```

**Update Flow:**
1. Coordinator polls every 15s with status request
2. Kettle sends ACK (extended status) immediately
3. Kettle also sends compact status periodically (unsolicited)
4. Both update coordinator data → entities update → UI updates

**Command Flow:**
1. User action → entity method → coordinator method
2. Coordinator acquires lock, sends command via client
3. Client sends frame, waits for ACK (5s timeout)
4. ACK updates coordinator data → entities reflect new state

## Testing

Uses pytest with asyncio support. Key patterns:

- `@pytest.mark.asyncio` for async tests
- Mock BLE with `unittest.mock.AsyncMock` and `patch`
- Fixtures in `conftest.py` for common objects
- Mock `bluetooth.async_ble_device_from_address()` as regular function
- Test both library (protocol, client, kettle) and HA component separately

## Registration and Pairing

Protocol requires a 16-byte registration key:

1. **First-time pairing:** Kettle must be in pairing mode - press and hold the "MyBrew" button
2. **Registration command (0x80):** Sent during config flow to obtain key
3. **Hello command (0x81):** Sent on every connection with registration key
4. **Key validation:** Invalid key → ConfigEntryAuthFailed → requires re-pairing

The integration stores the registration key in the config entry and uses it for all subsequent connections.

## Important Files

- **Protocol spec:** `PROTOCOL.md` - detailed protocol documentation
- **Library docs:** `LIBRARY.md` - standalone library usage
- **Main readme:** `README.md` - user-facing documentation
- **Core library:** `custom_components/cosori_kettle_ble/cosori_kettle/`
- **HA integration:** `custom_components/cosori_kettle_ble/*.py`
- **Tests:** `tests/` - comprehensive test coverage

## Interactive Debugging and Development

For interactive debugging or standalone use of the protocol library, you can import it directly without Home Assistant dependencies:

```python
import sys
sys.path.insert(0, 'custom_components/cosori_kettle_ble')
from cosori_kettle.protocol import ...
```
