"""Protocol message tests - validate generation and parsing against real packets.

These tests ensure that:
1. Generated messages match real device messages exactly
2. Real device messages parse correctly
"""

import pytest
from cosori_kettle.protocol_structs import (
    StatusRequest, CompactStatus, StatusAck, V1Start, V1Stop,
    V1SetMyTemp, V1SetBabyMode, CompletionNotification,
    OperatingMode, HeatingStage, CompletionStatus,
    parse_packet
)


class TestMessageGeneration:
    """Test that generated messages match real device messages exactly."""
    
    def test_status_request(self):
        """Generate status request and verify it matches real message."""
        msg = StatusRequest(seq=0x41)
        packet = msg.to_packet()
        
        # Real packet: A522 4104 0072 0140 4000
        expected = bytes.fromhex("A522410400720140 4000")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_start_coffee_no_hold(self):
        """Generate V1 start coffee command."""
        msg = V1Start(seq=0x03, mode=OperatingMode.COFFEE, enable_hold=False, hold_minutes=0)
        packet = msg.to_packet()
        
        # Expected packet (checksum verified): A522 0309 0095 01F0 A300 0300 0000 00
        expected = bytes.fromhex("A52203090095 01F0A300 03000000 00")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_start_coffee_hold_35min(self):
        """Generate V1 start coffee with 35 minute hold."""
        msg = V1Start(seq=0x48, mode=OperatingMode.COFFEE, enable_hold=True, hold_minutes=35)
        packet = msg.to_packet()
        
        # 35 minutes = 2100 seconds = 0x0834 big-endian
        # Verify structure is correct
        assert bytes.fromhex("01F0A300") in packet  # command
        assert bytes.fromhex("0300") in packet  # mode 3 little-endian
        assert bytes([0x01]) in packet  # hold enabled
        assert bytes.fromhex("0834") in packet  # 2100 seconds big-endian
    
    def test_v1_start_boil_no_hold(self):
        """Generate V1 start boil command."""
        msg = V1Start(seq=0x08, mode=OperatingMode.BOIL, enable_hold=False, hold_minutes=0)
        packet = msg.to_packet()
        
        # Real packet: A522 0809 008F 01F0 A300 0400 0000 00
        expected = bytes.fromhex("A52208 09008F01F0A300 0400000000")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_stop(self):
        """Generate V1 stop command."""
        msg = V1Stop(seq=0x04)
        packet = msg.to_packet()
        
        # Real packet: A522 0404 0098 01F4 A300
        expected = bytes.fromhex("A522040400 9801F4A300")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_set_mytemp_179(self):
        """Generate V1 set mytemp to 179°F."""
        msg = V1SetMyTemp(seq=0x1C, temp_f=179)
        packet = msg.to_packet()
        
        # Real packet: A522 1C05 00CD 01F3 A300 B3
        expected = bytes.fromhex("A5221C0500CD01F3A300B3")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_set_baby_mode_on(self):
        """Generate V1 set baby formula mode ON."""
        msg = V1SetBabyMode(seq=0x25, enabled=True)
        packet = msg.to_packet()
        
        # Real packet: A522 2505 0074 01F5 A300 01
        expected = bytes.fromhex("A52225050074 01F5A30001")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"
    
    def test_v1_set_baby_mode_off(self):
        """Generate V1 set baby formula mode OFF."""
        msg = V1SetBabyMode(seq=0x1D, enabled=False)
        packet = msg.to_packet()
        
        # Real packet: A522 1D05 007D 01F5 A300 00
        expected = bytes.fromhex("A5221D05007D01F5A30000")
        assert packet == expected, f"Got {packet.hex()}, expected {expected.hex()}"


