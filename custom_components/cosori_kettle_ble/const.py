"""Constants for the Cosori Kettle BLE integration."""
from typing import Final

DOMAIN: Final = "cosori_kettle_ble"

# BLE Service and Characteristics
SERVICE_UUID: Final = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_RX_UUID: Final = "0000fff1-0000-1000-8000-00805f9b34fb"  # Notify (device -> app)
CHAR_TX_UUID: Final = "0000fff2-0000-1000-8000-00805f9b34fb"  # Write (app -> device)

# Device Information Service (standard BLE service)
CHAR_HARDWARE_REVISION_UUID: Final = "00002a27-0000-1000-8000-00805f9b34fb"
CHAR_SOFTWARE_REVISION_UUID: Final = "00002a28-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER_UUID: Final = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_MANUFACTURER_UUID: Final = "00002a29-0000-1000-8000-00805f9b34fb"

# Protocol constants
FRAME_MAGIC: Final = 0xA5
MESSAGE_HEADER_TYPE: Final = 0x22  # A522 = A5 + 22
ACK_HEADER_TYPE: Final = 0x12  # A512 = A5 + 12
BLE_CHUNK_SIZE: Final = 20

# Protocol versions
PROTOCOL_VERSION_V0: Final = 0x00
PROTOCOL_VERSION_V1: Final = 0x01

# Command IDs
CMD_REGISTER: Final = 0x80
CMD_HELLO: Final = 0x81
CMD_POLL: Final = 0x40
CMD_CTRL: Final = 0x41
CMD_SET_MODE: Final = 0xF0
CMD_SET_HOLD_TIME: Final = 0xF2
CMD_SET_MY_TEMP: Final = 0xF3
CMD_STOP: Final = 0xF4
CMD_SET_BABY_FORMULA: Final = 0xF5

# Command types
CMD_TYPE_D1: Final = 0xD1
CMD_TYPE_A3: Final = 0xA3
CMD_TYPE_40: Final = 0x40

# Temperature limits (Fahrenheit)
MIN_TEMP_F: Final = 104
MAX_TEMP_F: Final = 212
MIN_VALID_READING_F: Final = 40
MAX_VALID_READING_F: Final = 230

# Operating modes
MODE_BOIL: Final = 0x04
MODE_HEAT: Final = 0x06
MODE_GREEN_TEA: Final = 0x01
MODE_GREEN_TEA_F: Final = 180
MODE_OOLONG: Final = 0x02
MODE_OOLONG_F: Final = 195
MODE_COFFEE: Final = 0x03
MODE_COFFEE_F: Final = 205
MODE_MY_TEMP: Final = 0x05

# Mode names
MODE_NAMES: Final = {
    MODE_BOIL: "Boil",
    MODE_HEAT: "Heat",
    MODE_GREEN_TEA: "Green Tea",
    MODE_OOLONG: "Oolong",
    MODE_COFFEE: "Coffee",
    MODE_MY_TEMP: "MyBrew",
}

# Configuration
CONF_DEVICE_ID: Final = "device_id"
CONF_PROTOCOL_VERSION: Final = "protocol_version"
CONF_REGISTRATION_KEY: Final = "registration_key"

# Update interval and retry settings
UPDATE_INTERVAL: Final = 15  # seconds
ACK_TIMEOUT_RETRY_DELAY: Final = 5  # seconds before retrying after ACK timeout
MAX_RECONNECT_ATTEMPTS: Final = 3  # max attempts to reconnect on disconnect
