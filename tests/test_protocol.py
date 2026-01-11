"""Tests for the protocol module."""
import pytest

from custom_components.cosori_kettle_ble.cosori_kettle.protocol import (
    PROTOCOL_VERSION_V0,
    PROTOCOL_VERSION_V1,
    CompactStatus,
    ExtendedStatus,
    Frame,
    build_packet,
    parse_compact_status,
    parse_extended_status,
    parse_frames,
    split_into_packets,
)


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
    # Build a test frame manually
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
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


def test_parse_compact_status_valid():
    """Test parsing valid compact status."""
    payload = bytes([0x01, 0x41, 0x40, 0x00, 0x01, 0x04, 0xD4, 0x5C, 0x00])
    status = parse_compact_status(payload)

    assert status.valid is True
    assert status.stage == 0x01
    assert status.mode == 0x04
    assert status.setpoint == 0xD4
    assert status.temp == 0x5C


def test_parse_compact_status_too_short():
    """Test parsing compact status with insufficient bytes."""
    payload = bytes([0x01, 0x41, 0x40])
    status = parse_compact_status(payload)

    assert status.valid is False


def test_parse_compact_status_wrong_command():
    """Test parsing compact status with wrong command byte."""
    payload = bytes([0x01, 0x40] + [0x00] * 7)  # CMD_POLL instead of CMD_CTRL
    status = parse_compact_status(payload)

    assert status.valid is False


def test_parse_compact_status_invalid_temp_too_low():
    """Test parsing compact status with temperature below minimum."""
    # Temp at index 7, set to 39 (below MIN_VALID_READING_F of 40)
    payload = bytearray([0x01, 0x41, 0x40, 0x00, 0x01, 0x04, 0xD4, 39, 0x00])
    status = parse_compact_status(bytes(payload))

    assert status.valid is False


def test_parse_compact_status_invalid_temp_too_high():
    """Test parsing compact status with temperature above maximum."""
    # Temp at index 7, set to 231 (above MAX_VALID_READING_F of 230)
    payload = bytearray([0x01, 0x41, 0x40, 0x00, 0x01, 0x04, 0xD4, 231, 0x00])
    status = parse_compact_status(bytes(payload))

    assert status.valid is False


def test_parse_compact_status_edge_temp_min():
    """Test parsing compact status with temperature at minimum edge."""
    payload = bytearray([0x01, 0x41, 0x40, 0x00, 0x01, 0x04, 0xD4, 40, 0x00])
    status = parse_compact_status(bytes(payload))

    assert status.valid is True
    assert status.temp == 40


def test_parse_compact_status_edge_temp_max():
    """Test parsing compact status with temperature at maximum edge."""
    payload = bytearray([0x01, 0x41, 0x40, 0x00, 0x01, 0x04, 0xD4, 230, 0x00])
    status = parse_compact_status(bytes(payload))

    assert status.valid is True
    assert status.temp == 230


def test_split_into_packets_single():
    """Test splitting packet that fits in one BLE packet."""
    packet = bytes([0xA5, 0x22, 0x1c, 0x04, 0x00, 0x00, 0x01, 0x81, 0xD1, 0x00])
    packets = split_into_packets(packet)

    assert len(packets) == 1
    assert packets[0] == packet


def test_split_into_packets_exact_multiple():
    """Test splitting packet that is exact multiple of BLE_CHUNK_SIZE."""
    # Create packet exactly 20 bytes (one BLE_CHUNK_SIZE)
    packet = bytes([0xA5, 0x22, 0x1c] + [0x00] * 17)
    packets = split_into_packets(packet)

    assert len(packets) == 1
    assert len(packets[0]) == 20


def test_split_into_packets_two_chunks():
    """Test splitting packet into two BLE packets."""
    # 25 bytes = 20 + 5
    packet = bytes([0xA5] * 25)
    packets = split_into_packets(packet)

    assert len(packets) == 2
    assert len(packets[0]) == 20
    assert len(packets[1]) == 5


def test_split_into_packets_multiple_chunks():
    """Test splitting packet into multiple BLE packets."""
    # 50 bytes = 20 + 20 + 10
    packet = bytes([0xA5] * 50)
    packets = split_into_packets(packet)

    assert len(packets) == 3
    assert len(packets[0]) == 20
    assert len(packets[1]) == 20
    assert len(packets[2]) == 10


