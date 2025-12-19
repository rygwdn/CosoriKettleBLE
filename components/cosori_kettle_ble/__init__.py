"""ESPHome component for Cosori Kettle BLE."""
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import ble_client, climate
from esphome.const import CONF_ID

CODEOWNERS = ["@barrymichels"]
DEPENDENCIES = ["ble_client"]
AUTO_LOAD = ["sensor", "binary_sensor", "number", "switch", "climate"]

CONF_COSORI_KETTLE_BLE_ID = "cosori_kettle_ble_id"
CONF_HANDSHAKE = "handshake"

cosori_kettle_ble_ns = cg.esphome_ns.namespace("cosori_kettle_ble")
CosoriKettleBLE = cosori_kettle_ble_ns.class_(
    "CosoriKettleBLE", ble_client.BLEClientNode, cg.PollingComponent, climate.Climate
)

COSORI_KETTLE_BLE_COMPONENT_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_COSORI_KETTLE_BLE_ID): cv.use_id(CosoriKettleBLE),
    }
)


def validate_hex_string(value):
    """Validate that a string contains valid hex bytes."""
    value = cv.string(value)
    # Remove any spaces, colons, or 0x prefixes
    cleaned = value.replace(" ", "").replace(":", "").replace("0x", "").lower()
    if len(cleaned) % 2 != 0:
        raise cv.Invalid("Hex string must have even number of characters")
    try:
        bytes.fromhex(cleaned)
    except ValueError as e:
        raise cv.Invalid(f"Invalid hex string: {e}")
    return cleaned


CONFIG_SCHEMA = (
    climate._CLIMATE_SCHEMA.extend(
        {
            cv.GenerateID(): cv.declare_id(CosoriKettleBLE),
            cv.Optional(CONF_HANDSHAKE): cv.All(
                cv.ensure_list(validate_hex_string),
                cv.Length(min=3, max=3, msg="handshake must have exactly 3 packets"),
            ),
        }
    )
    .extend(cv.polling_component_schema("1s"))
    .extend(ble_client.BLE_CLIENT_SCHEMA)
)


async def to_code(config):
    """Code generation for the component."""
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await ble_client.register_ble_node(var, config)
    await climate.register_climate(var, config)

    if CONF_HANDSHAKE in config:
        for i, hex_str in enumerate(config[CONF_HANDSHAKE]):
            # Convert hex string to list of bytes
            byte_list = [int(hex_str[j:j+2], 16) for j in range(0, len(hex_str), 2)]
            cg.add(var.set_handshake_packet(i, byte_list))
