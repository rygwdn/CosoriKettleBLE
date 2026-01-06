# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom component for controlling Cosori smart kettles via BLE. Enables direct Bluetooth connection from Home Assistant to monitor and control kettle temperature and heating.

## Commands

```bash
# Run library tests
uv run --extra test pytest tests/library/ -v

# Run HA component tests
uv run --extra test pytest tests/ha_component/ -v

# Scan for kettle MAC address
./scan.py
```

Python environment: `uv` with Python 3.13 in `.venv/`

## Architecture

### Component Structure (`custom_components/cosori_kettle_ble/`)

**Python Library (`cosori_kettle/`):**
- `protocol.py` - BLE protocol parser and command builder
- `client.py` - BLE client and connection management
- `kettle.py` - Main kettle control interface

**Home Assistant Integration:**
- `__init__.py` - Component setup and configuration
- `config_flow.py` - Configuration UI flow
- `climate.py` - Climate entity (thermostat)
- `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py` - Entity platforms
- `coordinator.py` - Data update coordinator

**Tests:**
- `tests/library/` - Python library tests
- `tests/ha_component/` - Home Assistant component tests

### BLE Protocol (see PROTOCOL.md)

**Flow:** Home Assistant connects → polls every 1-2s → receives status via notifications
- Service: 0xFFF0, RX: 0xFFF1 (notify), TX: 0xFFF2 (write)
- Packet types: Status Request (0x22), Status ACK (0x12, 35B), Compact Status (0x22, 18B), Heating Control (0x20)
- Protocol versions: V0 (legacy), V1 (advanced features)

**Critical Details:**
- Temperatures are **Fahrenheit** (no conversion in protocol layer)
- On-base detection: byte 20 (payload[14]), only in Status ACK (35B), not compact status
- BLE TX: chunk >20 byte packets; RX: complete messages, no reassembly
- Validate checksums (V0: sum; V1: iterative subtraction)

### Home Assistant Integration

Provides Climate entity (thermostat) + individual sensors/switches/numbers. All entities are created and managed through the Home Assistant integration platform.

## Common Pitfalls

1. **Temperature:** Already in Fahrenheit - don't convert in protocol layer
2. **On-base detection:** Use payload[14] from Status ACK (35B), NOT payload[4] or compact status
3. **Checksums:** V0 ≠ V1 calculation methods

## Key Files

- **Protocol:** `PROTOCOL.md`, `custom_components/cosori_kettle_ble/cosori_kettle/protocol.py`
- **Client/behavior:** `custom_components/cosori_kettle_ble/cosori_kettle/client.py`, `custom_components/cosori_kettle_ble/cosori_kettle/kettle.py`
- **HA Integration:** `custom_components/cosori_kettle_ble/__init__.py`, `config_flow.py`, `climate.py`
- **Tests:** `tests/library/`, `tests/ha_component/`