def test_split_into_packets_empty():
    """Test splitting empty packet."""
    packet = bytes([])
    packets = split_into_packets(packet)

    assert len(packets) == 0


def test_split_into_packets_single_byte():
    """Test splitting single byte packet."""
    packet = bytes([0xA5])
    packets = split_into_packets(packet)

    assert len(packets) == 1
    assert packets[0] == bytes([0xA5])


def test_find_frame_start_at_beginning():
    """Test finding frame start at buffer beginning."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([0xA5, 0x22, 0x1c, 0x04, 0x00])
    pos = _find_frame_start(buffer, 0)

    assert pos == 0


def test_find_frame_start_in_middle():
    """Test finding frame start in middle of buffer."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([0xFF, 0xFF, 0xA5, 0x22, 0x1c, 0x04, 0x00])
    pos = _find_frame_start(buffer, 0)

    assert pos == 2


def test_find_frame_start_after_position():
    """Test finding frame start from specific position."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([0xA5, 0xFF, 0xFF, 0xA5, 0x22])
    pos = _find_frame_start(buffer, 2)

    assert pos == 3


def test_find_frame_start_not_found():
    """Test finding frame start when magic byte not in buffer."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([0xFF, 0xFE, 0xFD, 0xFC])
    pos = _find_frame_start(buffer, 0)

    assert pos == len(buffer)


def test_find_frame_start_empty_buffer():
    """Test finding frame start in empty buffer."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([])
    pos = _find_frame_start(buffer, 0)

    assert pos == 0


def test_find_frame_start_start_beyond_buffer():
    """Test finding frame start when start position beyond buffer."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _find_frame_start

    buffer = bytearray([0xA5, 0x22, 0x1c])
    pos = _find_frame_start(buffer, 10)

    assert pos == len(buffer)


def test_calculate_checksum_v0():
    """Test checksum calculation for v0 protocol."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _calculate_checksum

    # V0 uses only header bytes: FRAME_MAGIC + type + seq + len_low + len_high
    # No payload version byte
    buffer = bytes([0xA5, 0x22, 0x1c, 0x04, 0x00, 0x00, 0x02, 0x81])  # v0: payload starts with 0x02
    checksum = _calculate_checksum(buffer)

    # Sum: 0xA5 + 0x22 + 0x1c + 0x04 + 0x00 = 0xE7 (231)
    assert checksum == 0xE7


def test_calculate_checksum_v1():
    """Test checksum calculation for v1 protocol."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _calculate_checksum

    # V1 uses iterative subtraction with all bytes
    buffer = bytes([0xA5, 0x22, 0x1c, 0x04, 0x00, 0x00, 0x01, 0x81])  # v1: payload starts with 0x01
    checksum = _calculate_checksum(buffer)

    # V1: iterative subtraction
    # checksum = 0
    # i=0: checksum = (0 - 0xA5) & 0xFF = 0x5B
    # i=1: checksum = (0x5B - 0x22) & 0xFF = 0x39
    # i=2: checksum = (0x39 - 0x1c) & 0xFF = 0x1D
    # i=3: checksum = (0x1D - 0x04) & 0xFF = 0x19
    # i=4: checksum = (0x19 - 0x00) & 0xFF = 0x19
    # i=5: checksum = (0x19 - 0x01) & 0xFF = 0x18  (0x01 used instead of 0x00)
    # i=6: checksum = (0x18 - 0x01) & 0xFF = 0x17
    # i=7: checksum = (0x17 - 0x81) & 0xFF = 0x96
    assert checksum == 0x96


def test_calculate_checksum_empty():
    """Test checksum calculation for empty buffer."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _calculate_checksum

    buffer = bytes([])
    checksum = _calculate_checksum(buffer)

    assert checksum == 0


def test_calculate_checksum_short_buffer():
    """Test checksum calculation for buffer shorter than 6 bytes."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import _calculate_checksum

    buffer = bytes([0xA5, 0x22, 0x1c])
    checksum = _calculate_checksum(buffer)

    # v0 path returns 0 for buffers < 6 bytes
    assert checksum == 0


