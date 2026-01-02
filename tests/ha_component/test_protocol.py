"""Test protocol implementation (ported from C++ tests)."""
import pytest

from cosori_kettle_ble.protocol import (
    CompactStatus,
    Envelope,
    ExtendedStatus,
    build_compact_status_request_payload,
    build_hello_payload,
    build_register_payload,
    build_set_baby_formula_payload,
    build_set_hold_time_payload,
    build_set_mode_payload,
    build_set_my_temp_payload,
    build_status_request_payload,
    build_stop_payload,
    parse_compact_status,
    parse_extended_status,
)
from cosori_kettle_ble.const import (
    PROTOCOL_VERSION_V0,
    PROTOCOL_VERSION_V1,
)


class TestEnvelopeBuild:
    """Test envelope building and checksum calculation."""

    def test_status_request_build(self, hex_to_bytes):
        """Test building status request."""
        payload = bytes([0x01, 0x40, 0x40, 0x00])
        env = Envelope()
        packet = env.set_message_payload(0x41, payload)

        assert len(packet) == 10  # 6 header + 4 payload
        assert packet[0] == 0xA5  # magic
        assert packet[1] == 0x22  # message type
        assert packet[2] == 0x41  # seq
        assert packet[3] == 0x04  # len_lo
        assert packet[4] == 0x00  # len_hi
        assert packet[5] == 0x72  # checksum (from real packet)
        assert packet[6:] == payload

    def test_v1_start_coffee_build(self):
        """Test building V1 start coffee command."""
        payload = bytes([0x01, 0xF0, 0xA3, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00])
        env = Envelope()
        packet = env.set_message_payload(0x03, payload)

        assert len(packet) == 15  # 6 header + 9 payload
        assert packet[0] == 0xA5
        assert packet[1] == 0x22
        assert packet[2] == 0x03
        assert packet[3] == 0x09  # len_lo
        assert packet[4] == 0x00  # len_hi
        assert packet[5] == 0x95  # checksum

    def test_v1_stop_build(self):
        """Test building V1 stop command."""
        payload = bytes([0x01, 0xF4, 0xA3, 0x00])
        env = Envelope()
        packet = env.set_message_payload(0x04, payload)

        assert len(packet) == 10
        assert packet[5] == 0x98  # checksum

    def test_set_mytemp_build(self):
        """Test building set mytemp command."""
        payload = bytes([0x01, 0xF3, 0xA3, 0x00, 0xB3])
        env = Envelope()
        packet = env.set_message_payload(0x1C, payload)

        assert len(packet) == 11
        assert packet[5] == 0xCD  # checksum


