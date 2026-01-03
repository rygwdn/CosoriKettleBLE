"""Tests for the protocol module."""
import pytest

from custom_components.cosori_kettle_ble.cosori_kettle.protocol import (
    PROTOCOL_VERSION_V1,
    Frame,
    build_hello_frame,
    build_packet,
    build_status_request_frame,
    build_stop_frame,
    parse_extended_status,
    parse_frames,
)


def test_build_hello_frame():
    """Test building hello frame."""
    key = bytes.fromhex("aabbccddee00112233445566778899aa")
    frame = build_hello_frame(PROTOCOL_VERSION_V1, key, seq=0x1c)

    assert frame.frame_type == 0x22
    assert frame.seq == 0x1c
    assert len(frame.payload) == 36
    assert frame.payload[0] == 0x01  # version
    assert frame.payload[1] == 0x81  # CMD_HELLO


def test_build_packet():
    """Test building packet with envelope."""
    frame = Frame(frame_type=0x22, seq=0x1c, payload=bytes([0x01, 0x81, 0xD1, 0x00]))
    packet = build_packet(frame)

    assert packet[0] == 0xA5  # magic
    assert packet[1] == 0x22  # type
    assert packet[2] == 0x1c  # seq
    assert packet[3] == 4  # length low
    assert packet[4] == 0  # length high
    # packet[5] is checksum
    assert len(packet) == 10  # 6 header + 4 payload


def test_parse_frames():
    """Test parsing frames from buffer."""
    # Build a test frame
    frame = build_status_request_frame(PROTOCOL_VERSION_V1, seq=0x41)
    packet = build_packet(frame)

    # Parse it
    buffer = bytearray(packet)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 1
    assert frames[0].frame_type == 0x22
    assert frames[0].seq == 0x41
    assert consumed == len(packet)


def test_parse_extended_status():
    """Test parsing extended status."""
    # Example extended status payload (29 bytes minimum)
    # Byte offsets: [0-3]=header, [4]=stage, [5]=mode, [6]=setpoint, [7]=temp,
    # [8]=my_temp, [9]=?, [10-11]=configured_hold (LE), [12-13]=remaining_hold (LE),
    # [14]=on_base, [15-25]=padding, [26]=baby_formula
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,  # [0-3] header
        0x00,  # [4] stage (idle)
        0x00,  # [5] mode
        0xD4,  # [6] setpoint (212)
        0x5C,  # [7] temp (92)
        0x8C,  # [8] my_temp (140)
        0x00,  # [9] padding
        0x3C, 0x00,  # [10-11] configured_hold_time (60) little-endian
        0x00, 0x00,  # [12-13] remaining_hold_time (0) little-endian
        0x00,  # [14] on_base (yes = 0x00)
        0x00, 0x00, 0x00, 0x00,  # [15-18] padding
        0x00, 0x00,  # [19-20] padding
        0x00, 0x00, 0x00,  # [21-23] padding
        0x00, 0x00,  # [24-25] padding
        0x01,  # [26] baby_formula_enabled
        0x00, 0x00,  # [27-28] padding (to reach 29 bytes minimum)
    ])

    status = parse_extended_status(bytes(payload))

    assert status.valid
    assert status.stage == 0
    assert status.mode == 0
    assert status.setpoint == 212
    assert status.temp == 92
    assert status.my_temp == 140
    assert status.configured_hold_time == 60
    assert status.on_base is True
    assert status.baby_formula_enabled is True


def test_parse_extended_status_off_base():
    """Test parsing extended status when off base."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,  # [0-3] header
        0x00, 0x00, 0xD4, 0x5C, 0x8C,  # [4-8] stage, mode, setpoint, temp, my_temp
        0x00,  # [9] padding
        0x3C, 0x00,  # [10-11] configured_hold (little-endian)
        0x00, 0x00,  # [12-13] remaining_hold
        0x01,  # [14] off base (0x01)
        0x00, 0x00, 0x00, 0x00,  # [15-18] padding
        0x00, 0x00,  # [19-20] padding
        0x00, 0x00, 0x00,  # [21-23] padding
        0x00, 0x00,  # [24-25] padding
        0x00,  # [26] baby_formula
        0x00, 0x00,  # [27-28] padding (to reach 29 bytes minimum)
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid
    assert status.on_base is False


def test_parse_invalid_status():
    """Test parsing invalid status."""
    # Too short
    payload = bytes([0x01, 0x40])
    status = parse_extended_status(payload)
    assert not status.valid

    # Wrong command
    payload = bytes([0x01, 0x41] + [0x00] * 27)
    status = parse_extended_status(payload)
    assert not status.valid

    # Invalid temperature
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4,
        0xFF,  # invalid temp (255)
        0x8C,
    ] + [0x00] * 20)
    status = parse_extended_status(bytes(payload))
    assert not status.valid


def test_build_stop_frame():
    """Test building stop frame."""
    frame = build_stop_frame(PROTOCOL_VERSION_V1, seq=0x60)

    assert frame.frame_type == 0x22
    assert frame.seq == 0x60
    assert frame.payload[0] == 0x01  # version
    assert frame.payload[1] == 0xF4  # CMD_STOP