def test_parse_frames_single_frame():
    """Test parsing single complete frame."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = build_packet(frame)

    buffer = bytearray(packet)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 1
    assert frames[0].seq == 0x41
    assert consumed == len(packet)


def test_parse_frames_multiple_frames():
    """Test parsing multiple frames from buffer."""
    frame1 = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet1 = build_packet(frame1)
    frame2 = Frame(frame_type=0x22, seq=0x42, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet2 = build_packet(frame2)

    buffer = bytearray(packet1 + packet2)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 2
    assert frames[0].seq == 0x41
    assert frames[1].seq == 0x42
    assert consumed == len(packet1) + len(packet2)


def test_parse_frames_incomplete_frame():
    """Test parsing buffer with incomplete frame."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = build_packet(frame)

    # Use only first 5 bytes (incomplete header)
    buffer = bytearray(packet[:5])
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 0
    assert consumed == 0  # No complete frame found


def test_parse_frames_incomplete_payload():
    """Test parsing buffer with complete header but incomplete payload."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = build_packet(frame)

    # Use header + partial payload
    buffer = bytearray(packet[:8])
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 0
    # Should return position where frame started
    assert consumed == 0


def test_parse_frames_invalid_checksum():
    """Test parsing frame with invalid checksum."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = bytearray(build_packet(frame))

    # Corrupt the checksum
    packet[5] = 0xFF

    buffer = bytearray(packet)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 0


def test_parse_frames_invalid_checksum_then_valid():
    """Test parsing recovery after invalid checksum."""
    frame1 = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet1 = bytearray(build_packet(frame1))
    frame2 = Frame(frame_type=0x22, seq=0x42, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet2 = build_packet(frame2)

    # Corrupt first frame's checksum
    packet1[5] = 0xFF

    buffer = bytearray(packet1 + packet2)
    frames, consumed = parse_frames(buffer)

    # Should skip first frame and parse second
    assert len(frames) == 1
    assert frames[0].seq == 0x42


def test_parse_frames_with_garbage_before():
    """Test parsing frame with garbage bytes before valid frame."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = build_packet(frame)

    garbage = bytes([0xFF, 0xFE, 0xFD, 0xFC])
    buffer = bytearray(garbage + packet)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 1
    assert frames[0].seq == 0x41
    assert consumed == len(garbage) + len(packet)


def test_parse_frames_with_garbage_between():
    """Test parsing multiple frames with garbage between them."""
    frame1 = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet1 = build_packet(frame1)
    frame2 = Frame(frame_type=0x22, seq=0x42, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet2 = build_packet(frame2)

    garbage = bytes([0xFF, 0xFE, 0xFD])
    buffer = bytearray(packet1 + garbage + packet2)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 2
    assert frames[0].seq == 0x41
    assert frames[1].seq == 0x42
    assert consumed == len(packet1) + len(garbage) + len(packet2)


def test_parse_frames_payload_size_exceeded():
    """Test parsing frame with payload size exceeding maximum."""
    frame = Frame(frame_type=0x22, seq=0x41, payload=bytes([0x01, 0x40, 0x40, 0x00]))
    packet = bytearray(build_packet(frame))

    # Manually create a frame with oversized payload length
    packet[3] = 0xFF
    packet[4] = 0xFF  # payload_len = 0xFFFF (too large)

    buffer = bytearray(packet)
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 0


def test_parse_frames_buffer_without_magic():
    """Test parsing buffer with no magic bytes."""
    buffer = bytearray([0xFF, 0xFE, 0xFD, 0xFC])
    frames, consumed = parse_frames(buffer)

    assert len(frames) == 0
    assert consumed == 0


def test_parse_extended_status_various_stages():
    """Test parsing extended status with different stage values."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,  # header
        0x05,  # stage = 5
        0x00,  # mode
        0xD4,  # setpoint
        0x5C,  # temp
        0x8C,  # my_temp
        0x00,  # padding
        0x3C, 0x00,  # configured_hold_time
        0x00, 0x00,  # remaining_hold_time
        0x00,  # on_base
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x01,  # baby_formula
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid is True
    assert status.stage == 5


def test_parse_extended_status_various_modes():
    """Test parsing extended status with different mode values."""
    for mode in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06]:
        payload = bytearray([
            0x01, 0x40, 0x40, 0x00,  # header
            0x00,  # stage
            mode,  # mode
            0xD4,  # setpoint
            0x5C,  # temp
            0x8C,  # my_temp
            0x00,
            0x3C, 0x00, 0x00, 0x00,
            0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00,
            0x00, 0x00,
        ])

        status = parse_extended_status(bytes(payload))
        assert status.valid is True
        assert status.mode == mode


