"""BLE client wrapper for Cosori Kettle.

Protocol Overview:
------------------
See protocol.py for full protocol structure documentation.

Envelope: 6 bytes [magic, frame_type, seq, len_lo, len_hi, checksum]
Command: 4 bytes [protocol_ver, command_id, direction, padding] + body
"""

import asyncio
import logging
from typing import Optional, Callable
from bleak import BleakClient, BleakScanner, BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic

from .protocol import (
    PacketParser, PacketBuilder, StatusPacket, AckPacket, CompletionPacket, Command,
    CommandManager, ProtocolVersion, OperatingMode, HeatingStage, CompletionStatus,
    MODE_BOIL, MODE_HEAT, MIN_TEMP_F, MAX_TEMP_F,
    HANDSHAKE_DELAY_MS, PRE_SETPOINT_DELAY_MS, POST_SETPOINT_DELAY_MS, CONTROL_DELAY_MS,
    generate_registration_key, is_error_state
)
from .state import StateManager

logger = logging.getLogger(__name__)

# BLE UUIDs
COSORI_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
COSORI_RX_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
COSORI_TX_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"

# Device information service
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
HARDWARE_REV_CHAR_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
SOFTWARE_REV_CHAR_UUID = "00002a28-0000-1000-8000-00805f9b34fb"


