"""Struct-based protocol implementation for Cosori Kettle BLE.

This module uses Python's struct module and dataclasses to provide
declarative parsing and building of protocol packets.
"""

import struct
from dataclasses import dataclass, field
from typing import ClassVar, Optional, Union
from enum import IntEnum
import logging

logger = logging.getLogger(__name__)

# Enums
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


# Protocol constants
FRAME_MAGIC = 0xA5
FRAME_TYPE_MESSAGE = 0x22
FRAME_TYPE_ACK = 0x12

MIN_TEMP_F = 104
MAX_TEMP_F = 212


@dataclass
class Envelope:
    """Protocol envelope (6 bytes fixed).
    
    Struct format: <BBBBBB (6 unsigned bytes, little-endian)
    """
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<BBBBBB')
    
    magic: int = FRAME_MAGIC
    frame_type: int = FRAME_TYPE_MESSAGE
    seq: int = 0
    payload_len: int = 0
    checksum: int = 0
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'Envelope':
        """Parse envelope from bytes."""
        magic, frame_type, seq, len_lo, len_hi, checksum = cls.STRUCT.unpack_from(data, 0)
        payload_len = len_lo | (len_hi << 8)
        return cls(magic, frame_type, seq, payload_len, checksum)
    
    def to_bytes(self) -> bytes:
        """Convert envelope to bytes."""
        len_lo = self.payload_len & 0xFF
        len_hi = (self.payload_len >> 8) & 0xFF
        return self.STRUCT.pack(self.magic, self.frame_type, self.seq, 
                               len_lo, len_hi, self.checksum)
    
    @staticmethod
    def calculate_checksum(packet: bytes) -> int:
        """Calculate packet checksum."""
        checksum = 0
        for byte in packet:
            checksum = (checksum - byte) & 0xFF
        return checksum
    
    def command(self) -> bytes:
        """Get command."""
        return self.payload()[:4]
    
    def body(self) -> bytes:
        """Get body."""
        return self.payload()[4:]
    
    def payload(self) -> bytes:
        """Get payload."""
        return self.to_bytes()[6:]

    def validate(self) -> bool:
        """Validate envelope."""
        if self.magic != FRAME_MAGIC:
            return False
        if self.frame_type not in (FRAME_TYPE_MESSAGE, FRAME_TYPE_ACK):
            return False
        if self.seq >= 256:
            return False
        if self.payload_len >= 256:
            return False
        if self.checksum >= 256:
            return False
        if self.checksum != self.calculate_checksum(self.to_bytes()):
            return False
        if self.payload_len < 4:
            return False
        if len(self.payload()) != self.payload_len:
            return False
        return True



@dataclass
class CompactStatus:
    """Compact status packet (12 bytes payload: 4 command + 8 data).
    
    Sent as unsolicited notifications (frame type 0x22).
    """
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sBBBBB3x')  # command + 5 data + 3 padding
    COMMAND: ClassVar[bytes] = bytes.fromhex("01414000")
    
    seq: int
    stage: HeatingStage
    mode: OperatingMode
    setpoint_f: int
    temperature_f: int
    status: int
    
    @classmethod
    def from_bytes(cls, seq: int, payload: bytes) -> 'CompactStatus':
        """Parse from payload bytes."""
        command, stage, mode, sp, temp, status = cls.STRUCT.unpack(payload)
        
        # Handle invalid enum values gracefully
        try:
            stage_enum = HeatingStage(stage)
        except ValueError:
            stage_enum = HeatingStage.IDLE
        
        try:
            mode_enum = OperatingMode(mode)
        except ValueError:
            mode_enum = OperatingMode.IDLE
        
        return cls(
            seq=seq,
            stage=stage_enum,
            mode=mode_enum,
            setpoint_f=sp,
            temperature_f=temp,
            status=status
        )
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        payload = self.STRUCT.pack(
            self.COMMAND,
            self.stage,
            self.mode,
            self.setpoint_f,
            self.temperature_f,
            self.status
        )
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)
    
    @property
    def heating(self) -> bool:
        """Is kettle currently heating."""
        return self.status != 0


