"""Base protocol classes for Cosori Kettle BLE communication.

This module defines the base protocol interface and common functionality
shared between V0 (legacy) and V1 (current) protocol implementations.
"""

from abc import ABC, abstractmethod
from typing import Union
from .protocol import (
    PacketBuilder, Command, OperatingMode, ProtocolVersion
)


class BaseProtocol(ABC):
    """Base class for protocol implementations.
    
    Defines the common interface that both V0 and V1 protocols must implement.
    """
    
    def __init__(self):
        self.builder = PacketBuilder()
    
    @abstractmethod
    def make_start(self, seq: int, mode: Union[int, OperatingMode], 
                   temp_f: int, **kwargs) -> bytes:
        """Create start heating packet.
        
        Args:
            seq: Sequence number
            mode: Operating mode
            temp_f: Target temperature in Fahrenheit
            **kwargs: Protocol-specific options (hold_enabled, hold_minutes, etc.)
        
        Returns:
            Packet bytes
        """
        pass
    
    @abstractmethod
    def make_stop(self, seq: int) -> bytes:
        """Create stop heating packet.
        
        Args:
            seq: Sequence number
        
        Returns:
            Packet bytes
        """
        pass
    
    def make_status_request(self, seq: int) -> bytes:
        """Create status request packet (common to both protocols).
        
        Renamed from make_poll for clarity.
        
        Args:
            seq: Sequence number
        
        Returns:
            Packet bytes
        """
        return self.builder.make_status_request(seq)
    
    def make_hello(self, seq: int, registration_key: bytes = None) -> bytes:
        """Create hello packet (common to both protocols).
        
        Args:
            seq: Sequence number
            registration_key: Registration key for V1, ignored for V0
        
        Returns:
            Packet bytes
        """
        return self.builder.make_hello(seq, registration_key)


class V0Protocol(BaseProtocol):
    """V0 (legacy) protocol implementation.
    
    Features:
    - Basic temperature control with setpoint commands
    - Requires hello5 handshake before setpoint
    - Limited to boil and heat modes
    - No advanced features (hold, delay, custom temp)
    """
    
    @property
    def version(self) -> ProtocolVersion:
        return ProtocolVersion.V0
    
    @property
    def requires_hello5(self) -> bool:
        """V0 protocol requires hello5 before setpoint."""
        return True
    
    def make_hello5(self, seq: int) -> bytes:
        """Create hello5 packet (V0-specific pre-setpoint handshake).
        
        Args:
            seq: Sequence number
        
        Returns:
            Packet bytes
        """
        return self.builder.make_hello5(seq)
    
    def make_start(self, seq: int, mode: Union[int, OperatingMode], 
                   temp_f: int, **kwargs) -> bytes:
        """Create V0 start heating packet (setpoint command).
        
        Args:
            seq: Sequence number
            mode: Operating mode (BOIL or HEAT)
            temp_f: Target temperature in Fahrenheit
            **kwargs: Ignored for V0 protocol
        
        Returns:
            Packet bytes
        """
        mode_val = int(mode)
        return self.builder.make_setpoint(seq, mode_val, temp_f)
    
    def make_stop(self, seq: int) -> bytes:
        """Create V0 stop heating packet.
        
        Args:
            seq: Sequence number
        
        Returns:
            Packet bytes
        """
        return self.builder.make_stop(seq, ProtocolVersion.V0)


class V1Protocol(BaseProtocol):
    """V1 (current) protocol implementation.
    
    Features:
    - Advanced temperature control with multiple modes
    - Delayed start support
    - Hold/keep-warm timer
    - Custom temperature (My Temp) mode
    - Baby formula mode
    - Registration/pairing support
    - Completion notifications
    - No hello5 required
    """
    
    @property
    def version(self) -> ProtocolVersion:
        return ProtocolVersion.V1
    
    @property
    def requires_hello5(self) -> bool:
        """V1 protocol does not require hello5."""
        return False
    
    def make_register(self, seq: int, registration_key: bytes = None) -> bytes:
        """Create registration packet for pairing.
        
        Args:
            seq: Sequence number
            registration_key: 32-byte ASCII hex registration key
        
        Returns:
            Packet bytes
        """
        return self.builder.make_register(seq, registration_key)
    
    def make_start(self, seq: int, mode: Union[int, OperatingMode], 
                   temp_f: int, **kwargs) -> bytes:
        """Create V1 start heating packet.
        
        Args:
            seq: Sequence number
            mode: Operating mode
            temp_f: Target temperature (used with MY_TEMP mode)
            **kwargs: V1-specific options:
                - enable_hold (bool): Enable hold/keep-warm
                - hold_minutes (int): Hold duration in minutes
        
        Returns:
            Packet bytes
        """
        enable_hold = kwargs.get('enable_hold', False)
        hold_minutes = kwargs.get('hold_minutes', 0)
        hold_seconds = hold_minutes * 60
        
        return self.builder.make_v1_start(seq, mode, enable_hold, hold_seconds)
    
    def make_delayed_start(self, seq: int, delay_minutes: int,
                          mode: Union[int, OperatingMode],
                          enable_hold: bool = False,
                          hold_minutes: int = 0) -> bytes:
        """Create V1 delayed start packet.
        
        Args:
            seq: Sequence number
            delay_minutes: Delay before starting (minutes)
            mode: Operating mode
            enable_hold: Enable hold/keep-warm after heating
            hold_minutes: Hold duration in minutes
        
        Returns:
            Packet bytes
        """
        delay_seconds = delay_minutes * 60
        hold_seconds = hold_minutes * 60
        return self.builder.make_v1_delay_start(seq, delay_seconds, mode, 
                                                enable_hold, hold_seconds)
    
    def make_stop(self, seq: int) -> bytes:
        """Create V1 stop heating packet.
        
        Args:
            seq: Sequence number
        
        Returns:
            Packet bytes
        """
        return self.builder.make_stop(seq, ProtocolVersion.V1)
    
    def make_set_mytemp(self, seq: int, temp_f: int) -> bytes:
        """Create V1 set custom temperature packet.
        
        Args:
            seq: Sequence number
            temp_f: Temperature in Fahrenheit
        
        Returns:
            Packet bytes
        """
        return self.builder.make_v1_set_mytemp(seq, temp_f)
    
    def make_set_baby_mode(self, seq: int, enabled: bool) -> bytes:
        """Create V1 set baby formula mode packet.
        
        Args:
            seq: Sequence number
            enabled: Enable or disable baby formula mode
        
        Returns:
            Packet bytes
        """
        return self.builder.make_v1_set_baby_mode(seq, enabled)
