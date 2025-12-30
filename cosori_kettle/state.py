"""State management for Cosori Kettle."""

from dataclasses import dataclass, field
from typing import Optional, Callable, Union
import time

from .protocol import StatusPacket, UnknownPacket


@dataclass
class KettleState:
    """Current state of the kettle."""
    current_temp_f: float = 0.0
    setpoint_f: float = 212.0
    target_setpoint_f: float = 212.0
    on_base: Optional[bool] = None
    heating: bool = False
    connected: bool = False
    last_update: float = 0.0
    
    # Extended status fields
    mytemp_f: Optional[int] = None
    baby_formula_mode: Optional[bool] = None
    hold_time_remaining_seconds: Optional[int] = None
    error_code: Optional[int] = None
    stage: Optional[int] = None
    mode: Optional[int] = None
    
    def update_from_packet(self, packet: StatusPacket) -> dict:
        """Update state from parsed packet. Returns dict of changed fields."""
        changes = {}
        
        if self.current_temp_f != packet.temperature_f:
            changes['temperature_f'] = (self.current_temp_f, packet.temperature_f)
            self.current_temp_f = packet.temperature_f
        
        if self.setpoint_f != packet.setpoint_f:
            changes['setpoint_f'] = (self.setpoint_f, packet.setpoint_f)
            self.setpoint_f = packet.setpoint_f
        
        if self.heating != packet.heating:
            changes['heating'] = (self.heating, packet.heating)
            self.heating = packet.heating
        
        if packet.on_base is not None and self.on_base != packet.on_base:
            changes['on_base'] = (self.on_base, packet.on_base)
            self.on_base = packet.on_base
        
        # Update extended fields
        if packet.mytemp_f is not None and self.mytemp_f != packet.mytemp_f:
            changes['mytemp_f'] = (self.mytemp_f, packet.mytemp_f)
            self.mytemp_f = packet.mytemp_f
        
        if packet.baby_formula_mode is not None and self.baby_formula_mode != packet.baby_formula_mode:
            changes['baby_formula_mode'] = (self.baby_formula_mode, packet.baby_formula_mode)
            self.baby_formula_mode = packet.baby_formula_mode
        
        if packet.hold_time_remaining_seconds is not None and self.hold_time_remaining_seconds != packet.hold_time_remaining_seconds:
            changes['hold_time_remaining_seconds'] = (self.hold_time_remaining_seconds, packet.hold_time_remaining_seconds)
            self.hold_time_remaining_seconds = packet.hold_time_remaining_seconds
        
        if packet.error_code is not None and self.error_code != packet.error_code:
            changes['error_code'] = (self.error_code, packet.error_code)
            self.error_code = packet.error_code
        
        # Update stage and mode
        stage_val = int(packet.stage)
        mode_val = int(packet.mode)
        
        if self.stage != stage_val:
            changes['stage'] = (self.stage, stage_val)
            self.stage = stage_val
        
        if self.mode != mode_val:
            changes['mode'] = (self.mode, mode_val)
            self.mode = mode_val
        
        self.last_update = time.time()
        return changes


class StateManager:
    """Manages kettle state and sequence numbers."""
    
    NO_RESPONSE_THRESHOLD = 10
    
    def __init__(self, on_state_change: Optional[Callable[[dict], None]] = None):
        self.state = KettleState()
        self.tx_seq = 0
        self.last_rx_seq = 0
        self.last_status_seq = 0
        self.status_received = False
        self.no_response_count = 0
        self.on_state_change = on_state_change
    
    def next_tx_seq(self) -> int:
        """Get next TX sequence number."""
        # Sync with RX sequence on first use if we've received packets
        if self.tx_seq == 0 and self.last_rx_seq != 0:
            self.tx_seq = (self.last_rx_seq + 1) & 0xFF
        else:
            self.tx_seq = (self.tx_seq + 1) & 0xFF
        return self.tx_seq
    
    def update_from_packet(self, packet: Union[StatusPacket, UnknownPacket]) -> None:
        """Update state from parsed packet."""
        # Update RX sequence
        self.last_rx_seq = packet.seq
        
        # Update status sequence for status packets
        if isinstance(packet, StatusPacket):
            self.last_status_seq = self.last_rx_seq
            self.status_received = True
            self.reset_online_status()
            
            # Update state
            changes = self.state.update_from_packet(packet)
            
            # Notify callback of changes
            if changes and self.on_state_change:
                self.on_state_change(changes)
    
    def track_online_status(self) -> None:
        """Track connection health. Call periodically."""
        self.no_response_count += 1
        
        if self.no_response_count >= self.NO_RESPONSE_THRESHOLD and self.status_received:
            # Mark as offline
            self.status_received = False
            self.state.connected = False
    
    def reset_online_status(self) -> None:
        """Reset online status counter. Call when status received."""
        self.no_response_count = 0
        self.state.connected = True
    
    def set_connected(self, connected: bool) -> None:
        """Set connection state."""
        if self.state.connected != connected:
            self.state.connected = connected
            if not connected:
                self.status_received = False
                self.no_response_count = 0