@dataclass
class StatusAck:
    """Status ACK packet (29 bytes payload: 4 command + 25 data).
    
    This IS an ACK frame (type 0x12) with status payload.
    Sent in response to status requests.
    
    Payload structure (29 bytes total):
    [0-3]   command (01404000)
    [4]     stage
    [5]     mode  
    [6]     setpoint
    [7]     temperature
    [8]     mytemp
    [9-13]  padding (5 bytes)
    [14]    on_base (0x00=on, 0x01=off)
    [15-16] hold_time_remaining (big-endian)
    [17-26] padding (10 bytes)
    [27]    padding
    [28]    baby_formula_mode (0x01=enabled)
    """
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sBBBBB5xBH11xB')
    # Format: command(4) + stage/mode/sp/temp/mytemp(5) + pad(5) + on_base(1) + hold_time(2) + pad(11) + baby(1)
    COMMAND: ClassVar[bytes] = bytes.fromhex("01404000")
    
    seq: int
    stage: HeatingStage
    mode: OperatingMode
    setpoint_f: int
    temperature_f: int
    mytemp_f: Optional[int] = None
    on_base: Optional[bool] = None
    hold_time_remaining_seconds: Optional[int] = None
    error_code: Optional[int] = None
    baby_formula_mode: Optional[bool] = None
    
    @classmethod
    def from_bytes(cls, seq: int, payload: bytes) -> 'StatusAck':
        """Parse from payload bytes."""
        # Full payload is 29 bytes, struct handles the layout
        if len(payload) < 29:
            # Pad if needed
            payload = payload + bytes(29 - len(payload))
        
        command, stage, mode, sp, temp, mytemp, on_base_byte, hold_time, baby = \
            cls.STRUCT.unpack(payload[:29])
        
        # Handle invalid enum values gracefully
        try:
            stage_enum = HeatingStage(stage)
        except ValueError:
            stage_enum = HeatingStage.IDLE
        
        try:
            mode_enum = OperatingMode(mode)
        except ValueError:
            mode_enum = OperatingMode.IDLE
        
        return cls(
            seq=seq,
            stage=stage_enum,
            mode=mode_enum,
            setpoint_f=sp,
            temperature_f=temp,
            mytemp_f=mytemp if mytemp != 0 else None,
            on_base=(on_base_byte == 0x00) if on_base_byte in (0x00, 0x01) else None,
            hold_time_remaining_seconds=hold_time if hold_time != 0 else None,
            error_code=None,  # Not parsed in this simplified struct
            baby_formula_mode=(baby == 0x01) if baby in (0x00, 0x01) else None
        )
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        mytemp = self.mytemp_f or 0
        on_base_byte = 0x00 if self.on_base else 0x01
        hold_time = self.hold_time_remaining_seconds or 0
        baby = 0x01 if self.baby_formula_mode else 0x00
        
        payload = self.STRUCT.pack(
            self.COMMAND,
            self.stage,
            self.mode,
            self.setpoint_f,
            self.temperature_f,
            mytemp,
            on_base_byte,
            hold_time,
            baby
        )
        return _build_packet(FRAME_TYPE_ACK, self.seq, payload)
    
    @property
    def heating(self) -> bool:
        """Is kettle currently heating."""
        return self.stage != HeatingStage.IDLE


@dataclass
class StatusRequest:
    """Status request command (4 bytes payload).
    
    Renamed from 'poll' for clarity - requests status from device.
    Device responds with StatusAck (frame type 0x12).
    """
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4s')
    COMMAND: ClassVar[bytes] = bytes.fromhex("01404000")
    
    seq: int
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        payload = self.STRUCT.pack(self.COMMAND)
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)