class TestEnvelopeParse:
    """Test envelope parsing from real packets."""

    def test_parse_status_request(self, hex_to_bytes):
        """Test parsing status request."""
        packet = hex_to_bytes("A5224104007201404000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        frame_type, seq, payload = frame
        assert frame_type == 0x22
        assert seq == 0x41
        assert len(payload) == 4
        assert payload == packet[6:]

    def test_parse_compact_status(self, hex_to_bytes):
        """Test parsing compact status."""
        packet = hex_to_bytes("A522B50C00B3014140000000B38F00000000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        frame_type, seq, payload = frame
        assert frame_type == 0x22
        assert seq == 0xB5
        assert len(payload) == 12

    def test_parse_extended_status_ack(self, hex_to_bytes):
        """Test parsing extended status ACK."""
        packet = hex_to_bytes("A512401D0093014040000000AF69AF0000000000010000C40E00000000003408000001")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        frame_type, seq, payload = frame
        assert frame_type == 0x12  # ACK
        assert seq == 0x40
        assert len(payload) == 29

    def test_parse_completion_notification(self, hex_to_bytes):
        """Test parsing completion notification."""
        packet = hex_to_bytes("A522980500E001F7A30020")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        frame_type, seq, payload = frame
        assert frame_type == 0x22
        assert seq == 0x98
        assert len(payload) == 5

    def test_parse_multiple_frames(self, hex_to_bytes):
        """Test parsing multiple frames in sequence."""
        packet1 = hex_to_bytes("A5221F0C0073014140000000AF6900000000")
        packet2 = hex_to_bytes("A522200C008A014140000000AF5100000000")
        packet3 = hex_to_bytes("A522210C0088014140000000AF5100010000")

        env = Envelope()
        env.append(packet1)
        env.append(packet2)
        env.append(packet3)

        frame1 = env.process_next_frame()
        assert frame1 is not None
        _, seq1, _ = frame1
        assert seq1 == 0x1F

        frame2 = env.process_next_frame()
        assert frame2 is not None
        _, seq2, _ = frame2
        assert seq2 == 0x20

        frame3 = env.process_next_frame()
        assert frame3 is not None
        _, seq3, _ = frame3
        assert seq3 == 0x21

    def test_reject_invalid_magic(self, hex_to_bytes):
        """Test rejecting packet with invalid magic."""
        packet = hex_to_bytes("FF224104007201404000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is None

    def test_handle_incomplete_packet(self, hex_to_bytes):
        """Test handling incomplete packet."""
        packet = hex_to_bytes("A5224104")  # Incomplete
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is None  # Should not be valid yet


class TestProtocolBuild:
    """Test protocol payload building."""

    def assert_message_payload(self, expected_hex, payload, seq, hex_to_bytes, bytes_to_hex):
        """Assert that the envelope matches expected hex."""
        env = Envelope()
        packet = env.set_message_payload(seq, payload)
        expected = hex_to_bytes(expected_hex)
        assert packet == expected, f"Expected {bytes_to_hex(expected)}, got {bytes_to_hex(packet)}"

    def test_build_status_request_payload(self, hex_to_bytes, bytes_to_hex):
        """Test building status request payload."""
        payload = build_status_request_payload(PROTOCOL_VERSION_V1)
        self.assert_message_payload("A5224104007201404000", payload, 0x41, hex_to_bytes, bytes_to_hex)

    def test_build_compact_status_request_payload(self, hex_to_bytes, bytes_to_hex):
        """Test building compact status request payload."""
        payload = build_compact_status_request_payload(PROTOCOL_VERSION_V1)
        self.assert_message_payload("A522B50400FD01414000", payload, 0xB5, hex_to_bytes, bytes_to_hex)

    def test_build_set_my_temp_payload(self, hex_to_bytes, bytes_to_hex):
        """Test building set mytemp payload (179°F = 0xB3)."""
        payload = build_set_my_temp_payload(PROTOCOL_VERSION_V1, 179)
        self.assert_message_payload("A5221C0500CD01F3A300B3", payload, 0x1C, hex_to_bytes, bytes_to_hex)

    def test_build_set_baby_formula_enabled(self, hex_to_bytes, bytes_to_hex):
        """Test building set baby formula payload (enabled)."""
        payload = build_set_baby_formula_payload(PROTOCOL_VERSION_V1, True)
        self.assert_message_payload("A5222505007401F5A30001", payload, 0x25, hex_to_bytes, bytes_to_hex)

    def test_build_set_baby_formula_disabled(self, hex_to_bytes, bytes_to_hex):
        """Test building set baby formula payload (disabled)."""
        payload = build_set_baby_formula_payload(PROTOCOL_VERSION_V1, False)
        self.assert_message_payload("A5221D05007D01F5A30000", payload, 0x1D, hex_to_bytes, bytes_to_hex)

    def test_build_stop_payload(self, hex_to_bytes, bytes_to_hex):
        """Test building stop payload."""
        payload = build_stop_payload(PROTOCOL_VERSION_V1)
        self.assert_message_payload("A5220404009801F4A300", payload, 0x04, hex_to_bytes, bytes_to_hex)

    def test_build_set_mode_no_hold(self, hex_to_bytes, bytes_to_hex):
        """Test building set mode payload (coffee mode, no hold)."""
        payload = build_set_mode_payload(PROTOCOL_VERSION_V1, 0x03, 0x00, 0)
        self.assert_message_payload("A5224809005001F0A3000300000000", payload, 0x48, hex_to_bytes, bytes_to_hex)

    def test_build_set_mode_with_hold(self, hex_to_bytes, bytes_to_hex):
        """Test building set mode payload (coffee mode, 35 min hold = 2100 seconds = 0x0834)."""
        payload = build_set_mode_payload(PROTOCOL_VERSION_V1, 0x03, 0xCD, 2100)
        self.assert_message_payload("A5221C09007201F0A30003CD010834", payload, 0x1C, hex_to_bytes, bytes_to_hex)

    def test_build_set_hold_time_payload(self, hex_to_bytes, bytes_to_hex):
        """Test building set hold time payload (35 min = 2100 seconds)."""
        payload = build_set_hold_time_payload(PROTOCOL_VERSION_V1, 2100)
        self.assert_message_payload("A5224908001401F2A30000013408", payload, 0x49, hex_to_bytes, bytes_to_hex)

    def test_build_register_payload(self, registration_key):
        """Test building register payload (pairing mode - 0x80)."""
        payload = build_register_payload(PROTOCOL_VERSION_V1, registration_key)

        assert len(payload) == 36  # 4-byte header + 32-byte hex key
        assert payload[0] == PROTOCOL_VERSION_V1  # 0x01
        assert payload[1] == 0x80  # CMD_REGISTER
        assert payload[2] == 0xD1  # CMD_TYPE_D1
        assert payload[3] == 0x00  # padding

        # Verify hex encoding of key (32 bytes ASCII hex)
        expected_hex = b"9903e01a3c3baa8f6c71cbb5167e7d5f"
        assert payload[4:] == expected_hex

    def test_build_hello_payload(self, registration_key):
        """Test building hello payload (reconnect - 0x81)."""
        payload = build_hello_payload(PROTOCOL_VERSION_V1, registration_key)

        assert len(payload) == 36  # 4-byte header + 32-byte hex key
        assert payload[0] == PROTOCOL_VERSION_V1  # 0x01
        assert payload[1] == 0x81  # CMD_HELLO
        assert payload[2] == 0xD1  # CMD_TYPE_D1
        assert payload[3] == 0x00  # padding

        # Verify hex encoding of key (32 bytes ASCII hex)
        expected_hex = b"9903e01a3c3baa8f6c71cbb5167e7d5f"
        assert payload[4:] == expected_hex

    def test_register_vs_hello_difference(self, registration_key):
        """Test register vs hello command ID difference."""
        register_payload = build_register_payload(PROTOCOL_VERSION_V1, registration_key)
        hello_payload = build_hello_payload(PROTOCOL_VERSION_V1, registration_key)

        assert len(register_payload) == 36
        assert len(hello_payload) == 36

        # Both should have same structure except command ID
        assert register_payload[0] == hello_payload[0]  # version
        assert register_payload[1] == 0x80  # REGISTER
        assert hello_payload[1] == 0x81  # HELLO
        assert register_payload[2] == hello_payload[2]  # type
        assert register_payload[3] == hello_payload[3]  # padding

        # Hex encoding should be identical
        assert register_payload[4:] == hello_payload[4:]

    def test_hex_encoding_all_byte_values(self):
        """Test hex encoding with all possible nibble values."""
        reg_key = bytes.fromhex("00010f10fffeabcd123456789abcdeef")
        payload = build_register_payload(PROTOCOL_VERSION_V1, reg_key)

        assert len(payload) == 36

        # Verify hex encoding: each byte becomes 2 hex chars
        expected_hex = b"00010f10fffeabcd123456789abcdeef"
        assert payload[4:] == expected_hex

    def test_protocol_version_v0_support(self, registration_key):
        """Test with V0 protocol version."""
        payload = build_register_payload(PROTOCOL_VERSION_V0, registration_key)
        assert len(payload) == 36
        assert payload[0] == PROTOCOL_VERSION_V0  # 0x00

        payload = build_hello_payload(PROTOCOL_VERSION_V0, registration_key)
        assert len(payload) == 36
        assert payload[0] == PROTOCOL_VERSION_V0  # 0x00


class TestProtocolParse:
    """Test protocol parsing."""

    def parse_envelope(self, message, hex_to_bytes):
        """Parse envelope and return payload."""
        packet = hex_to_bytes(message)
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, _, payload = frame
        return payload

    def test_parse_compact_status_idle(self, hex_to_bytes):
        """Test parsing compact status (kettle idle)."""
        payload = self.parse_envelope("a5:22:0b:0c:00:4b 01:41:40:00 01:04:d4:7b:00:00:00:00", hex_to_bytes)
        status = parse_compact_status(payload)

        assert status.valid
        assert status.stage == 0x01
        assert status.mode == 0x04
        assert status.setpoint == 212
        assert status.temp == 123

    def test_parse_compact_status_heating(self, hex_to_bytes):
        """Test parsing compact status (kettle heating)."""
        payload = self.parse_envelope("A5221D0C0068014140000101B46F00000000", hex_to_bytes)
        status = parse_compact_status(payload)

        assert status.valid
        assert status.stage == 0x01  # HEATING
        assert status.mode == 0x01  # GREEN_TEA (180°F)
        assert status.setpoint == 0xB4  # 180°F
        assert status.temp == 0x6F  # 111°F

    def test_parse_extended_status_with_hold_time(self, hex_to_bytes):
        """Test parsing extended status ACK (hold time)."""
        payload = self.parse_envelope(
            "A512 831D 00B6 0140 4000 0301 B4B5 AF01 2C01 9F00 0000 0058 0200 0000 0000 2C01 0000 01",
            hex_to_bytes
        )
        status = parse_extended_status(payload)

        assert status.valid
        assert status.stage == 0x03
        assert status.mode == 0x01
        assert status.configured_hold_time == 0x012C
        assert status.remaining_hold_time == 0x009F

    def test_parse_extended_status_off_base(self, hex_to_bytes):
        """Test parsing extended status ACK (off base)."""
        payload = self.parse_envelope(
            "A512401D0093014040000000AF69AF0000000000010000C40E00000000003408000001",
            hex_to_bytes
        )
        status = parse_extended_status(payload)

        assert status.valid
        assert status.stage == 0x00
        assert status.setpoint == 0xAF  # 175°F
        assert status.temp == 0x69  # 105°F
        assert status.my_temp == 0xAF  # 175°F
        assert status.on_base is False  # 0x01 = off base
        assert status.configured_hold_time == 0x0000
        assert status.remaining_hold_time == 0x0000
        assert status.baby_formula_enabled is False

    def test_parse_extended_status_on_base(self, hex_to_bytes):
        """Test parsing extended status ACK (on base)."""
        payload = self.parse_envelope(
            "A512871D001601404000000068B5680000000000000000580200000000002C01000001",
            hex_to_bytes
        )
        status = parse_extended_status(payload)

        assert status.valid
        assert status.setpoint == 0x68  # 104°F
        assert status.temp == 0xB5  # 181°F
        assert status.my_temp == 0x68  # 104°F
        assert status.on_base is True  # 0x00 = on base
        assert status.configured_hold_time == 0x0000
        assert status.remaining_hold_time == 0x0000
        assert status.baby_formula_enabled is False

    def test_reject_invalid_compact_status(self):
        """Test rejecting invalid compact status (too short)."""
        payload = bytes([0x01, 0x41, 0x40, 0x00, 0x00])  # Only 5 bytes
        status = parse_compact_status(payload)
        assert not status.valid

    def test_reject_invalid_extended_status(self):
        """Test rejecting invalid extended status (wrong command)."""
        payload = bytes([0x01, 0x99, 0x40, 0x00])  # Wrong command
        status = parse_extended_status(payload)
        assert not status.valid


class TestRoundTrip:
    """Test round-trip: build payload, wrap in envelope, parse back."""

    def test_status_request_round_trip(self):
        """Test status request round-trip."""
        payload = build_status_request_payload(PROTOCOL_VERSION_V1)

        env = Envelope()
        packet = env.set_message_payload(0x42, payload)

        # Parse it back
        env2 = Envelope()
        env2.append(packet)
        frame = env2.process_next_frame()

        assert frame is not None
        frame_type, seq, parsed_payload = frame
        assert seq == 0x42
        assert parsed_payload == payload

    def test_set_mytemp_round_trip(self):
        """Test set mytemp round-trip."""
        payload = build_set_my_temp_payload(PROTOCOL_VERSION_V1, 179)

        env = Envelope()
        packet = env.set_message_payload(0x1C, payload)

        # Parse it back
        env2 = Envelope()
        env2.append(packet)
        frame = env2.process_next_frame()

        assert frame is not None
        frame_type, seq, parsed_payload = frame
        assert seq == 0x1C
        assert parsed_payload[4] == 0xB3  # 179°F

    def test_compact_status_round_trip(self, hex_to_bytes):
        """Test compact status round-trip (build envelope from real packet, parse)."""
        packet = hex_to_bytes("A522B50C00B3014140000000B38F00000000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, _, payload = frame

        status = parse_compact_status(payload)
        assert status.valid
        assert status.setpoint == 0xB3
        assert status.temp == 0x8F


class TestRealPackets:
    """Test against specific real packets from stuff.md."""

    def test_start_coffee_no_hold(self, hex_to_bytes):
        """Test start coffee, no hold."""
        packet = hex_to_bytes("A5224809005001F0A3000300000000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        frame_type, seq, payload = frame
        assert seq == 0x48
        assert len(payload) == 9
        assert payload[0] == 0x01
        assert payload[1] == 0xF0
        assert payload[2] == 0xA3
        assert payload[3] == 0x00
        assert payload[4] == 0x03  # mode = coffee
        assert payload[5] == 0x00
        assert payload[6] == 0x00  # hold disabled
        assert payload[7] == 0x00  # hold time
        assert payload[8] == 0x00

    def test_stop_command(self, hex_to_bytes):
        """Test stop command."""
        packet = hex_to_bytes("A5220404009801F4A300")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, seq, payload = frame
        assert seq == 0x04
        assert len(payload) == 4
        assert payload[1] == 0xF4  # STOP command

    def test_set_mytemp_179(self, hex_to_bytes):
        """Test set mytemp to 179°F."""
        packet = hex_to_bytes("A5221C0500CD01F3A300B3")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, seq, payload = frame
        assert seq == 0x1C
        assert len(payload) == 5
        assert payload[1] == 0xF3  # SET_MY_TEMP
        assert payload[4] == 0xB3  # 179°F

    def test_set_baby_formula_on(self, hex_to_bytes):
        """Test set baby formula mode ON."""
        packet = hex_to_bytes("A5222505007401F5A30001")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, seq, payload = frame
        assert seq == 0x25
        assert payload[1] == 0xF5  # SET_BABY_FORMULA
        assert payload[4] == 0x01  # enabled

    def test_completion_notification_done(self, hex_to_bytes):
        """Test completion notification (done)."""
        packet = hex_to_bytes("A522980500E001F7A30020")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, seq, payload = frame
        assert seq == 0x98
        assert payload[1] == 0xF7  # Completion notification
        assert payload[4] == 0x20  # DONE status

    def test_hold_timer_end(self, hex_to_bytes):
        """Test completion notification (hold complete)."""
        packet = hex_to_bytes("A522E105009601F7A30021")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, _, payload = frame
        assert payload[4] == 0x21  # HOLD_COMPLETE status

    def test_delay_start(self, hex_to_bytes):
        """Test delay start (1h 3min, boil)."""
        packet = hex_to_bytes("A522290B009901F1A300C40E0400000000")
        env = Envelope()
        env.append(packet)

        frame = env.process_next_frame()
        assert frame is not None
        _, seq, payload = frame
        assert seq == 0x29
        assert len(payload) == 11
        assert payload[1] == 0xF1  # Delay start command
        # Delay: C40E = 0x0EC4 = 3780 seconds = 1h 3min
        assert payload[4] == 0xC4
        assert payload[5] == 0x0E
        assert payload[6] == 0x04  # mode = boil
        assert payload[7] == 0x00
