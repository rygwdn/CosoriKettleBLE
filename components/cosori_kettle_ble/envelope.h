#pragma once

#include <cstdint>
#include <cstddef>

namespace esphome {
namespace cosori_kettle_ble {

// BLE characteristic write limit
static constexpr size_t BLE_CHUNK_SIZE = 20;
// Buffer size for envelope (must match MAX_FRAME_BUFFER_SIZE in cosori_kettle_ble.cpp)
static constexpr size_t ENVELOPE_BUFFER_SIZE = 512;

class Envelope {
 public:
  Envelope() : size_(0), pos_(0) {}

  // Clear the buffer and reset position
  void clear() { 
    size_ = 0; 
    pos_ = 0;
  }

  // Get current size (total data in buffer)
  size_t size() const { return size_; }
  
  // Get remaining unread data size
  size_t remaining() const { return (pos_ < size_) ? (size_ - pos_) : 0; }

  // Get read position
  size_t position() const { return pos_; }
  
  // Set read position
  void set_position(size_t pos) { pos_ = (pos <= size_) ? pos : size_; }
  
  // Advance read position
  void advance(size_t count) {
    pos_ += count;
    if (pos_ > size_) {
      pos_ = size_;
    }
  }

  // Get pointer to buffer data (from start)
  const uint8_t *data() const { return buffer_; }
  uint8_t *data() { return buffer_; }
  
  // Get pointer to current read position
  const uint8_t *read_ptr() const { return buffer_ + pos_; }
  uint8_t *read_ptr() { return buffer_ + pos_; }

  // Append data to buffer
  bool append(const uint8_t *data, size_t len) {
    if (size_ + len > ENVELOPE_BUFFER_SIZE) {
      return false;  // Buffer overflow
    }
    for (size_t i = 0; i < len; i++) {
      buffer_[size_++] = data[i];
    }
    return true;
  }

  // Build a complete packet with envelope header into this buffer
  bool build(uint8_t frame_type, uint8_t seq, const uint8_t *payload, size_t payload_len) {
    size_t total_len = 6 + payload_len;  // 6-byte header + payload
    if (total_len > ENVELOPE_BUFFER_SIZE) {
      return false;  // Too large
    }

    size_ = 0;
    pos_ = 0;
    buffer_[size_++] = 0xA5;  // FRAME_MAGIC
    buffer_[size_++] = frame_type;
    buffer_[size_++] = seq;
    buffer_[size_++] = payload_len & 0xFF;           // len_lo
    buffer_[size_++] = (payload_len >> 8) & 0xFF;    // len_hi
    buffer_[size_++] = calculate_checksum(frame_type, seq, payload_len);

    // Append payload
    if (payload != nullptr && payload_len > 0) {
      for (size_t i = 0; i < payload_len; i++) {
        buffer_[size_++] = payload[i];
      }
    }

    return true;
  }

  // Get chunk data at current position (for BLE transmission)
  // Returns pointer to chunk data and size
  const uint8_t *get_chunk_data(size_t chunk_index, size_t &chunk_size) const {
    size_t offset = chunk_index * BLE_CHUNK_SIZE;
    if (offset >= size_) {
      chunk_size = 0;
      return nullptr;
    }
    chunk_size = (offset + BLE_CHUNK_SIZE <= size_) ? BLE_CHUNK_SIZE : (size_ - offset);
    return buffer_ + offset;
  }
  
  // Get total number of chunks needed
  size_t get_chunk_count() const {
    if (size_ == 0) {
      return 0;
    }
    return (size_ + BLE_CHUNK_SIZE - 1) / BLE_CHUNK_SIZE;
  }

  // Frame processing structure
  struct FrameInfo {
    uint8_t frame_type;
    uint8_t seq;
    uint16_t payload_len;
    const uint8_t *payload;
    bool valid;
  };

  // Process next frame: finds, validates, and advances position
  // Returns FrameInfo with valid=true if a complete valid frame is found
  // Returns FrameInfo with valid=false if no valid frame found yet
  // Handles all position advancing internally
  FrameInfo process_next_frame(size_t max_payload_size) {
    FrameInfo info = {0, 0, 0, nullptr, false};
    
    while (true) {
      // Find frame start from current position
      size_t frame_start = find_frame_start();
      
      // If not found, advance position to end and return
      if (frame_start >= size_) {
        pos_ = size_;
        return info;  // No more frames
      }
      
      // Advance position to frame start
      pos_ = frame_start;
      
      // Validate frame header at current position
      uint8_t frame_type;
      uint8_t seq;
      uint16_t payload_len;
      uint8_t checksum;
      
      if (!validate_frame_header_at_pos(frame_type, seq, payload_len, checksum)) {
        // Invalid header, advance by 1 byte and continue searching
        pos_++;
        continue;
      }
      
      // Validate payload length
      if (payload_len > max_payload_size) {
        // Invalid payload length, advance by 1 byte and continue
        pos_++;
        continue;
      }
      
      size_t frame_len = 6 + payload_len;
      
      // Wait for complete frame
      if (pos_ + frame_len > size_) {
        // Not enough data yet, keep position at frame start
        return info;  // Frame not complete yet
      }
      
      // Extract payload
      const uint8_t *payload = buffer_ + pos_ + 6;
      
      // Fill in frame info
      info.frame_type = frame_type;
      info.seq = seq;
      info.payload_len = payload_len;
      info.payload = payload;
      info.valid = true;
      
      // Advance position past processed frame
      pos_ += frame_len;
      
      return info;
    }
  }
  
  // Compact buffer: move unprocessed data (from pos_ to size_) to front
  // This should be called periodically to free up space at the beginning
  void compact() {
    if (pos_ == 0) {
      return;  // Nothing to compact
    }
    if (pos_ >= size_) {
      // All data processed, clear buffer
      clear();
      return;
    }
    
    size_t remaining = size_ - pos_;
    // Shift remaining data to front
    for (size_t i = 0; i < remaining; i++) {
      buffer_[i] = buffer_[pos_ + i];
    }
    size_ = remaining;
    pos_ = 0;
  }

 private:
  // Find next frame start (FRAME_MAGIC) from current position
  size_t find_frame_start() const {
    for (size_t i = pos_; i < size_; i++) {
      if (buffer_[i] == 0xA5) {  // FRAME_MAGIC
        return i;
      }
    }
    return size_;  // Not found
  }
  
  // Validate frame header at current position
  // Returns true if valid frame header exists, fills in frame info
  bool validate_frame_header_at_pos(uint8_t &frame_type, uint8_t &seq, 
                                     uint16_t &payload_len, uint8_t &checksum) const {
    if (pos_ + 6 > size_) {
      return false;  // Not enough data for header
    }
    
    if (buffer_[pos_] != 0xA5) {  // FRAME_MAGIC
      return false;
    }
    
    frame_type = buffer_[pos_ + 1];
    seq = buffer_[pos_ + 2];
    payload_len = buffer_[pos_ + 3] | (buffer_[pos_ + 4] << 8);
    checksum = buffer_[pos_ + 5];
    
    // Validate checksum
    uint8_t calculated = calculate_checksum(frame_type, seq, payload_len);
    return (checksum == calculated);
  }

  // Calculate checksum for envelope header
  static uint8_t calculate_checksum(uint8_t frame_type, uint8_t seq, uint16_t payload_len);

  uint8_t buffer_[ENVELOPE_BUFFER_SIZE];
  size_t size_;  // Total data size
  size_t pos_;   // Read position
};

}  // namespace cosori_kettle_ble
}  // namespace esphome
