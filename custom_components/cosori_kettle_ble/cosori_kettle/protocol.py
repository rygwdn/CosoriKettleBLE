"""BLE protocol implementation for Cosori Kettle.

This module provides low-level protocol parsing and packet building for
the Cosori Smart Kettle BLE protocol. It handles frame construction,
parsing, checksum validation, and status decoding.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Protocol constants
FRAME_MAGIC = 0xA5
MESSAGE_HEADER_TYPE = 0x22  # A522 = A5 + 22
ACK_HEADER_TYPE = 0x12  # A512 = A5 + 12
BLE_CHUNK_SIZE = 20

# Protocol versions
PROTOCOL_VERSION_V0 = 0x00
PROTOCOL_VERSION_V1 = 0x01

# Command IDs
CMD_REGISTER = 0x80
CMD_HELLO = 0x81
CMD_POLL = 0x40
CMD_CTRL = 0x41
CMD_SET_MODE = 0xF0
CMD_DELAYED_START = 0xF1
CMD_SET_HOLD_TIME = 0xF2
CMD_SET_MY_TEMP = 0xF3
CMD_STOP = 0xF4
CMD_SET_BABY_FORMULA = 0xF5

COMMANDS_WITH_STATUS = [
    CMD_REGISTER,
    CMD_HELLO,
    CMD_SET_MODE,
    CMD_DELAYED_START,
    CMD_SET_HOLD_TIME,
    CMD_SET_MY_TEMP,
    CMD_STOP,
    CMD_SET_BABY_FORMULA,
]

# Command types
CMD_TYPE_D1 = 0xD1
CMD_TYPE_A3 = 0xA3
CMD_TYPE_40 = 0x40

# Temperature limits (Fahrenheit)
MIN_TEMP_F = 104
MAX_TEMP_F = 212
MIN_VALID_READING_F = 40
MAX_VALID_READING_F = 230

# Operating modes
MODE_BOIL = 0x04
MODE_HEAT = 0x06
MODE_GREEN_TEA = 0x01
MODE_GREEN_TEA_F = 180
MODE_OOLONG = 0x02
MODE_OOLONG_F = 195
MODE_COFFEE = 0x03
MODE_COFFEE_F = 205
MODE_MY_TEMP = 0x05

# Mode names
MODE_NAMES = {
    MODE_BOIL: "Boil",
    MODE_HEAT: "Heat",
    MODE_GREEN_TEA: "Green Tea",
    MODE_OOLONG: "Oolong",
    MODE_COFFEE: "Coffee",
    MODE_MY_TEMP: "MyBrew",
}


@dataclass
class CompactStatus:
    """Compact status from kettle."""

    stage: int
    mode: int
    setpoint: int
    temp: int
    valid: bool = False


@dataclass
class ExtendedStatus:
    """Extended status from kettle."""

    stage: int
    mode: int
    setpoint: int
    temp: int
    my_temp: int
    configured_hold_time: int
    remaining_hold_time: int
    on_base: bool
    baby_formula_enabled: bool
    valid: bool = False


@dataclass
class Frame:
    """BLE packet frame with header.

    Represents a single frame with type, sequence number, and payload.
    """

    frame_type: int
    seq: int
    payload: bytes


def build_packet(frame: Frame) -> bytes:
    """Build a complete packet with envelope header.

    Args:
        frame: Frame object with type, sequence, and payload

    Returns:
        Complete packet with envelope header and checksum
    """
    payload_len = len(frame.payload)
    packet = bytearray(6 + payload_len)

    packet[0] = FRAME_MAGIC
    packet[1] = frame.frame_type
    packet[2] = frame.seq
    packet[3] = payload_len & 0xFF
    packet[4] = (payload_len >> 8) & 0xFF
    packet[5] = 0x01  # Placeholder, will be calculated

    if frame.payload:
        packet[6:] = frame.payload

    # Calculate and set checksum
    packet[5] = _calculate_checksum(packet)

    return bytes(packet)


def split_into_packets(packet: bytes) -> list[bytes]:
    """Split packet into BLE-sized packets.

    Args:
        packet: Complete packet to split

    Returns:
        List of packets, each <= BLE_CHUNK_SIZE bytes
    """
    return [packet[i : i + BLE_CHUNK_SIZE] for i in range(0, len(packet), BLE_CHUNK_SIZE)]


def parse_frames(buffer: bytearray, max_payload_size: int = 512) -> tuple[list[Frame], int]:
    """Parse all complete frames from buffer.

    Args:
        buffer: Buffer containing received data
        max_payload_size: Maximum allowed payload size

    Returns:
        Tuple of (frames list, bytes_consumed)
    """
    frames = []
    pos = 0

    while pos < len(buffer):
        # Find frame start
        frame_start = _find_frame_start(buffer, pos)
        if frame_start >= len(buffer):
            break

        pos = frame_start

        # Validate header
        if pos + 6 > len(buffer):
            break

        if buffer[pos] != FRAME_MAGIC:
            pos += 1
            continue

        frame_type = buffer[pos + 1]
        seq = buffer[pos + 2]
        payload_len = buffer[pos + 3] | (buffer[pos + 4] << 8)
        checksum = buffer[pos + 5]

        # Validate payload length
        if payload_len > max_payload_size:
            pos += 1
            continue

        frame_len = 6 + payload_len

        # Wait for complete frame
        if pos + frame_len > len(buffer):
            break

        # Validate checksum
        frame_data = buffer[pos : pos + frame_len]
        calculated_checksum = _calculate_checksum(frame_data)

        if checksum != calculated_checksum:
            pos += 1
            continue

        # Extract payload and create frame
        payload = bytes(frame_data[6:])
        frames.append(Frame(frame_type=frame_type, seq=seq, payload=payload))

        pos += frame_len

    return frames, pos


def _find_frame_start(buffer: bytearray, start_pos: int) -> int:
    """Find next frame start (FRAME_MAGIC) in buffer."""
    for i in range(start_pos, len(buffer)):
        if buffer[i] == FRAME_MAGIC:
            return i
    return len(buffer)


def _calculate_checksum(buffer: bytes | bytearray) -> int:
    """Calculate checksum for envelope."""
    # Detect protocol version
    is_v1 = len(buffer) > 6 and buffer[6] == 0x01

    if is_v1:
        # V1: iterative subtraction
        checksum = 0
        for i, byte in enumerate(buffer):
            byte_val = 0x01 if i == 5 else byte
            checksum = (checksum - byte_val) & 0xFF
        return checksum
    else:
        # V0: sum of header bytes
        if len(buffer) < 6:
            return 0
        return (FRAME_MAGIC + buffer[1] + buffer[2] + buffer[3] + buffer[4]) & 0xFF


def parse_compact_status(payload: bytes) -> CompactStatus:
    """Parse compact status packet."""
    if len(payload) < 9 or payload[1] != CMD_CTRL:
        return CompactStatus(0, 0, 0, 0, False)

    temp = payload[7]
    if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
        return CompactStatus(0, 0, 0, 0, False)

    return CompactStatus(
        stage=payload[4],
        mode=payload[5],
        setpoint=payload[6],
        temp=temp,
        valid=True,
    )


def parse_extended_status(payload: bytes) -> ExtendedStatus:
    """Parse extended status packet."""
    if len(payload) < 29 or payload[1] != CMD_POLL:
        return ExtendedStatus(0, 0, 0, 0, 0, 0, 0, False, False, False)

    temp = payload[7]
    if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
        return ExtendedStatus(0, 0, 0, 0, 0, 0, 0, False, False, False)

    my_temp = payload[8]
    if my_temp < MIN_TEMP_F or my_temp > MAX_TEMP_F:
        my_temp = 0

    return ExtendedStatus(
        stage=payload[4],
        mode=payload[5],
        setpoint=payload[6],
        temp=temp,
        my_temp=my_temp,
        configured_hold_time=(payload[11] << 8) | payload[10],
        remaining_hold_time=(payload[13] << 8) | payload[12],
        on_base=payload[14] == 0x00,
        baby_formula_enabled=payload[26] == 0x01,
        valid=True,
    )


def detect_protocol_version(hw_version: str | None, sw_version: str | None) -> int:
    """Detect protocol version from hardware and software version strings.

    Args:
        hw_version: Hardware version string (e.g., "1.0.00")
        sw_version: Software version string (e.g., "R0007V0012")

    Returns:
        Protocol version (PROTOCOL_VERSION_V0 or PROTOCOL_VERSION_V1)

    Notes:
        - V1 protocol: Hardware 1.0.00, Software R0007V0012 and newer
        - V0 protocol: Older firmware versions
        - Defaults to V1 if version info is unavailable
    """
    # Default to V1 if no version info available
    if not hw_version and not sw_version:
        return PROTOCOL_VERSION_V1

    # Check hardware version
    if hw_version:
        # Parse hardware version (expected format: "1.0.00")
        try:
            parts = hw_version.split(".")
            if len(parts) >= 1:
                major = int(parts[0])
                # Hardware 1.x.x and above use V1 protocol
                if major >= 1:
                    return PROTOCOL_VERSION_V1
        except (ValueError, AttributeError):
            pass

    # Check software version
    if sw_version:
        # Parse software version (expected format: "R0007V0012")
        try:
            if sw_version.startswith("R") and "V" in sw_version:
                # Extract release and version numbers
                r_part = sw_version[1:sw_version.index("V")]
                v_part = sw_version[sw_version.index("V")+1:]
                release = int(r_part)
                version = int(v_part)

                # R0007V0012 and newer use V1 protocol
                if release > 7 or (release == 7 and version >= 12):
                    return PROTOCOL_VERSION_V1
                else:
                    return PROTOCOL_VERSION_V0
        except (ValueError, AttributeError):
            pass

    # Default to V1 for unknown formats
    return PROTOCOL_VERSION_V1


def parse_registration_key_from_packets(packet1: str, packet2: str, packet3: str) -> bytes:
    """Parse registration key from captured Bluetooth packets.

    The official Cosori app sends three packets when connecting:
    1. First packet (20 bytes): a5 XX:XX:XX:XX:XX 0181d100 YY:YY:YY:YY:YY:YY:YY:YY:YY:YY
    2. Second packet (20 bytes): continuation of registration key
    3. Third packet (2 bytes): final bytes of registration key

    The registration key is encoded in the payload following the hello command (0181d100).
    The key data starts at byte 10 of the first packet, continues through all of the
    second packet, and finishes with the third packet. These bytes are ASCII-encoded
    hex characters that must be decoded to get the final 16-byte registration key.

    Args:
        packet1: First packet as hex string (can include spaces/colons)
        packet2: Second packet as hex string (can include spaces/colons)
        packet3: Third packet as hex string (can include spaces/colons)

    Returns:
        16-byte registration key

    Raises:
        ValueError: If packets are malformed or don't match expected format
    """
    # Clean up input - remove spaces, colons, and convert to lowercase
    p1 = packet1.replace(" ", "").replace(":", "").lower()
    p2 = packet2.replace(" ", "").replace(":", "").lower()
    p3 = packet3.replace(" ", "").replace(":", "").lower()

    # Validate lengths (20 bytes = 40 hex chars, 2 bytes = 4 hex chars)
    if len(p1) != 40:
        raise ValueError(f"First packet must be 40 hex characters (20 bytes), got {len(p1)}")
    if len(p2) != 40:
        raise ValueError(f"Second packet must be 40 hex characters (20 bytes), got {len(p2)}")
    if len(p3) != 4:
        raise ValueError(f"Third packet must be 4 hex characters (2 bytes), got {len(p3)}")

    # Validate hex format
    try:
        bytes.fromhex(p1)
        bytes.fromhex(p2)
        bytes.fromhex(p3)
    except ValueError as e:
        raise ValueError(f"Invalid hex format in packets: {e}")

    # Parse first packet as a frame to validate it's a hello command
    try:
        packet1_bytes = bytes.fromhex(p1)
        # Check magic byte and validate it's a hello command
        if packet1_bytes[0] != FRAME_MAGIC:
            raise ValueError(f"First packet doesn't start with magic byte (0xA5), got {packet1_bytes[0]:02x}")

        # Extract payload - should contain 0181d100 or 0081d100 (hello command)
        # Packet structure: [A5][type][seq][len_lo][len_hi][checksum][payload...]
        payload_start = 6
        if len(packet1_bytes) > payload_start + 4:
            # Check for hello command (0x01 0x81 0xd1 0x00 or 0x00 0x81 0xd1 0x00)
            cmd_bytes = packet1_bytes[payload_start:payload_start+4]
            if cmd_bytes[1:4] != b'\x81\xd1\x00':
                raise ValueError(f"First packet doesn't contain hello command (0x81d100), got {cmd_bytes.hex()}")
    except (IndexError, ValueError) as e:
        raise ValueError(f"Failed to parse first packet structure: {e}")

    # Extract the registration key data
    # First packet: bytes 10-19 (10 bytes after the 0181d100 command)
    # Second packet: all 20 bytes
    # Third packet: 2 bytes
    # Total: 32 ASCII characters (64 hex chars) encoding 16-byte hex key

    # Take last 10 bytes from p1 (20 hex chars), all of p2 (40 hex chars), and all of p3 (4 hex chars)
    # Total: 64 hex chars = 32 bytes of ASCII data
    key_ascii_hex = p1[20:] + p2 + p3  # 20 + 40 + 4 = 64 hex chars = 32 bytes

    # The 32 bytes (64 hex chars) represent ASCII-encoded hex string
    # Convert to bytes to get ASCII characters
    try:
        ascii_bytes = bytes.fromhex(key_ascii_hex)
        # Decode ASCII to get the hex string of the actual key
        key_hex_string = ascii_bytes.decode('ascii')
        # Convert hex string to final 16-byte key
        registration_key = bytes.fromhex(key_hex_string)
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Failed to decode registration key from packets: {e}")

    if len(registration_key) != 16:
        raise ValueError(f"Registration key must be 16 bytes, got {len(registration_key)}")

    return registration_key
