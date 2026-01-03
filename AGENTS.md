# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESPHome component for controlling Cosori smart kettles via BLE. Enables Home Assistant integration through ESP32 to monitor and control kettle temperature and heating.

## Commands

```bash
# Run C++ protocol tests
make test

# Compile ESPHome firmware
uv run esphome compile cosori-kettle.build.yaml

# Full workflow (test + compile)
make run

# Scan for kettle MAC address
./scan.py
```

Python environment: `uv` with Python 3.13 in `.venv/`

## Architecture

### Component Structure (`components/cosori_kettle_ble/`)

**C++ Core (ESP32):**
- `envelope.h` - Packet framing (magic, sequence, checksum, length)
- `protocol.h/cpp` - BLE protocol parser and command builder
- `cosori_kettle_state.h/cpp` - State machine
- `cosori_kettle_ble.h/cpp` - Main component (BLE client, polling, entities)

**Python (ESPHome codegen):**
- `__init__.py` - Registration, validation, `device_id` inheritance
- `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py` - Entity platforms

**Tests:**
- `tests/test_cpp.cpp` - Protocol parsing
- `tests/test_state.cpp` - State machine

### BLE Protocol (see PROTOCOL.md)

**Flow:** ESP32 connects → polls every 1-2s → receives status via notifications
- Service: 0xFFF0, RX: 0xFFF1 (notify), TX: 0xFFF2 (write)
- Packet types: Status Request (0x22), Status ACK (0x12, 35B), Compact Status (0x22, 18B), Heating Control (0x20)
- Protocol versions: V0 (legacy), V1 (advanced features)

**Critical Details:**
- Temperatures are **Fahrenheit** (no conversion in protocol layer)
- On-base detection: byte 20 (payload[14]), only in Status ACK (35B), not compact status
- BLE TX: chunk >20 byte packets; RX: complete messages, no reassembly
- Validate checksums (V0: sum; V1: iterative subtraction)

### ESPHome Integration

Provides Climate entity (thermostat) + individual sensors/switches/numbers. Child entities inherit `device_id` from parent via `inherit_device_id()` in `__init__.py`.

## Common Pitfalls

1. **Temperature:** Already in Fahrenheit - don't convert in protocol layer
2. **On-base detection:** Use payload[14] from Status ACK (35B), NOT payload[4] or compact status
3. **Checksums:** V0 ≠ V1 calculation methods

## Key Files

- **Protocol:** `PROTOCOL.md`, `envelope.h`, `protocol.cpp`, `tests/test_cpp.cpp`
- **State/behavior:** `cosori_kettle_state.h/cpp`, `cosori_kettle_ble.cpp`
- **Config:** `__init__.py`, `cosori-kettle-example.yaml`
