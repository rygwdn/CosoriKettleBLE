#include "envelope.h"

namespace esphome {
namespace cosori_kettle_ble {

static constexpr uint8_t FRAME_MAGIC = 0xA5;

std::vector<uint8_t> Envelope::build(uint8_t frame_type, uint8_t seq, const uint8_t *payload, size_t payload_len) {
  std::vector<uint8_t> packet;
  packet.reserve(6 + payload_len);  // 6-byte header + payload

  // Header: magic, type, seq, len_lo, len_hi, checksum
  packet.push_back(FRAME_MAGIC);
  packet.push_back(frame_type);
  packet.push_back(seq);
  packet.push_back(payload_len & 0xFF);           // len_lo
  packet.push_back((payload_len >> 8) & 0xFF);    // len_hi
  packet.push_back(calculate_checksum(frame_type, seq, payload_len));

  // Append payload
  if (payload != nullptr && payload_len > 0) {
    packet.insert(packet.end(), payload, payload + payload_len);
  }

  return packet;
}

std::vector<std::vector<uint8_t>> Envelope::chunk(const std::vector<uint8_t> &packet) {
  std::vector<std::vector<uint8_t>> chunks;

  if (packet.empty()) {
    return chunks;
  }

  // Split into 20-byte chunks
  for (size_t i = 0; i < packet.size(); i += BLE_CHUNK_SIZE) {
    size_t chunk_size = (i + BLE_CHUNK_SIZE <= packet.size()) ? BLE_CHUNK_SIZE : (packet.size() - i);
    std::vector<uint8_t> chunk(packet.begin() + i, packet.begin() + i + chunk_size);
    chunks.push_back(chunk);
  }

  return chunks;
}

uint8_t Envelope::calculate_checksum(uint8_t frame_type, uint8_t seq, uint16_t payload_len) {
  return (FRAME_MAGIC + frame_type + seq + (payload_len & 0xFF) + ((payload_len >> 8) & 0xFF)) & 0xFF;
}

}  // namespace cosori_kettle_ble
}  // namespace esphome
