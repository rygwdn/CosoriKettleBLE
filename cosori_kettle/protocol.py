"""Protocol layer for Cosori Kettle BLE communication.

Protocol Structure:
-------------------
Envelope (6 bytes):
    - 0xA5              : magic byte
    - 0x22 | 0x12       : frame type (0x22=message, 0x12=ack)
    - 0x00-0xFF         : sequence number (ack matches command seq)
    - 0x00-0xFF         : payload length low byte
    - 0x00-0xFF         : payload length high byte
    - 0x00-0xFF         : checksum

Command (4 bytes, first part of payload):
    - 0x00 | 0x01       : protocol version?
    - 0x00-0xFF         : command ID?
    - 0x40 | 0xA3       : direction/type?
    - 0x00              : padding?

... additional body bytes follow command
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import struct


# Protocol constants - Envelope
FRAME_MAGIC = 0xA5
FRAME_TYPE_MESSAGE = 0x22  # Messages sent to/from device
FRAME_TYPE_ACK = 0x12      # Acknowledgments (mirror seq+command from original message)

# Temperature limits (Fahrenheit)
MIN_TEMP_F = 104
MAX_TEMP_F = 212
MIN_VALID_READING_F = 40
MAX_VALID_READING_F = 230

# Operating modes
MODE_BOIL = 0x04
MODE_HEAT = 0x06

# Protocol commands (4-byte command header)
class Command:
    """4-byte command headers for protocol packets."""
    POLL = bytes.fromhex("01404000")          # Poll/status request
    STATUS_COMPACT = bytes.fromhex("01414000")  # Compact status response
    STATUS_EXTENDED = bytes.fromhex("01404000") # Extended status response
    V1_HELLO = bytes.fromhex("0181D100")         # Registration hello
    V1_STOP = bytes.fromhex("01F4A300")          # Stop heating

    V0_HELLO5 = bytes.fromhex("00F2A300")        # Pre-setpoint hello
    V0_SETPOINT = bytes.fromhex("00F0A300")      # Set temperature/mode
    V0_STOP = bytes.fromhex("00F4A300")          # Stop heating

"""
v1 commands:
- start heating: 01F0 A300 yyyy bb zzzz
- delay start: 01F1 A300 xxxx yyyy bb zzzz
  xxxx: delay in seconds in big-endian (10_0E == 3600s == 60 minutes)
  yyyy: mode (0300 for coffee, 0400 for boil, 0500 for "mytemp", etc.)
  bb: enable hold (01 on, 00 off)
  zzzz: hold time in seconds in big-endian (34_08 == 2100s == 35 mins)
- stop: 01F4 A300
- set mytemp temp: 01F3_A300_{temp}
- set mytemp baby-formula mode: 01F5_A300_{0 or 1}
- ?? sent from device when it finished..: 01F7 A300 xx
  xx: 20 = done (might hold), 21 = hold done
- hello: 0181 D100 {bytes}
  bytes: 32 bytes which is 16 byte key encoded as ascii hex. appears to be tied to the controller device/app or the account
  - ack will have payload '00' on success

# TODO: implement registration
- register: 0180 D100 {bytes}
  - ack will have payload '00' on success
  - device must be in pairing mode
"""

# TODO: handle error states?
"""
maybe error state??

