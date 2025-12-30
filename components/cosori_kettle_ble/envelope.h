#pragma once

#include <vector>
#include <cstdint>
#include <cstddef>

namespace esphome {
namespace cosori_kettle_ble {

// BLE characteristic write limit
static constexpr size_t BLE_CHUNK_SIZE = 20;

class Envelope {
 public:
  // Build a complete packet with envelope header
  static std::vector<uint8_t> build(uint8_t frame_type, uint8_t seq, const uint8_t *payload, size_t payload_len);

  // Split a packet into 20-byte chunks for BLE transmission
  static std::vector<std::vector<uint8_t>> chunk(const std::vector<uint8_t> &packet);

  // Calculate checksum for envelope header
  static uint8_t calculate_checksum(uint8_t frame_type, uint8_t seq, uint16_t payload_len);
};

}  // namespace cosori_kettle_ble
}  // namespace esphome
