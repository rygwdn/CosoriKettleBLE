"""Protocol layer for Cosori Kettle BLE communication.

Protocol Structure:
-------------------
Envelope (6 bytes - fixed):
    - 0xA5              : magic byte
    - 0x22 | 0x12       : frame type (0x22=message, 0x12=ack)
    - 0x00-0xFF         : sequence number (ack matches command seq)
    - 0x00-0xFF         : payload length low byte
    - 0x00-0xFF         : payload length high byte
    - 0x00-0xFF         : checksum

Command (4 bytes, first part of payload):
    - 0x00 | 0x01       : protocol version (0x00=V0, 0x01=V1)
    - 0x00-0xFF         : command ID
    - 0x40 | 0xA3 | 0xD1: command type/direction
    - 0x00              : padding

Payload (variable, but fixed per command type):
    - Compact status: 12 bytes (4 command + 8 data)
    - Extended status: 29 bytes (4 command + 25 data)
    - Commands: varies by command type

Important Notes:
----------------
1. Status packets are FIXED LENGTH, not variable:
   - Compact status (0x22): Always 12 bytes payload
   - Extended status (0x12): Always 29 bytes payload

2. Extended status IS an ACK packet (frame type 0x12) with status payload.
   It's sent in response to poll commands and contains full device state.

3. Flow control: Packets >20 bytes are sent in 20-byte chunks over BLE.
   The parser must buffer and reassemble multi-chunk packets.

4. Response pattern: Commands sent on TX characteristic (0xFFF2) trigger
   responses on RX notification characteristic (0xFFF1).
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Union
from enum import IntEnum
import struct
import asyncio
import secrets


# Protocol constants - Envelope
FRAME_MAGIC = 0xA5
FRAME_TYPE_MESSAGE = 0x22  # Messages sent to/from device
FRAME_TYPE_ACK = 0x12      # Acknowledgments (includes extended status responses)

# Fixed payload lengths (command + body)
COMPACT_STATUS_PAYLOAD_LEN = 12  # 4-byte command + 8 bytes data
EXTENDED_STATUS_PAYLOAD_LEN = 29  # 4-byte command + 25 bytes data

# Temperature limits (Fahrenheit)
MIN_TEMP_F = 104
MAX_TEMP_F = 212
MIN_VALID_READING_F = 40
MAX_VALID_READING_F = 230

# Operating modes (legacy constants - use OperatingMode enum instead)
MODE_BOIL = 0x04
MODE_HEAT = 0x06


# Enums for protocol states and modes
class HeatingStage(IntEnum):
    """Heating stage of the kettle."""
    IDLE = 0x00
    HEATING = 0x01
    ALMOST_DONE = 0x02
    KEEP_WARM = 0x03


class OperatingMode(IntEnum):
    """Operating mode/temperature preset."""
    IDLE = 0x00        # Not heating / idle
    GREEN_TEA = 0x01   # 180°F
    OOLONG = 0x02      # 195°F
    COFFEE = 0x03      # 205°F
    BOIL = 0x04        # 212°F
    MY_TEMP = 0x05     # Custom temperature
    HEAT = 0x06        # Generic heat mode (V0 protocol)


class CompletionStatus(IntEnum):
    """Completion status for V1 protocol notifications."""
    DONE = 0x20           # Heating complete (might hold)
    HOLD_COMPLETE = 0x21  # Hold timer complete


class ProtocolVersion(IntEnum):
    """Protocol version."""
    V0 = 0  # Legacy protocol (hello5 + setpoint)
    V1 = 1  # Modern protocol (F0/F1/F3/F4/F5 commands)

# Protocol commands (4-byte command header)
class Command:
    """4-byte command headers for protocol packets."""
    # Common commands
    STATUS_REQUEST = bytes.fromhex("01404000")     # Status request
    STATUS_COMPACT = bytes.fromhex("01414000")     # Compact status response
    STATUS_ACK = bytes.fromhex("01404000")         # Status ACK response
    
    # V1 Protocol commands
    V1_HELLO = bytes.fromhex("0181D100")         # Registration hello
    V1_REGISTER = bytes.fromhex("0180D100")      # Registration (pairing mode)
    V1_START = bytes.fromhex("01F0A300")         # Start heating
    V1_DELAY_START = bytes.fromhex("01F1A300")   # Delayed start
    V1_SET_MYTEMP = bytes.fromhex("01F3A300")    # Set custom temperature
    V1_STOP = bytes.fromhex("01F4A300")          # Stop heating
    V1_SET_BABY_MODE = bytes.fromhex("01F5A300") # Set baby formula mode
    V1_COMPLETION = bytes.fromhex("01F7A300")    # Completion notification

    # V0 Protocol commands (legacy)
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


# Protocol struct definitions for efficient parsing
ENVELOPE_STRUCT = struct.Struct('<BBBBBB')  # magic, type, seq, len_lo, len_hi, checksum (all 1 byte)
# Note: We don't use a single struct for status packets because of variable-length payloads


@dataclass
class StatusPacket:
    """Status packet from kettle (compact 0x22 or extended 0x12)."""
    seq: int
    temperature_f: int
    setpoint_f: int
    heating: bool
    stage: HeatingStage
    mode: OperatingMode
    on_base: Optional[bool] = None  # Only available in extended packets (0x12)
    packet_type: str = "compact"  # "compact" or "extended"
    
    # Extended status fields (only in extended packets)
    mytemp_f: Optional[int] = None  # Custom temperature setting (payload[8])
    baby_formula_mode: Optional[bool] = None  # Baby formula mode (payload[26])
    hold_time_remaining_seconds: Optional[int] = None  # From payload[14:16] big-endian
    error_code: Optional[int] = None  # From payload[24:25]


@dataclass
class AckPacket:
    """ACK packet for command acknowledgment."""
    seq: int
    command: bytes  # 4-byte command header being acknowledged
    success: bool
    payload: bytes  # Additional payload data


@dataclass
class CompletionPacket:
    """Completion notification packet (V1 protocol)."""
    seq: int
    status: CompletionStatus  # 0x20 = done, 0x21 = hold done


@dataclass
class Envelope:
    """Parsed envelope (frame header)."""
    magic: int
    frame_type: int
    seq: int
    payload_len: int
    checksum: int
    payload: bytes


@dataclass
class UnknownPacket:
    """Unknown packet type."""
    seq: int
    frame_type: int
    payload: bytes


@dataclass
class PendingCommand:
    """Tracks a command awaiting ACK."""
    seq: int
    command: bytes
    sent_time: float
    future: asyncio.Future


# Timing constants (milliseconds)
# TODO: replace these with waits for acks
HANDSHAKE_DELAY_MS = 80
PRE_SETPOINT_DELAY_MS = 60
POST_SETPOINT_DELAY_MS = 100
CONTROL_DELAY_MS = 50


def generate_registration_key() -> bytes:
    """Generate a new registration key for device pairing.
    
    Returns:
        32-byte ASCII hex string (representing 16 random bytes)
    """
    random_bytes = secrets.token_bytes(16)
    return random_bytes.hex().encode('ascii')


def is_error_state(packet: StatusPacket) -> bool:
    """Check if status packet indicates an error state.
    
    Error states appear to have suspicious temperature values like 0xB004
    in multiple fields.
    
    Args:
        packet: Status packet to check
        
    Returns:
        True if packet appears to be an error state
    """
    # Check for suspicious temperature patterns (e.g., B004 = 45060°F)
    if packet.temperature_f > 1000 or packet.setpoint_f > 1000:
        return True
    
    # Check error code if available
    if packet.error_code is not None and packet.error_code != 0:
        return True
    
    return False


# TODO: two protocol classes with different implementations sharing helper functions


class CommandManager:
    """Manages command sending and ACK tracking."""
    
    def __init__(self):
        self.pending_acks: dict[int, PendingCommand] = {}
    
    async def wait_for_ack(self, seq: int, timeout: float = 1.0) -> bool:
        """Wait for ACK with timeout.
        
        Args:
            seq: Sequence number to wait for
            timeout: Timeout in seconds
            
        Returns:
            True if ACK received, False if timeout
        """
        if seq not in self.pending_acks:
            return False
        
        try:
            await asyncio.wait_for(self.pending_acks[seq].future, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending_acks.pop(seq, None)
    
    def register_command(self, seq: int, command: bytes) -> asyncio.Future:
        """Register a command awaiting ACK.
        
        Args:
            seq: Sequence number
            command: Command bytes
            
        Returns:
            Future that will be resolved when ACK arrives
        """
        future = asyncio.Future()
        self.pending_acks[seq] = PendingCommand(
            seq=seq,
            command=command,
            sent_time=asyncio.get_event_loop().time(),
            future=future
        )
        return future
    
    def handle_ack(self, ack_packet: AckPacket) -> None:
        """Handle received ACK packet.
        
        Args:
            ack_packet: Received ACK packet
        """
        if ack_packet.seq in self.pending_acks:
            pending = self.pending_acks[ack_packet.seq]
            if not pending.future.done():
                pending.future.set_result(ack_packet)


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
    def make_status_request(seq: int) -> bytes:
        """Create status request."""
        return PacketBuilder.build_send(seq, Command.STATUS_REQUEST)
    
    @staticmethod
    def make_hello(seq: int, registration_key: Optional[bytes] = None) -> bytes:
        """Create registration hello packet.
        
        Args:
            seq: Sequence number
            registration_key: 32-byte ASCII hex registration key (default uses REGISTRATION_CODE)
        """
        key = registration_key if registration_key is not None else REGISTRATION_CODE
        return PacketBuilder.build_send(seq, Command.V1_HELLO, key)
    
    @staticmethod
    def make_register(seq: int, registration_key: Optional[bytes] = None) -> bytes:
        """Create registration packet for pairing.
        
        Device must be in pairing mode. ACK will have payload '00' on success.
        
        Args:
            seq: Sequence number
            registration_key: 32-byte ASCII hex registration key (if None, generates new key)
            
        Returns:
            Registration packet bytes
        """
        if registration_key is None:
            registration_key = generate_registration_key()
        return PacketBuilder.build_send(seq, Command.V1_REGISTER, registration_key)
    
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
    def make_stop(seq: int, protocol_version: ProtocolVersion = ProtocolVersion.V0) -> bytes:
        """Create stop heating packet.
        
        Args:
            seq: Sequence number
            protocol_version: Protocol version to use
        """
        if protocol_version == ProtocolVersion.V1:
            return PacketBuilder.build_send(seq, Command.V1_STOP)
        else:
            return PacketBuilder.build_send(seq, Command.V0_STOP)
    
    @staticmethod
    def make_v1_start(seq: int, mode: Union[int, OperatingMode], 
                      enable_hold: bool = False, hold_seconds: int = 0) -> bytes:
        """Create V1 start heating packet.
        
        Args:
            seq: Sequence number
            mode: Operating mode (use OperatingMode enum or int)
            enable_hold: Enable hold/keep-warm after heating
            hold_seconds: Hold time in seconds
            
        Returns:
            Start heating packet
            
        Example packets:
            - start 205°F, no hold:  A522 xxxx xxxx 01F0 A300 0300 0000 00
            - start 205°F, hold 35m: A522 xxxx xxxx 01F0 A300 0300 0134 08
            Note: mode is little-endian (0300 = mode 3), hold_time is big-endian (3408 = 2100s)
        """
        mode_val = int(mode)
        mode_bytes = mode_val.to_bytes(2, byteorder='little')  # Mode is little-endian
        hold_byte = bytes([0x01 if enable_hold else 0x00])
        hold_time_bytes = hold_seconds.to_bytes(2, byteorder='big')  # Hold time is big-endian
        
        body = mode_bytes + hold_byte + hold_time_bytes
        return PacketBuilder.build_send(seq, Command.V1_START, body)
    
    @staticmethod
    def make_v1_delay_start(seq: int, delay_seconds: int, 
                           mode: Union[int, OperatingMode],
                           enable_hold: bool = False, hold_seconds: int = 0) -> bytes:
        """Create V1 delayed start packet.
        
        Args:
            seq: Sequence number
            delay_seconds: Delay in seconds before starting
            mode: Operating mode
            enable_hold: Enable hold/keep-warm after heating
            hold_seconds: Hold time in seconds
            
        Returns:
            Delayed start packet
            
        Example packet:
            - delay start 1h, boil, no hold: A522 xxxx xxxx 01F1 A300 100E 0400 0000 00
              (0x0E10 = 3600 seconds = 1 hour, big-endian)
              (0400 = mode 4 boil, little-endian)
        """
        delay_bytes = delay_seconds.to_bytes(2, byteorder='big')  # Delay is big-endian
        mode_val = int(mode)
        mode_bytes = mode_val.to_bytes(2, byteorder='little')  # Mode is little-endian
        hold_byte = bytes([0x01 if enable_hold else 0x00])
        hold_time_bytes = hold_seconds.to_bytes(2, byteorder='big')  # Hold time is big-endian
        
        body = delay_bytes + mode_bytes + hold_byte + hold_time_bytes
        return PacketBuilder.build_send(seq, Command.V1_DELAY_START, body)
    
    @staticmethod
    def make_v1_set_mytemp(seq: int, temp_f: int) -> bytes:
        """Create V1 set custom temperature packet.
        
        Args:
            seq: Sequence number
            temp_f: Temperature in Fahrenheit
            
        Returns:
            Set mytemp packet
            
        Example packet:
            - set mytemp to 179°F: A522 1C05 00CD 01F3 A300 B3
        """
        body = bytes([temp_f])
        return PacketBuilder.build_send(seq, Command.V1_SET_MYTEMP, body)
    
    @staticmethod
    def make_v1_set_baby_mode(seq: int, enabled: bool) -> bytes:
        """Create V1 set baby formula mode packet.
        
        Args:
            seq: Sequence number
            enabled: Enable or disable baby formula mode
            
        Returns:
            Set baby mode packet
            
        Example packets:
            - enable:  A522 2505 0074 01F5 A300 01
            - disable: A522 1D05 007D 01F5 A300 00
        """
        body = bytes([0x01 if enabled else 0x00])
        return PacketBuilder.build_send(seq, Command.V1_SET_BABY_MODE, body)
    
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
        
        while True:
            # Parse envelope
            envelope = self._parse_envelope()
            if envelope is None:
                break
            
            # Parse payload based on envelope
            parsed = self._parse_payload(envelope)
            if parsed:
                packets.append(parsed)
        
        return packets
    
    def _parse_envelope(self) -> Optional[Envelope]:
        """Parse envelope from buffer.
        
        Returns:
            Envelope if valid frame found, None otherwise
        """
        # Find frame start
        start_idx = 0
        while start_idx < len(self.frame_buffer) and self.frame_buffer[start_idx] != FRAME_MAGIC:
            start_idx += 1
        
        if start_idx > 0:
            self.frame_buffer = self.frame_buffer[start_idx:]
        
        # Need at least 6 bytes for envelope
        if len(self.frame_buffer) < 6:
            return None
        
        # Parse envelope using struct (more efficient than manual indexing)
        try:
            magic, frame_type, seq, len_lo, len_hi, received_checksum = \
                ENVELOPE_STRUCT.unpack_from(self.frame_buffer, 0)
        except struct.error:
            return None
        
        payload_len = len_lo | (len_hi << 8)
        frame_len = 6 + payload_len
        
        # Validate payload length
        if payload_len > self.MAX_PAYLOAD_SIZE:
            self.frame_buffer = self.frame_buffer[1:]
            return None
        
        # Wait for complete frame
        if len(self.frame_buffer) < frame_len:
            return None
        
        # Validate checksum
        test_packet = bytes(self.frame_buffer[:frame_len])
        test_packet = test_packet[:5] + bytes([0x01]) + test_packet[6:]
        calculated_checksum = PacketBuilder.calculate_checksum(test_packet)
        if received_checksum != calculated_checksum:
            self.frame_buffer = self.frame_buffer[1:]
            return None
        
        # Extract payload
        payload = bytes(self.frame_buffer[6:6+payload_len])
        
        # Remove processed frame from buffer
        self.frame_buffer = self.frame_buffer[frame_len:]
        
        return Envelope(
            magic=magic,
            frame_type=frame_type,
            seq=seq,
            payload_len=payload_len,
            checksum=received_checksum,
            payload=payload
        )
    
    def _parse_payload(self, envelope: Envelope) -> Optional[Union[StatusPacket, AckPacket, CompletionPacket, UnknownPacket]]:
        """Parse payload based on frame type and command.
        
        Args:
            envelope: Parsed envelope
            
        Returns:
            Parsed packet or None
        """
        payload = envelope.payload
        
        # Need at least 4 bytes for command header
        if len(payload) < 4:
            return UnknownPacket(seq=envelope.seq, frame_type=envelope.frame_type, payload=payload)
        
        command = payload[:4]
        body = payload[4:]
        
        # Route based on frame type and command
        if envelope.frame_type == FRAME_TYPE_MESSAGE:
            if command == Command.STATUS_COMPACT:
                return self._parse_compact_status(envelope.seq, body)
            elif command == Command.V1_COMPLETION:
                return self._parse_completion(envelope.seq, body)
            else:
                return UnknownPacket(seq=envelope.seq, frame_type=envelope.frame_type, payload=payload)
        
        elif envelope.frame_type == FRAME_TYPE_ACK:
            if command == Command.STATUS_ACK:
                return self._parse_status_ack(envelope.seq, body)
            elif command == Command.V1_COMPLETION:
                return self._parse_completion(envelope.seq, body)
            elif command in (Command.V1_START, Command.V1_STOP, Command.V1_REGISTER, 
                           Command.V1_HELLO, Command.V1_SET_MYTEMP, Command.V1_SET_BABY_MODE,
                           Command.V1_DELAY_START, Command.V0_SETPOINT, Command.V0_STOP):
                # Command acknowledgment
                return self._parse_command_ack(envelope.seq, command, body)
            else:
                return UnknownPacket(seq=envelope.seq, frame_type=envelope.frame_type, payload=payload)
        
        else:
            return UnknownPacket(seq=envelope.seq, frame_type=envelope.frame_type, payload=payload)
    
    def _parse_compact_status(self, seq: int, body: bytes) -> Optional[StatusPacket]:
        """Parse compact status packet body (frame type 0x22 = message).
        
        Compact status is sent as unsolicited notifications from the device.
        Payload is FIXED LENGTH: 12 bytes (4 command + 8 data bytes).
        
        Args:
            seq: Sequence number
            body: Payload body after command header (8 bytes)
            
        Returns:
            StatusPacket or None if invalid
            
        Payload structure (after 4-byte command header):
            body[0]: stage (heating stage)
            body[1]: mode (operating mode)
            body[2]: setpoint (target temperature)
            body[3]: temperature (current temperature)
            body[4]: status (heating indicator)
            body[5-7]: padding/unknown
        """
        if len(body) < 5:
            return None
        
        stage = body[0]  # 00 (idle), 01 (heating), 02 (almost done), 03 (keep warm)
        mode = body[1]   # 01-05 (see OperatingMode enum)
        sp = body[2]
        temp = body[3]
        status = body[4]
        
        if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
            return None
        
        # Handle enum conversion gracefully
        try:
            stage_enum = HeatingStage(stage)
        except ValueError:
            stage_enum = HeatingStage.IDLE
        
        try:
            mode_enum = OperatingMode(mode)
        except ValueError:
            mode_enum = OperatingMode.BOIL
        
        return StatusPacket(
            seq=seq,
            temperature_f=temp,
            setpoint_f=sp,
            heating=(status != 0),
            stage=stage_enum,
            mode=mode_enum,
            on_base=None,
            packet_type="compact"
        )
    
    def _parse_status_ack(self, seq: int, body: bytes) -> Optional[StatusPacket]:
        """Parse status ACK packet body (frame type 0x12 = ACK with status payload).
        
        Renamed from _parse_extended_status to clarify that this IS an ACK.
        
        IMPORTANT: Extended status uses frame type 0x12 (ACK), but contains full status data.
        This is the device's response to poll commands, sent as an ACK frame with 29-byte payload.
        
        Extended status includes additional fields like on_base, mytemp, baby_mode, etc.
        Payload is FIXED LENGTH: 29 bytes (4 command + 25 data bytes).
        
        Args:
            seq: Sequence number
            body: Payload body after command header (25 bytes)
            
        Returns:
            StatusPacket or None if invalid
            
        Payload structure (after 4-byte command header):
            body[0-3]:   stage, mode, setpoint, temperature
            body[4]:     mytemp (custom temperature)
            body[5-9]:   padding/unknown
            body[10]:    on_base status (0x00=on, 0x01=off)
            body[11-12]: hold time remaining (big-endian seconds)
            body[13-19]: padding/unknown
            body[20]:    error code
            body[21]:    padding
            body[22]:    baby formula mode (0x01=enabled)
            body[23-24]: padding
        """
        if len(body) < 4:
            return None
        
        stage = body[0]
        mode = body[1]
        sp = body[2]
        temp = body[3]
        
        if temp < MIN_VALID_READING_F or temp > MAX_VALID_READING_F:
            return None
        
        # Parse optional fields based on payload length
        mytemp_f = None
        if len(body) >= 5:
            mytemp_f = body[4]
        
        # On-base detection at body[10] (payload[14])
        on_base = None
        if len(body) >= 11:
            on_base = (body[10] == 0x00)
        
        # Hold time remaining at body[10:12] (big-endian)
        hold_time_remaining = None
        if len(body) >= 12:
            hold_time_remaining = int.from_bytes(body[10:12], byteorder='big')
        
        # Error code at body[20:21] (payload[24:25])
        error_code = None
        if len(body) >= 21:
            error_code = body[20]
        
        # Baby formula mode at body[22] (payload[26] in full packet after 4-byte command header)
        baby_mode = None
        if len(body) >= 23:
            baby_mode = (body[22] == 0x01)
        
        # Handle enum conversion gracefully
        try:
            stage_enum = HeatingStage(stage)
        except ValueError:
            stage_enum = HeatingStage.IDLE
        
        try:
            mode_enum = OperatingMode(mode)
        except ValueError:
            mode_enum = OperatingMode.BOIL
        
        return StatusPacket(
            seq=seq,
            temperature_f=temp,
            setpoint_f=sp,
            heating=(stage != 0),
            stage=stage_enum,
            mode=mode_enum,
            on_base=on_base,
            packet_type="extended",
            mytemp_f=mytemp_f,
            baby_formula_mode=baby_mode,
            hold_time_remaining_seconds=hold_time_remaining,
            error_code=error_code
        )
    
    def _parse_command_ack(self, seq: int, command: bytes, body: bytes) -> AckPacket:
        """Parse command acknowledgment.
        
        Args:
            seq: Sequence number
            command: Command being acknowledged
            body: ACK payload body
            
        Returns:
            AckPacket
        """
        # Check for success indicator (payload '00' means success for registration)
        success = True
        if len(body) > 0:
            success = (body[0] == 0x00)
        
        return AckPacket(
            seq=seq,
            command=command,
            success=success,
            payload=body
        )
    
    def _parse_completion(self, seq: int, body: bytes) -> Optional[CompletionPacket]:
        """Parse V1 completion notification.
        
        Args:
            seq: Sequence number
            body: Payload body after command header
            
        Returns:
            CompletionPacket or None if invalid
            
        Example packets:
            Done: A522 9805 00E0 | 01F7 A300 20
            Hold complete: A522 E105 0096 | 01F7 A300 21
        """
        if len(body) < 1:
            return None
        
        status_byte = body[0]
        
        # Validate status byte
        if status_byte not in (0x20, 0x21):
            return None
        
        return CompletionPacket(
            seq=seq,
            status=CompletionStatus(status_byte)
        )