A512 631D 0071 0140 4000 0304 D4D4 AF01 B004 B004 0000 0058 0200 0000 0000 (B004) 0000 01
A512 641D 0070 0140 4000 0304 D4D4 AF01 B004 B004 0000 0058 0200 0000 0000 (B004) 0000 01
"""


# TODO: looks like 16 bytes of random data (key) encoded as hex as ascii to get 32 bytes
REGISTRATION_CODE = bytes.fromhex(
    # '3634323837613931376537343661303733313136366237366634336435636262'
    '3939303365303161336333626161386636633731636262353136376537643566'
)


@dataclass
class StatusPacket:
    """Status packet from kettle (compact 0x22 or extended 0x12)."""
    seq: int
    temperature_f: int
    setpoint_f: int
    heating: bool
    stage: int
    mode: int
    on_base: Optional[bool] = None  # Only available in extended packets (0x12)
    packet_type: str = "compact"  # "compact" or "extended"


@dataclass
class UnknownPacket:
    """Unknown packet type."""
    seq: int
    frame_type: int
    payload: bytes


# Timing constants (milliseconds)
# TODO: replace these with waits for acks
HANDSHAKE_DELAY_MS = 80
PRE_SETPOINT_DELAY_MS = 60
POST_SETPOINT_DELAY_MS = 100
CONTROL_DELAY_MS = 50

# TODO: two protocol classes with different implementations sharing helper functions

class PacketBuilder:
    """Builds protocol packets for Cosori Kettle.
    
    See module docstring for protocol structure details.
    """
    
    @staticmethod
    def calculate_checksum(packet: bytes) -> int:
        """Calculate packet checksum.
        
        Algorithm: Build packet with checksum=0x01, then for each byte:
        checksum = (checksum - byte) & 0xFF
        """
        checksum = 0
        for byte in packet:
            checksum = (checksum - byte) & 0xFF
        return checksum
    
    @staticmethod
    def build_frame(frame_type: int, seq: int, payload: bytes) -> bytes:
        """Build frame with envelope and payload.
        
        Args:
            frame_type: 0x22=message, 0x12=ack
            seq: Sequence number (0x00-0xFF)
            payload: Command + body bytes
        """
        payload_len = len(payload)
        len_lo = payload_len & 0xFF
        len_hi = (payload_len >> 8) & 0xFF
        
        # Build packet with checksum=0x01 initially
        packet = bytes([FRAME_MAGIC, frame_type, seq, len_lo, len_hi, 0x01]) + payload
        
        # Calculate and replace checksum
        checksum = PacketBuilder.calculate_checksum(packet)
        return packet[:5] + bytes([checksum]) + packet[6:]
    
    @staticmethod
    def build_send(seq: int, command: bytes, body: bytes = b'') -> bytes:
        """Build message frame (0x22).
        
        Args:
            seq: Sequence number
            command: 4-byte command header (use Command constants)
            body: Additional payload bytes after command
        """
        # TODO: when sending a message, should wait for the ack
        payload = command + body
        return PacketBuilder.build_frame(FRAME_TYPE_MESSAGE, seq, payload)
    
    @staticmethod
    def build_ack(seq: int, command: bytes, body: bytes = b'') -> bytes:
        """Build ACK frame (0x12).
        
        ACKs mirror the original message's sequence and command.
        
        Args:
            seq: Sequence number (from original message)
            command: 4-byte command header (from original message)
            body: Additional payload bytes (typically empty for ACKs)
        """
        payload = command + body
        return PacketBuilder.build_frame(FRAME_TYPE_ACK, seq, payload)
    
    @staticmethod
    def make_poll(seq: int) -> bytes:
        """Create poll/status request."""
        return PacketBuilder.build_send(seq, Command.POLL)
    
    @staticmethod
    def make_hello(seq: int) -> bytes:
        """Create registration hello packet.
        """
        return PacketBuilder.build_send(seq, Command.V1_HELLO, REGISTRATION_CODE)
    
    @staticmethod
    def make_hello5(seq: int) -> bytes:
        """Create hello5 packet (pre-setpoint)."""
        # TODO: mine doesn't do this?
        return PacketBuilder.build_send(seq, Command.V0_HELLO5, bytes([0x00, 0x01, 0x10, 0x0E]))
    
    @staticmethod
    def make_setpoint(seq: int, mode: int, temp_f: int) -> bytes:
        """Create setpoint packet.
        """
        body = bytes([mode, temp_f, 0x01, 0x10, 0x0E])
        return PacketBuilder.build_send(seq, Command.V0_SETPOINT, body)
    
    @staticmethod
    def make_stop(seq: int) -> bytes:
        """Create stop heating packet."""
        # TODO: by version..
        return PacketBuilder.build_send(seq, Command.V0_STOP)
    
    @staticmethod
    def make_ack(seq: int, command: bytes) -> bytes:
        """Create ACK packet (frame type 0x12) mirroring original message.
        
        Args:
            seq: Sequence from original message being acknowledged
            command: Command from original message being acknowledged
        """
        return PacketBuilder.build_ack(seq, command)


class PacketParser:
    """Parses protocol packets from Cosori Kettle.
    
    See module docstring for envelope structure.
    """
    
    MAX_FRAME_BUFFER_SIZE = 512
    MAX_PAYLOAD_SIZE = 256
    
    def __init__(self):
        self.frame_buffer = bytearray()
    
    def append_data(self, data: bytes) -> None:
        """Append received BLE notification data to frame buffer."""
        if len(self.frame_buffer) + len(data) > self.MAX_FRAME_BUFFER_SIZE:
            self.frame_buffer.clear()
        self.frame_buffer.extend(data)
    
    def process_frames(self) -> list:
        """Process complete frames from buffer."""
        packets = []
        
        # TODO: parse using structs
        while True:
            # Find frame start
            start_idx = 0
            while start_idx < len(self.frame_buffer) and self.frame_buffer[start_idx] != FRAME_MAGIC:
                start_idx += 1
            
            if start_idx > 0:
                self.frame_buffer = self.frame_buffer[start_idx:]
            
            # Need at least 6 bytes for envelope
            if len(self.frame_buffer) < 6:
                break
            
            # Parse envelope
            frame_type = self.frame_buffer[1]
            seq = self.frame_buffer[2]
            payload_len = self.frame_buffer[3] | (self.frame_buffer[4] << 8)
            received_checksum = self.frame_buffer[5]
            frame_len = 6 + payload_len
            
            # Validate payload length
            if payload_len > self.MAX_PAYLOAD_SIZE:
                self.frame_buffer = self.frame_buffer[1:]
                continue
            
            # Wait for complete frame
            if len(self.frame_buffer) < frame_len:
                break
            
            # Validate checksum
            test_packet = bytes(self.frame_buffer[:frame_len])
            test_packet = test_packet[:5] + bytes([0x01]) + test_packet[6:]
            calculated_checksum = PacketBuilder.calculate_checksum(test_packet)
            if received_checksum != calculated_checksum:
                self.frame_buffer = self.frame_buffer[1:]
                continue
            
            # Extract payload
            payload = bytes(self.frame_buffer[6:6+payload_len])
            
            # TODO: parse envelope sepparately, then parse the payload based on frame type and command, just pass the parse_{command} the payload after the command id
            # Parse based on frame type
            parsed = None
            if frame_type == FRAME_TYPE_MESSAGE:
                parsed = self._parse_message(seq, payload)
            elif frame_type == FRAME_TYPE_ACK:
                parsed = self._parse_ack(seq, payload)
            else:
                parsed = UnknownPacket(seq=seq, frame_type=frame_type, payload=payload)
            
            if parsed:
                packets.append(parsed)
            
            self.frame_buffer = self.frame_buffer[frame_len:]
        
        return packets
    
    def _parse_message(self, seq: int, payload: bytes) -> Optional[StatusPacket]:
        """Parse message frame (0x22) - compact status."""
        if len(payload) < 9:
            return None
        
        # Check for compact status command
        if payload[:4] != Command.STATUS_COMPACT:
            return None
        
        # TODO: parse using structs
        # TODO: enums for states, modes, etc.
        stage = payload[4] # 00 (idle), 01 (heating), (02) almost done, (03) keep warm
        mode = payload[5] # 01 (green tea, 180f), 02 (oolong, 195f), 03 (coffee, 205f), 04 (boil, 212f), 05 (mytemp, custom)
        sp = payload[6]
        temp = payload[7]
        status = payload[8]
        
        if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
            return None
        
        return StatusPacket(
            seq=seq,
            temperature_f=temp,
            setpoint_f=sp,
            heating=(status != 0),
            stage=stage,
            mode=mode,
            on_base=None,
            packet_type="compact"
        )
    
    def _parse_ack(self, seq: int, payload: bytes) -> Optional[StatusPacket]:
        """Parse ACK frame (0x12) - extended status from device.
        
        When device sends extended status, it uses frame type 0x12.
        """
        if len(payload) < 8:
            return None
        
        # Check for extended status command
        if payload[:4] != Command.STATUS_EXTENDED:
            return None
        
        stage = payload[4]
        mode = payload[5]
        sp = payload[6]
        temp = payload[7]
        # TODO: add to status packet class
        mytemp = payload[8] # TODO if len..
        baby_mode = payload[26] == 0x01 # TODO: if len..
        # TODO: bytes 24 and 25 (right before baby mode) look like they might be status and show errors
        
        if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
            return None
        
        # On-base detection at payload[14]
        on_base = None
        if len(payload) >= 15:
            on_base = (payload[14] == 0x00)
        
        return StatusPacket(
            seq=seq,
            temperature_f=temp,
            setpoint_f=sp,
            heating=(stage != 0),
            stage=stage,
            mode=mode,
            on_base=on_base,
            packet_type="extended"
        )