class CosoriKettleClient:
    """BLE client for Cosori Kettle."""
    
    def __init__(self, on_state_change: Optional[Callable[[dict], None]] = None):
        self.client: Optional[BleakClient] = None
        self.device: Optional[BLEDevice] = None
        self.rx_char: Optional[BleakGATTCharacteristic] = None
        self.tx_char: Optional[BleakGATTCharacteristic] = None
        
        self.parser = PacketParser()
        self.state_manager = StateManager(on_state_change)
        self.command_manager = CommandManager()
        
        self._running = False
        self._registration_complete = False
        self._registration_key: Optional[bytes] = None
        
        # Device version info
        self.hardware_version: Optional[str] = None
        self.software_version: Optional[str] = None
        self.protocol_version: ProtocolVersion = ProtocolVersion.V0
        self.use_scan_hello: bool = False
        self.requires_hello5: bool = True
        
        # Callbacks
        self.on_heating_complete: Optional[Callable[[], None]] = None
        self.on_hold_complete: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[int], None]] = None
    
    async def scan(self, name_filter: str = "Cosori") -> list[BLEDevice]:
        """Scan for Cosori kettles."""
        logger.info("Scanning for Cosori kettles...")
        devices = await BleakScanner.discover(timeout=5.0)
        filtered = [
            d for d in devices
            if d.name and name_filter.lower() in d.name.lower()
        ]
        return filtered
    
    async def find_device(self, name: str = "Cosori Gooseneck Kettle") -> Optional[BLEDevice]:
        """Find device by name."""
        device = await BleakScanner.find_device_by_name(name, cb={"use_bdaddr": True})
        return device
    
    async def connect(self, device: BLEDevice) -> bool:
        """Connect to kettle."""
        try:
            self.device = device
            self.client = BleakClient(device, disconnected_callback=self._on_disconnect)
            
            logger.info(f"Connecting to {device.name} ({device.address})...")
            await self.client.connect()
            
            # Services are automatically discovered on connection in newer bleak versions
            # Access them directly via client.services
            
            # Get characteristics
            service = self.client.services.get_service(COSORI_SERVICE_UUID)
            if not service:
                logger.error("Service not found")
                return False
            
            self.rx_char = service.get_characteristic(COSORI_RX_CHAR_UUID)
            self.tx_char = service.get_characteristic(COSORI_TX_CHAR_UUID)
            
            if not self.rx_char or not self.tx_char:
                logger.error("Characteristics not found")
                return False
            
            # Read device version information
            await self._read_device_info()
            
            # Subscribe to notifications
            await self.client.start_notify(self.rx_char, self._notification_handler)
            
            logger.info("Connected and subscribed to notifications")
            self.state_manager.set_connected(True)
            
            # Start background tasks
            self._running = True
            self._registration_complete = False
            
            # Start registration handshake (async, no FSM needed)
            asyncio.create_task(self._do_registration())
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.state_manager.set_connected(False)
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from kettle."""
        self._running = False
        
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        
        self.state_manager.set_connected(False)
        logger.info("Disconnected")
    
    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection."""
        logger.warning("Device disconnected")
        self.state_manager.set_connected(False)
        self._registration_complete = False
    
    async def _read_device_info(self) -> None:
        """Read hardware and software version from device info service."""
        self.use_scan_hello = False
        
        try:
            # Get device info service
            info_service = self.client.services.get_service(DEVICE_INFO_SERVICE_UUID)
            if not info_service:
                logger.warning("Device info service not found")
            else:
                # Read hardware revision
                hw_char = info_service.get_characteristic(HARDWARE_REV_CHAR_UUID)
                if hw_char:
                    hw_bytes = await self.client.read_gatt_char(hw_char)
                    self.hardware_version = hw_bytes.decode('utf-8', errors='ignore')
                    logger.info(f"Hardware version: {self.hardware_version}")
                
                # Read software revision
                sw_char = info_service.get_characteristic(SOFTWARE_REV_CHAR_UUID)
                if sw_char:
                    sw_bytes = await self.client.read_gatt_char(sw_char)
                    self.software_version = sw_bytes.decode('utf-8', errors='ignore')
                    logger.info(f"Software version: {self.software_version}")
                
                # Determine which hello packet to use
                if self.hardware_version == '1.0.00' and self.software_version == 'R0007V0012':
                    logger.info("Using scan.py hello payload for version 1.0.00/R0007V0012")
                    self.use_scan_hello = True
                else:
                    logger.info("Using default C++ hello payload")
                
        except Exception as e:
            logger.warning(f"Failed to read device info: {e}")
    
    def _notification_handler(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle BLE notification from device."""
        hex_str = ":".join(f"{b:02x}" for b in data)
        logger.info(f"RX: {hex_str}")
        
        self.parser.append_data(bytes(data))
        packets = self.parser.process_frames()
        
        for packet in packets:
            # Handle different packet types
            if isinstance(packet, StatusPacket):
                if packet.packet_type == "extended":
                    if not self._registration_complete:
                        self._registration_complete = True
                        logger.info("Registration handshake complete")
                
                # Check for error states
                if is_error_state(packet):
                    logger.error(f"Error state detected: error_code={packet.error_code}")
                    if self.on_error and packet.error_code is not None:
                        self.on_error(packet.error_code)
                
                self.state_manager.update_from_packet(packet)
            
            elif isinstance(packet, AckPacket):
                # Handle command acknowledgment
                logger.info(f"ACK received: seq={packet.seq}, success={packet.success}")
                self.command_manager.handle_ack(packet)
            
            elif isinstance(packet, CompletionPacket):
                # Handle completion notification
                logger.info(f"Completion: {packet.status.name}")
                if packet.status == CompletionStatus.DONE and self.on_heating_complete:
                    self.on_heating_complete()
                elif packet.status == CompletionStatus.HOLD_COMPLETE and self.on_hold_complete:
                    self.on_hold_complete()
    
    async def _do_registration(self) -> None:
        """Perform registration handshake: hello -> delay -> status_request."""
        try:
            hello_pkt = PacketBuilder.make_hello(0)
            await self._send_packet_split(hello_pkt)
            
            await asyncio.sleep(HANDSHAKE_DELAY_MS / 1000.0)
            
            seq = self.state_manager.next_tx_seq()
            status_req = PacketBuilder.make_status_request(seq)
            await self._send_packet_split(status_req)
        except Exception as e:
            logger.error(f"Registration error: {e}")
    
    async def _send_packet_split(self, packet: bytes, wait_for_ack: bool = False, 
                                  seq: Optional[int] = None, command: Optional[bytes] = None,
                                  timeout: float = 1.0) -> bool:
        """Send packet, splitting into 20-byte chunks if needed.
        
        Args:
            packet: Packet bytes to send
            wait_for_ack: Whether to wait for ACK
            seq: Sequence number (required if wait_for_ack=True)
            command: Command bytes (required if wait_for_ack=True)
            timeout: ACK timeout in seconds
            
        Returns:
            True if sent successfully (and ACK received if requested), False otherwise
        """
        if not self.tx_char or not self.client or not self.client.is_connected:
            return False
        
        # Register command if waiting for ACK
        if wait_for_ack:
            if seq is None or command is None:
                raise ValueError("seq and command required when wait_for_ack=True")
            self.command_manager.register_command(seq, command)
        
        # Send packet
        max_size = 20
        if len(packet) <= max_size:
            hex_str = ":".join(f"{b:02x}" for b in packet)
            logger.info(f"TX: {hex_str}")
            await self.client.write_gatt_char(self.tx_char, packet, response=False)
        else:
            for i in range(0, len(packet), max_size):
                chunk = packet[i:i + max_size]
                hex_str = ":".join(f"{b:02x}" for b in chunk)
                logger.info(f"TX: {hex_str} (chunk {i//max_size + 1})")
                await self.client.write_gatt_char(self.tx_char, chunk, response=False)
        
        # Wait for ACK if requested
        if wait_for_ack:
            ack_received = await self.command_manager.wait_for_ack(seq, timeout)
            if not ack_received:
                logger.warning(f"ACK timeout for seq={seq}")
            return ack_received
        
        return True
    
    async def send_packet(self, packet: bytes) -> None:
        """Send packet manually."""
        if not self.tx_char or not self.client or not self.client.is_connected:
            raise RuntimeError("Not connected")
        await self._send_packet_split(packet)
    
    async def request_status(self) -> None:
        """Send status request."""
        if not self.is_connected():
            return
        seq = self.state_manager.next_tx_seq()
        status_req = PacketBuilder.make_status_request(seq)
        await self.send_packet(status_req)
    
    async def set_target_temperature(self, temp_f: float) -> None:
        """Set target temperature and start heating (V0 protocol).
        
        Sequence: [hello5] -> delay -> setpoint -> delay -> ack -> delay -> ack
        Note: hello5 is optional depending on device version
        """
        temp_f = max(MIN_TEMP_F, min(MAX_TEMP_F, temp_f))
        temp_f_int = int(round(temp_f))
        self.state_manager.state.target_setpoint_f = temp_f
        mode = MODE_BOIL if temp_f_int == MAX_TEMP_F else MODE_HEAT
        
        logger.info(f"Setting target temperature to {temp_f_int}°F (mode={mode:02x})")
        
        # Send hello5 if required by device
        if self.requires_hello5:
            seq = self.state_manager.next_tx_seq()
            await self._send_packet_split(PacketBuilder.make_hello5(seq))
            await asyncio.sleep(PRE_SETPOINT_DELAY_MS / 1000.0)
        
        seq = self.state_manager.next_tx_seq()
        await self._send_packet_split(PacketBuilder.make_setpoint(seq, mode, temp_f_int))
        await asyncio.sleep(POST_SETPOINT_DELAY_MS / 1000.0)
        
        seq_base = self.state_manager.last_status_seq or self.state_manager.next_tx_seq()
        await self._send_packet_split(PacketBuilder.make_ack(seq_base, Command.STATUS_COMPACT))
        await asyncio.sleep(CONTROL_DELAY_MS / 1000.0)
        
        seq_ack = self.state_manager.next_tx_seq()
        await self._send_packet_split(PacketBuilder.make_ack(seq_ack, Command.STATUS_COMPACT))
        await asyncio.sleep(CONTROL_DELAY_MS / 1000.0)
    
    async def start_heating(self) -> None:
        """Start heating to target temperature."""
        temp_f = self.state_manager.state.target_setpoint_f
        await self.set_target_temperature(temp_f)
    
    async def stop_heating(self) -> None:
        """Stop heating.
        
        Sequence: stop -> delay -> ack -> delay -> stop
        """
        logger.info("Stopping heating")
        
        seq = self.state_manager.next_tx_seq()
        stop_pkt = PacketBuilder.make_stop(seq, self.protocol_version)
        
        if self.protocol_version == ProtocolVersion.V1:
            # V1 protocol: send stop and wait for ACK
            await self._send_packet_split(stop_pkt, wait_for_ack=True, seq=seq, 
                                         command=Command.V1_STOP, timeout=1.0)
        else:
            # V0 protocol: legacy sequence
            await self._send_packet_split(stop_pkt)
            await asyncio.sleep(CONTROL_DELAY_MS / 1000.0)
            
            seq_ctrl = self.state_manager.last_status_seq or self.state_manager.next_tx_seq()
            await self._send_packet_split(PacketBuilder.make_ack(seq_ctrl, Command.STATUS_COMPACT))
            await asyncio.sleep(CONTROL_DELAY_MS / 1000.0)
            
            seq = self.state_manager.next_tx_seq()
            await self._send_packet_split(PacketBuilder.make_stop(seq, self.protocol_version))
    
    async def register(self, registration_key: Optional[bytes] = None) -> bool:
        """Register with device (pairing mode required).
        
        Args:
            registration_key: 32-byte ASCII hex registration key (generates new if None)
            
        Returns:
            True if registration successful, False otherwise
        """
        if registration_key is None:
            registration_key = generate_registration_key()
        
        logger.info("Registering with device (pairing mode required)")
        
        seq = self.state_manager.next_tx_seq()
        register_pkt = PacketBuilder.make_register(seq, registration_key)
        
        success = await self._send_packet_split(register_pkt, wait_for_ack=True, 
                                                seq=seq, command=Command.V1_REGISTER, 
                                                timeout=2.0)
        
        if success:
            self._registration_key = registration_key
            logger.info("Registration successful")
        else:
            logger.error("Registration failed")
        
        return success
    
    async def start_heating_v1(self, mode: OperatingMode, enable_hold: bool = False, 
                               hold_minutes: int = 0) -> bool:
        """Start heating using V1 protocol.
        
        Args:
            mode: Operating mode
            enable_hold: Enable keep-warm after heating
            hold_minutes: Hold time in minutes
            
        Returns:
            True if command successful
        """
        logger.info(f"Starting heating: mode={mode.name}, hold={enable_hold}, hold_time={hold_minutes}min")
        
        seq = self.state_manager.next_tx_seq()
        hold_seconds = hold_minutes * 60
        start_pkt = PacketBuilder.make_v1_start(seq, mode, enable_hold, hold_seconds)
        
        return await self._send_packet_split(start_pkt, wait_for_ack=True, 
                                            seq=seq, command=Command.V1_START, timeout=1.0)
    
    async def start_delayed_v1(self, delay_minutes: int, mode: OperatingMode, 
                              enable_hold: bool = False, hold_minutes: int = 0) -> bool:
        """Start heating with delay using V1 protocol.
        
        Args:
            delay_minutes: Delay in minutes before starting
            mode: Operating mode
            enable_hold: Enable keep-warm after heating
            hold_minutes: Hold time in minutes
            
        Returns:
            True if command successful
        """
        logger.info(f"Delayed start: delay={delay_minutes}min, mode={mode.name}, "
                   f"hold={enable_hold}, hold_time={hold_minutes}min")
        
        seq = self.state_manager.next_tx_seq()
        delay_seconds = delay_minutes * 60
        hold_seconds = hold_minutes * 60
        delay_pkt = PacketBuilder.make_v1_delay_start(seq, delay_seconds, mode, 
                                                      enable_hold, hold_seconds)
        
        return await self._send_packet_split(delay_pkt, wait_for_ack=True, 
                                            seq=seq, command=Command.V1_DELAY_START, timeout=1.0)
    
    async def set_mytemp(self, temp_f: int) -> bool:
        """Set custom temperature for MY_TEMP mode.
        
        Args:
            temp_f: Temperature in Fahrenheit
            
        Returns:
            True if command successful
        """
        temp_f = max(MIN_TEMP_F, min(MAX_TEMP_F, temp_f))
        logger.info(f"Setting mytemp to {temp_f}°F")
        
        seq = self.state_manager.next_tx_seq()
        mytemp_pkt = PacketBuilder.make_v1_set_mytemp(seq, temp_f)
        
        return await self._send_packet_split(mytemp_pkt, wait_for_ack=True, 
                                            seq=seq, command=Command.V1_SET_MYTEMP, timeout=1.0)
    
    async def set_baby_formula_mode(self, enabled: bool) -> bool:
        """Set baby formula mode.
        
        Args:
            enabled: Enable or disable baby formula mode
            
        Returns:
            True if command successful
        """
        logger.info(f"Setting baby formula mode: {enabled}")
        
        seq = self.state_manager.next_tx_seq()
        baby_pkt = PacketBuilder.make_v1_set_baby_mode(seq, enabled)
        
        return await self._send_packet_split(baby_pkt, wait_for_ack=True, 
                                            seq=seq, command=Command.V1_SET_BABY_MODE, timeout=1.0)
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return (
            self.client is not None
            and self.client.is_connected
            and self.state_manager.state.connected
        )
    
    @property
    def state(self):
        """Get current state."""
        return self.state_manager.state
    
    @property
    def registration_complete(self) -> bool:
        """Check if registration is complete."""
        return self._registration_complete
    
    @property
    def is_registered(self) -> bool:
        """Check if device has been registered."""
        return self._registration_key is not None