def test_parse_extended_status_my_temp_below_min():
    """Test parsing extended status with my_temp below minimum."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4, 0x5C,
        0x68,  # my_temp = 104 (MIN_TEMP_F), below minimum test
        0x00,
        0x3C, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    # 104 is exactly MIN_TEMP_F, so it's valid
    assert status.valid is True
    assert status.my_temp == 104


def test_parse_extended_status_my_temp_below_min_invalid():
    """Test parsing extended status with my_temp below minimum invalid."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4, 0x5C,
        0x67,  # my_temp = 103 (below MIN_TEMP_F of 104)
        0x00,
        0x3C, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid is True
    assert status.my_temp == 0  # Should be zeroed


def test_parse_extended_status_my_temp_above_max():
    """Test parsing extended status with my_temp above maximum."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4, 0x5C,
        0xD5,  # my_temp = 213 (above MAX_TEMP_F of 212)
        0x00,
        0x3C, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid is True
    assert status.my_temp == 0  # Should be zeroed


def test_parse_extended_status_various_hold_times():
    """Test parsing extended status with various hold times."""
    # Test with 300 seconds (0x012C)
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4, 0x5C, 0x8C, 0x00,
        0x2C, 0x01,  # configured_hold_time = 300 (little-endian)
        0x64, 0x00,  # remaining_hold_time = 100 (little-endian)
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid is True
    assert status.configured_hold_time == 300
    assert status.remaining_hold_time == 100


def test_parse_extended_status_baby_formula_disabled():
    """Test parsing extended status with baby formula disabled."""
    payload = bytearray([
        0x01, 0x40, 0x40, 0x00,
        0x00, 0x00, 0xD4, 0x5C, 0x8C, 0x00,
        0x3C, 0x00, 0x00, 0x00,
        0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00,  # baby_formula_enabled = 0x00 (disabled)
        0x00, 0x00,
    ])

    status = parse_extended_status(bytes(payload))
    assert status.valid is True
    assert status.baby_formula_enabled is False


def test_parse_extended_status_all_zeros():
    """Test parsing extended status with all zero payload."""
    payload = bytes([0x00] * 29)
    status = parse_extended_status(payload)

    # Should be invalid because payload[1] != CMD_POLL (0x40)
    assert status.valid is False


def test_parse_extended_status_invalid_command():
    """Test parsing extended status with invalid command byte."""
    payload = bytearray([0x01, 0x41] + [0x00] * 27)
    status = parse_extended_status(bytes(payload))

    assert status.valid is False


def test_detect_protocol_version_v1_hw():
    """Test protocol detection with V1 hardware version."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version("1.0.00", None)
    assert version == PROTOCOL_VERSION_V1


def test_detect_protocol_version_v1_sw():
    """Test protocol detection with V1 software version."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version(None, "R0007V0012")
    assert version == PROTOCOL_VERSION_V1


def test_detect_protocol_version_v1_sw_newer():
    """Test protocol detection with newer software version."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version(None, "R0008V0001")
    assert version == PROTOCOL_VERSION_V1


def test_detect_protocol_version_v0_sw():
    """Test protocol detection with V0 software version."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version(None, "R0007V0011")
    assert version == PROTOCOL_VERSION_V0


def test_detect_protocol_version_v0_sw_older():
    """Test protocol detection with older software version."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version(None, "R0006V0001")
    assert version == PROTOCOL_VERSION_V0


def test_detect_protocol_version_default():
    """Test protocol detection defaults to V1 when no version info."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version(None, None)
    assert version == PROTOCOL_VERSION_V1


def test_detect_protocol_version_invalid_format():
    """Test protocol detection with invalid version format defaults to V1."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    version = detect_protocol_version("invalid", "invalid")
    assert version == PROTOCOL_VERSION_V1


def test_detect_protocol_version_hw_takes_precedence():
    """Test that hardware version >= 1.0.00 results in V1 regardless of SW."""
    from custom_components.cosori_kettle_ble.cosori_kettle.protocol import detect_protocol_version
    # Even with old SW, HW 1.0.00 should give V1
    version = detect_protocol_version("1.0.00", "R0006V0001")
    assert version == PROTOCOL_VERSION_V1