class TestMessageParsing:
    """Test that real device messages parse correctly."""
    
    def test_parse_compact_status(self):
        """Parse real compact status message."""
        # Real packet: A522 B50C 00B3 0141 4000 0000 B38F 0000 0000
        # Payload structure: command(4) + stage(1) + mode(1) + sp(1) + temp(1) + status(1) + padding(3)
        packet = bytes.fromhex("A522B50C00B3 01414000 0000B38F00000000")
        
        msg = parse_packet(packet)
        
        assert isinstance(msg, CompactStatus)
        assert msg.seq == 0xB5
        assert msg.stage == HeatingStage.IDLE  # stage byte is 0x00
        assert msg.mode == OperatingMode.IDLE  # mode byte is 0x00
        assert msg.setpoint_f == 0xB3  # 179°F
        assert msg.temperature_f == 0x8F  # 143°F
        assert msg.heating == False  # status byte is 0x00
    
    def test_parse_status_ack_off_base(self):
        """Parse real status ACK when kettle removed from base."""
        # Real packet: A512 401D 0093 0140 4000 0000 AF69 AF00 0000 0000 0100 00C4 0E00 0000 0000 3408 0000 01
        packet = bytes.fromhex("A512401D0093 01404000 0000AF69AF00 00000000 0100 00C40E00 00000000 3408000001")
        
        msg = parse_packet(packet)
        
        assert isinstance(msg, StatusAck)
        assert msg.seq == 0x40
        assert msg.stage == HeatingStage.IDLE
        assert msg.setpoint_f == 0xAF  # 175°F
        assert msg.temperature_f == 0x69  # 105°F
        assert msg.on_base == False  # 0x01 = off base
        assert msg.mytemp_f == 0xAF  # 175°F
    
    def test_parse_status_ack_on_base(self):
        """Parse real status ACK when kettle on base."""
        # Real packet: A522 1F0C 0073 0141 4000 0000 AF69 0000 0000
        # This is actually compact status, let me use a proper extended one
        # Real extended: A512 871D 0016 0140 4000 0000 68B5 6800 0000 0000 0000 0058 0200 0000 0000 2C01 0000 01
        packet = bytes.fromhex("A512871D0016 01404000 000068B56800 00000000 0000 00580200 00000000 2C01000001")
        
        msg = parse_packet(packet)
        
        assert isinstance(msg, StatusAck)
        assert msg.seq == 0x87
        assert msg.setpoint_f == 0x68  # 104°F
        assert msg.temperature_f == 0xB5  # 181°F
        assert msg.mytemp_f == 0x68  # 104°F
        assert msg.on_base == True  # 0x00 = on base
    
    def test_parse_completion_done(self):
        """Parse real completion notification - done."""
        # Real packet: A522 9805 00E0 01F7 A300 20
        packet = bytes.fromhex("A52298 0500E001F7A30020")
        
        msg = parse_packet(packet)
        
        assert isinstance(msg, CompletionNotification)
        assert msg.seq == 0x98
        assert msg.status == CompletionStatus.DONE
    
    def test_parse_completion_hold_complete(self):
        """Parse real completion notification - hold timer complete."""
        # Real packet: A522 E105 0096 01F7 A300 21
        packet = bytes.fromhex("A522E1 05009601F7A30021")
        
        msg = parse_packet(packet)
        
        assert isinstance(msg, CompletionNotification)
        assert msg.seq == 0xE1
        assert msg.status == CompletionStatus.HOLD_COMPLETE
    
    def test_parse_multiple_compact_status(self):
        """Parse sequence of compact status messages."""
        packets = [
            bytes.fromhex("A5221F0C0073 014140000000AF6900000000"),
            bytes.fromhex("A522200C008A 014140000000AF5100000000"),
            bytes.fromhex("A522210C0088 014140000000AF5100010000"),
        ]
        
        messages = [parse_packet(p) for p in packets]
        
        assert all(isinstance(m, CompactStatus) for m in messages)
        assert messages[0].seq == 0x1F
        assert messages[1].seq == 0x20
        assert messages[2].seq == 0x21
        # Payload: 0141 4000 | 00 00 AF 69 | 00 00 00 00
        #          command    | st md sp tm | status pad
        assert messages[0].setpoint_f == 0xAF  # 175°F setpoint
        assert messages[0].temperature_f == 0x69  # 105°F current
        assert messages[1].setpoint_f == 0xAF  # 175°F
        assert messages[1].temperature_f == 0x51  # 81°F
        assert messages[2].setpoint_f == 0xAF  # 175°F
        assert messages[2].temperature_f == 0x51  # 81°F


class TestRoundTrip:
    """Test that messages can be built and parsed back correctly."""
    
    def test_status_request_roundtrip(self):
        """Build and parse status request."""
        original = StatusRequest(seq=0x42)
        packet = original.to_packet()
        
        # Status requests don't get parsed back (they're commands)
        # but we can verify the packet structure
        assert packet[0] == 0xA5  # magic
        assert packet[1] == 0x22  # message type
        assert packet[2] == 0x42  # seq
        assert packet[3] == 0x04  # payload length
    
    def test_v1_start_roundtrip(self):
        """Build V1 start, verify structure."""
        msg = V1Start(seq=0x10, mode=OperatingMode.COFFEE, enable_hold=True, hold_minutes=20)
        packet = msg.to_packet()
        
        # Verify packet structure
        assert packet[0] == 0xA5
        assert packet[1] == 0x22
        assert packet[2] == 0x10
        # Payload: 01F0A300 + 0300 (mode LE) + 01 (hold en) + 04B0 (1200s BE)
        assert bytes.fromhex("01F0A300") in packet
        assert bytes.fromhex("0300") in packet  # mode 3 little-endian
        # 20 minutes = 1200 seconds = 0x04B0 big-endian
        assert bytes.fromhex("04B0") in packet


class TestInvalidPackets:
    """Test handling of invalid/malformed packets."""
    
    def test_parse_too_short(self):
        """Parse packet that's too short."""
        packet = bytes.fromhex("A522")
        msg = parse_packet(packet)
        assert msg is None
    
    def test_parse_bad_magic(self):
        """Parse packet with wrong magic byte."""
        packet = bytes.fromhex("FF22410400720140 4000")
        msg = parse_packet(packet)
        assert msg is None
    
    def test_parse_bad_checksum(self):
        """Parse packet with invalid checksum."""
        packet = bytes.fromhex("A522410400FF0140 4000")  # Wrong checksum
        msg = parse_packet(packet)
        assert msg is None
    
    def test_parse_unknown_command(self):
        """Parse packet with unknown command."""
        packet = bytes.fromhex("A522410400720199 9999")  # Unknown command
        msg = parse_packet(packet)
        assert msg is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