@dataclass
class V1Start:
    """V1 start heating command."""
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sHBH')  # command + mode(LE) + hold_en + hold_time(BE)
    COMMAND: ClassVar[bytes] = bytes.fromhex("01F0A300")
    
    seq: int
    mode: OperatingMode
    enable_hold: bool = False
    hold_minutes: int = 0
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        hold_seconds = self.hold_minutes * 60
        # Mode is little-endian, hold_time is big-endian
        payload = self.COMMAND + \
                  int(self.mode).to_bytes(2, 'little') + \
                  bytes([0x01 if self.enable_hold else 0x00]) + \
                  hold_seconds.to_bytes(2, 'big')
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)


@dataclass
class V1Stop:
    """V1 stop heating command."""
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4s')
    COMMAND: ClassVar[bytes] = bytes.fromhex("01F4A300")
    
    seq: int
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        payload = self.STRUCT.pack(self.COMMAND)
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)


@dataclass
class V1SetMyTemp:
    """V1 set custom temperature command."""
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sB')
    COMMAND: ClassVar[bytes] = bytes.fromhex("01F3A300")
    
    seq: int
    temp_f: int
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        payload = self.STRUCT.pack(self.COMMAND, self.temp_f)
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)


@dataclass
class V1SetBabyMode:
    """V1 set baby formula mode command."""
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sB')
    COMMAND: ClassVar[bytes] = bytes.fromhex("01F5A300")
    
    seq: int
    enabled: bool
    
    def to_packet(self) -> bytes:
        """Build complete packet with envelope."""
        payload = self.STRUCT.pack(self.COMMAND, 0x01 if self.enabled else 0x00)
        return _build_packet(FRAME_TYPE_MESSAGE, self.seq, payload)


@dataclass
class CompletionNotification:
    """Completion notification from device."""
    STRUCT: ClassVar[struct.Struct] = struct.Struct('<4sB')
    COMMAND: ClassVar[bytes] = bytes.fromhex("01F7A300")
    
    seq: int
    status: CompletionStatus
    
    @classmethod
    def from_bytes(cls, seq: int, payload: bytes) -> 'CompletionNotification':
        """Parse from payload bytes."""
        command, status_byte = cls.STRUCT.unpack(payload[:5])
        return cls(seq=seq, status=CompletionStatus(status_byte))


# Helper functions

def _build_packet(frame_type: int, seq: int, payload: bytes) -> bytes:
    """Build complete packet with envelope and checksum."""
    payload_len = len(payload)
    
    # Build packet with checksum=0x01 initially
    envelope = Envelope(
        magic=FRAME_MAGIC,
        frame_type=frame_type,
        seq=seq,
        payload_len=payload_len,
        checksum=0x01
    )
    
    packet = envelope.to_bytes() + payload
    
    # Calculate and update checksum
    checksum = Envelope.calculate_checksum(packet)
    envelope.checksum = checksum
    
    return envelope.to_bytes() + payload


def parse_packet(data: bytes) -> Optional[Union[CompactStatus, StatusAck, CompletionNotification]]:
    """Parse a complete packet.
    
    Returns the appropriate message type or None if invalid/unknown.
    """
    if len(data) < 6:
        return None
    
    envelope = Envelope.from_bytes(data)
    if not envelope.validate():
        logger.error(f"Invalid envelope: {envelope.to_bytes()}")
        return None
    
    if envelope.command() == CompactStatus.COMMAND and envelope.frame_type == FRAME_TYPE_MESSAGE:
        return CompactStatus.from_bytes(envelope.seq, envelope.body())
    elif envelope.command() == StatusAck.COMMAND and envelope.frame_type == FRAME_TYPE_ACK:
        return StatusAck.from_bytes(envelope.seq, envelope.body())
    elif envelope.command() == CompletionNotification.COMMAND:
        return CompletionNotification.from_bytes(envelope.seq, envelope.body())

    logger.error(f"Unknown command: {envelope.command()}")
    return None
