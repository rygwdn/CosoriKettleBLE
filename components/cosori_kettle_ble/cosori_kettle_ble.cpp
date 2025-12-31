#include "cosori_kettle_ble.h"
#include "envelope.h"
#include "protocol.h"
#include "esphome/core/log.h"
#include "esphome/core/application.h"
#include <cmath>
#include <cstring>

#ifdef USE_ESP32

namespace esphome {
namespace cosori_kettle_ble {

static const char *const TAG = "cosori_kettle_ble";

// Static buffer instances
Envelope CosoriKettleBLE::send_buffer;
Envelope CosoriKettleBLE::recv_buffer;

// Buffer size limits
static constexpr size_t MAX_FRAME_BUFFER_SIZE = 512;
static constexpr size_t MAX_PAYLOAD_SIZE = 256;

// Protocol constants are now defined in envelope.h

// Temperature limits and operating modes are now defined in protocol.h

// Timing constants (milliseconds)
static constexpr uint32_t HANDSHAKE_TIMEOUT_MS = 10000;
static constexpr uint32_t PRE_SETPOINT_DELAY_MS = 60;
static constexpr uint32_t POST_SETPOINT_DELAY_MS = 100;
static constexpr uint32_t CONTROL_DELAY_MS = 50;
static constexpr uint32_t STATUS_TIMEOUT_MS = 2000;

// Online/offline tracking
static constexpr uint8_t NO_RESPONSE_THRESHOLD = 10;

// BLE UUIDs
static const char *COSORI_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb";
static const char *COSORI_RX_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb";
static const char *COSORI_TX_CHAR_UUID = "0000fff2-0000-1000-8000-00805f9b34fb";

std::string bytes_to_hex_string(const uint8_t *data, size_t len) {
  std::string hex_str;
  hex_str.reserve(len * 3);  // Pre-allocate: "xx:" per byte
  for (size_t i = 0; i < len; i++) {
    char buf[4];
    snprintf(buf, sizeof(buf), "%02x%s", data[i], (i < len - 1) ? ":" : "");
    hex_str += buf;
  }
  return hex_str;
}

void CosoriKettleBLE::setup() {
  ESP_LOGCONFIG(TAG, "Setting up Cosori Kettle BLE...");
  // Initialize state
  this->tx_seq_ = 0;
  this->last_rx_seq_ = 0;
  this->last_status_seq_ = 0;
  this->status_received_ = false;
  this->registration_sent_ = false;
  this->no_response_count_ = 0;

  // Initialize BLE connection switch to ON (enabled by default)
  if (this->ble_connection_switch_ != nullptr) {
    this->ble_connection_switch_->publish_state(true);
  }

  // Initialize climate state (ESPHome climate expects Celsius)
  this->mode = climate::CLIMATE_MODE_OFF;
  this->action = climate::CLIMATE_ACTION_IDLE;
  this->target_temperature = (this->target_setpoint_f_ - 32.0f) * 5.0f / 9.0f;
  this->current_temperature = (this->current_temp_f_ - 32.0f) * 5.0f / 9.0f;
}


void CosoriKettleBLE::dump_config() {
  ESP_LOGCONFIG(TAG, "Cosori Kettle BLE:");
  ESP_LOGCONFIG(TAG, "  MAC Address: %s", this->parent_->address_str());
  ESP_LOGCONFIG(TAG, "  Protocol Version: %d", this->protocol_version_);
  ESP_LOGCONFIG(TAG, "  Update Interval: %ums", this->get_update_interval());
  LOG_BINARY_SENSOR("  ", "On Base", this->on_base_binary_sensor_);
  LOG_BINARY_SENSOR("  ", "Heating", this->heating_binary_sensor_);
  LOG_SENSOR("  ", "Temperature", this->temperature_sensor_);
  LOG_SENSOR("  ", "Kettle Setpoint", this->kettle_setpoint_sensor_);
  LOG_SENSOR("  ", "Hold Time Remaining", this->hold_time_remaining_sensor_);
  LOG_NUMBER("  ", "Target Setpoint", this->target_setpoint_number_);
  LOG_NUMBER("  ", "Hold Time", this->hold_time_number_);
  LOG_NUMBER("  ", "My Temp", this->my_temp_number_);
  LOG_SWITCH("  ", "Heating Control", this->heating_switch_);
  LOG_SWITCH("  ", "BLE Connection", this->ble_connection_switch_);
  LOG_SWITCH("  ", "Baby Formula", this->baby_formula_switch_);
  LOG_SWITCH("  ", "Register", this->register_switch_);
}

void CosoriKettleBLE::update() {
  this->track_online_status_();
  if (!this->ble_enabled_) {
    return;
  }

  if (!this->is_connected()) {
    ESP_LOGD(TAG, "Not connected, skipping poll");
    return;
  }

  if (!this->registration_sent_) {
    ESP_LOGD(TAG, "Registration not complete, skipping poll");
    return;
  }

  // Process command state machine
  this->process_command_state_machine_();

  if (this->command_state_ != CommandState::IDLE) {
    return;
  }
  
  if (this->waiting_for_write_ack_) {
    return;
  }

  if (this->send_chunk_index_ < this->send_total_chunks_) {
    return;
  }

  this->send_status_request_();
}

void CosoriKettleBLE::gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                                           esp_ble_gattc_cb_param_t *param) {
  switch (event) {
    case ESP_GATTC_OPEN_EVT:
      ESP_LOGI(TAG, "BLE connection opened");
      break;

    case ESP_GATTC_DISCONNECT_EVT:
      ESP_LOGW(TAG, "BLE disconnected");
      this->node_state = esp32_ble_tracker::ClientState::IDLE;
      this->rx_char_handle_ = 0;
      this->tx_char_handle_ = 0;
      this->notify_handle_ = 0;
      recv_buffer.clear();
      this->registration_sent_ = false;
      this->status_received_ = false;
      this->no_response_count_ = 0;
      // Clear chunking state
      this->send_chunk_index_ = 0;
      this->send_total_chunks_ = 0;
      this->waiting_for_write_ack_ = false;
      break;

    case ESP_GATTC_SEARCH_CMPL_EVT: {
      ESP_LOGI(TAG, "Service search complete");

      // These UUIDs are 16-bit UUIDs in Bluetooth base UUID format
      // 0000fff0-0000-1000-8000-00805f9b34fb = 0xfff0
      auto service_uuid = esp32_ble_tracker::ESPBTUUID::from_uint16(0xfff0);
      auto rx_uuid = esp32_ble_tracker::ESPBTUUID::from_uint16(0xfff1);
      auto tx_uuid = esp32_ble_tracker::ESPBTUUID::from_uint16(0xfff2);

      // Get RX characteristic (for notifications)
      auto *rx_chr = this->parent_->get_characteristic(service_uuid, rx_uuid);
      if (rx_chr == nullptr) {
        ESP_LOGE(TAG, "RX characteristic not found");
        break;
      }
      this->rx_char_handle_ = rx_chr->handle;

      // Get TX characteristic (for writes)
      auto *tx_chr = this->parent_->get_characteristic(service_uuid, tx_uuid);
      if (tx_chr == nullptr) {
        ESP_LOGE(TAG, "TX characteristic not found");
        break;
      }
      this->tx_char_handle_ = tx_chr->handle;

      // Register for notifications
      auto status = esp_ble_gattc_register_for_notify(gattc_if, this->parent_->get_remote_bda(), rx_chr->handle);
      if (status) {
        ESP_LOGW(TAG, "esp_ble_gattc_register_for_notify failed, status=%d", status);
      }
      
      break;
    }

    case ESP_GATTC_REG_FOR_NOTIFY_EVT: {
      this->node_state = esp32_ble_tracker::ClientState::ESTABLISHED;
      ESP_LOGI(TAG, "Registered for notifications, sending registration handshake");

      // Send registration handshake
      if (this->use_register_command_) {
        this->send_register_();
      } else {
        this->send_hello_();
      }

      // Mark registration sent
      this->registration_sent_ = true;
      break;
    }

    case ESP_GATTC_WRITE_CHAR_EVT: {
      // Handle write acknowledgment for chunked packets
      if (this->waiting_for_write_ack_ && param->write.handle == this->tx_char_handle_) {
        if (param->write.status == ESP_GATT_OK) {
          // Move to next chunk
          this->send_chunk_index_++;
          this->waiting_for_write_ack_ = false;
          // Send next chunk if available
          this->send_next_chunk_();
        } else {
          ESP_LOGW(TAG, "Write failed, status=%d", param->write.status);
          this->send_chunk_index_ = 0;
          this->send_total_chunks_ = 0;
          this->waiting_for_write_ack_ = false;
        }
        this->process_command_state_machine_();
      }
      break;
    }

    case ESP_GATTC_NOTIFY_EVT: {
      if (param->notify.handle != this->rx_char_handle_)
        break;

      // Log full RX packet as hex dump (only when DEBUG level is enabled)
      // if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
        ESP_LOGD(TAG, "RX: %s", bytes_to_hex_string(param->notify.value, param->notify.value_len).c_str());
      // }

      // Check buffer size limit before appending
      if (recv_buffer.size() + param->notify.value_len > MAX_FRAME_BUFFER_SIZE) {
        ESP_LOGW(TAG, "Frame buffer overflow (%zu + %d > %zu), clearing buffer",
                 recv_buffer.size(), param->notify.value_len, MAX_FRAME_BUFFER_SIZE);
        recv_buffer.clear();
      }

      // Append to receive buffer
      if (!recv_buffer.append(param->notify.value, param->notify.value_len)) {
        ESP_LOGW(TAG, "Failed to append to receive buffer, clearing");
        recv_buffer.clear();
      }

      // Process complete frames
      this->process_frame_buffer_();
      this->process_command_state_machine_();
      break;
    }

    default:
      break;
  }
}

// ============================================================================
// Protocol Implementation - Packet Sending
// ============================================================================

void CosoriKettleBLE::send_hello_() {
  // Verify registration key is set
  if (!this->registration_key_set_) {
    ESP_LOGE(TAG, "Registration key not set - cannot send hello command");
    return;
  }
  
  // Start handshake state machine instead of blocking
  this->use_register_command_ = false;
  ESP_LOGI(TAG, "Starting handshake (hello)");
  this->command_state_ = CommandState::HANDSHAKE_START;
  this->command_state_time_ = millis();
}

void CosoriKettleBLE::send_register_() {
  // Verify registration key is set
  if (!this->registration_key_set_) {
    ESP_LOGE(TAG, "Registration key not set - cannot send register command");
    return;
  }
  
  // Start handshake state machine with register flag set
  this->use_register_command_ = true;
  ESP_LOGI(TAG, "Starting device registration (register)");
  this->command_state_ = CommandState::HANDSHAKE_START;
  this->command_state_time_ = millis();
}

void CosoriKettleBLE::send_status_request_() {
  if (!this->is_connected()) {
    ESP_LOGV(TAG, "Cannot send poll: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[4];
  size_t payload_len = build_status_request_payload(this->protocol_version_, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build POLL payload");
    return;
  }
  ESP_LOGV(TAG, "Sending POLL (seq=%02x)", seq);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send POLL");
  }
}

void CosoriKettleBLE::send_set_my_temp(uint8_t temp_f) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send set my temp: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[5];
  size_t payload_len = build_set_my_temp_payload(this->protocol_version_, temp_f, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build set my temp payload");
    return;
  }
  ESP_LOGD(TAG, "Sending set my temp %d°F (seq=%02x)", temp_f, seq);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send set my temp");
  }
}

void CosoriKettleBLE::send_set_baby_formula(bool enabled) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send set baby formula: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[5];
  size_t payload_len = build_set_baby_formula_payload(this->protocol_version_, enabled, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build set baby formula payload");
    return;
  }
  ESP_LOGD(TAG, "Sending set baby formula %s (seq=%02x)", enabled ? "enabled" : "disabled", seq);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send set baby formula");
  }
}

void CosoriKettleBLE::send_set_hold_time(uint16_t seconds) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send set hold time: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[8];
  size_t payload_len = build_set_hold_time_payload(this->protocol_version_, seconds, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build set hold time payload");
    return;
  }
  ESP_LOGD(TAG, "Sending set hold time %u seconds (seq=%02x)", seconds, seq);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send set hold time");
  }
}

void CosoriKettleBLE::send_set_mode(uint8_t mode, uint8_t temp_f) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send setpoint: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[9];
  if (this->protocol_version_ == 1) {
    if (mode == MODE_HEAT) {
      ESP_LOGW(TAG, "Cannot send set mode: HEAT mode not supported in V1");
      mode = MODE_BOIL;
    }
    if (mode != MODE_MY_TEMP) {
      temp_f = 0;
    }
  }

  size_t payload_len = build_set_mode_payload(this->protocol_version_, mode, temp_f, this->hold_time_seconds_, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build set mode payload");
    return;
  }
  ESP_LOGD(TAG, "Sending SETPOINT %d°F (seq=%02x, mode=%02x)", temp_f, seq, mode);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send SETPOINT");
  }
}

void CosoriKettleBLE::send_stop() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send F4: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  uint8_t payload[4];
  size_t payload_len = build_stop_payload(this->protocol_version_, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build stop payload");
    return;
  }
  ESP_LOGD(TAG, "Sending F4 (seq=%02x)", seq);
  if (!this->send_command(seq, payload, payload_len)) {
    ESP_LOGW(TAG, "Failed to send F4");
  }
}

void CosoriKettleBLE::send_request_compact_status_(uint8_t seq_base) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send CTRL: not connected");
    return;
  }
  
  uint8_t payload[4];
  size_t payload_len = build_compact_status_request_payload(this->protocol_version_, payload);
  if (payload_len == 0) {
    ESP_LOGW(TAG, "Failed to build compact status request payload");
    return;
  }
  ESP_LOGD(TAG, "Sending CTRL (seq=%02x)", seq_base);
  if (!this->send_command(seq_base, payload, payload_len, true)) {
    ESP_LOGW(TAG, "Failed to send CTRL");
  }
}

// ============================================================================
// Outgoing buffer management
// ============================================================================

bool CosoriKettleBLE::send_command(uint8_t seq, const uint8_t *payload, size_t payload_len, bool is_ack) {
  // if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    // ESP_LOGD(TAG, "Sending command: seq=%02x, payload=%s", seq, bytes_to_hex_string(payload, payload_len).c_str());
  // }

  if (this->tx_char_handle_ == 0) {
    ESP_LOGW(TAG, "TX characteristic not ready");
    return false;
  }

  // Check if already sending something or waiting
  if (this->waiting_for_write_ack_) {
    ESP_LOGW(TAG, "Cannot send command: already waiting for write acknowledgment");
    return false;
  }
  if (this->send_chunk_index_ < this->send_total_chunks_) {
    ESP_LOGW(TAG, "Cannot send command: already sending (chunk %zu/%zu)",
             this->send_chunk_index_, this->send_total_chunks_, this->waiting_for_write_ack_);
    return false;
  }

  // Set payload in send buffer
  bool success;
  if (is_ack) {
    success = send_buffer.set_ack_payload(seq, payload, payload_len);
  } else {
    success = send_buffer.set_message_payload(seq, payload, payload_len);
  }

  if (!success) {
    ESP_LOGW(TAG, "Failed to set payload in send buffer");
    return false;
  }

  // Log full TX packet as hex dump (only when DEBUG level is enabled)
  // if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    // ESP_LOGD(TAG, "TX: %s", bytes_to_hex_string(send_buffer.data(), send_buffer.size()).c_str());
  // }

  // Calculate total chunks needed
  this->send_total_chunks_ = send_buffer.get_chunk_count();
  
  if (this->send_total_chunks_ == 0) {
    ESP_LOGW(TAG, "No chunks to send");
    return false;
  }

  // Reset chunking state
  this->send_chunk_index_ = 0;
  this->waiting_for_write_ack_ = false;

  // Send first chunk immediately
  this->send_next_chunk_();
  return true;
}

void CosoriKettleBLE::send_packet_(const uint8_t *data, size_t len) {
  if (this->tx_char_handle_ == 0) {
    ESP_LOGW(TAG, "TX characteristic not ready");
    return;
  }

  // Check if already sending something or waiting
  if (this->waiting_for_write_ack_ || (this->send_chunk_index_ < this->send_total_chunks_)) {
    ESP_LOGW(TAG, "Cannot send packet: already sending (chunk %zu/%zu, waiting=%d)",
             this->send_chunk_index_, this->send_total_chunks_, this->waiting_for_write_ack_);
    return;
  }

  // Copy data to send_buffer (for raw packets like handshake)
  send_buffer.clear();
  if (!send_buffer.append(data, len)) {
    ESP_LOGW(TAG, "Failed to append data to send buffer");
    return;
  }

  // Log full TX packet as hex dump (only when DEBUG level is enabled)
  // if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    // ESP_LOGD(TAG, "TX: %s", bytes_to_hex_string(data, len).c_str());
  // }
  
  // Calculate total chunks needed
  this->send_total_chunks_ = send_buffer.get_chunk_count();
  
  if (this->send_total_chunks_ == 0) {
    ESP_LOGW(TAG, "No chunks to send");
    return;
  }

  // Reset chunking state
  this->send_chunk_index_ = 0;
  this->waiting_for_write_ack_ = false;

  // Send first chunk immediately
  this->send_next_chunk_();
}

void CosoriKettleBLE::send_next_chunk_() {
  if (this->tx_char_handle_ == 0) {
    ESP_LOGW(TAG, "TX characteristic not ready");
    this->send_chunk_index_ = 0;
    this->send_total_chunks_ = 0;
    this->waiting_for_write_ack_ = false;
    return;
  }

  // Check if we have more chunks to send
  if (this->send_chunk_index_ >= this->send_total_chunks_) {
    // All chunks sent
    this->send_chunk_index_ = 0;
    this->send_total_chunks_ = 0;
    this->waiting_for_write_ack_ = false;
    return;
  }
  
  // Get current chunk data and size
  size_t chunk_size = 0;
  const uint8_t *chunk_data = send_buffer.get_chunk_data(this->send_chunk_index_, chunk_size);
  
  if (chunk_data == nullptr || chunk_size == 0) {
    ESP_LOGW(TAG, "Invalid chunk data at index %zu", this->send_chunk_index_);
    this->send_chunk_index_ = 0;
    this->send_total_chunks_ = 0;
    this->waiting_for_write_ack_ = false;
    return;
  }

  size_t current_chunk = this->send_chunk_index_ + 1;

  // Send current chunk
  this->waiting_for_write_ack_ = true;

  auto status = esp_ble_gattc_write_char(this->parent_->get_gattc_if(), this->parent_->get_conn_id(),
                                          this->tx_char_handle_, chunk_size,
                                          const_cast<uint8_t *>(chunk_data),
                                          ESP_GATT_WRITE_TYPE_NO_RSP, ESP_GATT_AUTH_REQ_NONE);
  if (status) {
    ESP_LOGW(TAG, "Error sending chunk %zu/%zu, status=%d: %s", current_chunk, this->send_total_chunks_, status, bytes_to_hex_string(chunk_data, chunk_size).c_str());
    this->send_chunk_index_ = 0;
    this->send_total_chunks_ = 0;
    this->waiting_for_write_ack_ = false;
  } else {
    ESP_LOGD(TAG, "Sent chunk %zu/%zu (%zu bytes): %s", current_chunk, this->send_total_chunks_, chunk_size, bytes_to_hex_string(chunk_data, chunk_size).c_str());
  }
}


// ============================================================================
// Incoming Frame Processing
// ============================================================================

void CosoriKettleBLE::process_frame_buffer_() {
  while (true) {
    // Process next frame using Envelope's built-in validation and position management
    auto frame = recv_buffer.process_next_frame(MAX_PAYLOAD_SIZE);
    
    // If no valid frame found, break (either no more frames or incomplete frame)
    if (!frame.valid) {
      break;
    }

    // Update last RX sequence
    this->last_rx_seq_ = frame.seq;
    
    // if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    ESP_LOGD(TAG, "Processing frame: type=%02x, seq=%02x, payload=%s", frame.frame_type, frame.seq, bytes_to_hex_string(frame.payload, frame.payload_len).c_str());
    // }

    if (frame.frame_type == ACK_HEADER_TYPE && this->waiting_for_ack_complete_ && this->waiting_for_ack_seq_ == frame.seq) {
      this->waiting_for_ack_complete_ = false;
      this->last_ack_error_code_ = frame.payload_len > 4 ? static_cast<uint8_t>(frame.payload[4]) : 0;
      ESP_LOGD(TAG, "ACK complete: seq=%02x, error_code=%02x", frame.seq, this->last_ack_error_code_);
    }

    if (frame.frame_type == MESSAGE_HEADER_TYPE && frame.payload[1] == CMD_CTRL) {
      this->parse_compact_status_(frame.payload, frame.payload_len);
    } else if (frame.frame_type == ACK_HEADER_TYPE && frame.payload[1] == CMD_POLL) {
      this->parse_status_ack_(frame.payload, frame.payload_len);
    }
  }
  
  // Compact buffer periodically to free up space at the beginning
  recv_buffer.compact();
}

void CosoriKettleBLE::parse_compact_status_(const uint8_t *payload, size_t len) {
  CompactStatus status = parse_compact_status(payload, len);
  if (!status.valid) {
    return;
  }

  // Update state (temp, setpoint, heating only - no on-base detection from compact packets)
  this->current_temp_f_ = status.temp;
  this->kettle_setpoint_f_ = status.setpoint;
  this->heating_ = (status.status != 0);
  this->status_received_ = true;
  this->last_status_seq_ = this->last_rx_seq_;

  // Reset offline counter
  this->reset_online_status_();

  // Update entities
  this->update_entities_();
}

void CosoriKettleBLE::parse_status_ack_(const uint8_t *payload, size_t len) {
  ExtendedStatus status = parse_extended_status(payload, len);
  if (!status.valid) {
    return;
  }

  // Update state (temp, setpoint, heating)
  this->current_temp_f_ = status.temp;
  this->kettle_setpoint_f_ = status.setpoint;
  this->heating_ = (status.stage != 0);
  this->status_received_ = true;
  this->last_status_seq_ = this->last_rx_seq_;
  this->on_base_ = status.on_base;
  this->remaining_hold_time_seconds_ = status.remaining_hold_time;

  if (this->pending_my_temp_) {
    this->pending_my_temp_ = false;
    this->my_temp_f_ = status.my_temp;
    ESP_LOGD(TAG, "My temp update confirmed: %d°F", status.my_temp);
  } else {
    // Not pending, safe to update from device
    this->my_temp_f_ = status.my_temp;
  }

  if (this->pending_hold_time_) {
    this->pending_hold_time_ = false;
    this->hold_time_seconds_ = status.configured_hold_time;
    ESP_LOGD(TAG, "Hold time update confirmed: %u seconds", status.configured_hold_time);
  } else {
    // Not pending, safe to update from device
    this->hold_time_seconds_ = status.configured_hold_time;
  }

  if (this->pending_baby_formula_) {
    this->pending_baby_formula_ = false;
    this->baby_formula_enabled_ = status.baby_formula_enabled;
    ESP_LOGD(TAG, "Baby formula update confirmed: %s", status.baby_formula_enabled ? "enabled" : "disabled");
  } else {
    // Not pending, safe to update from device
    this->baby_formula_enabled_ = status.baby_formula_enabled;
  }

  this->reset_online_status_();
  this->update_entities_();
}

// ============================================================================
// Public Control Methods
// ============================================================================

void CosoriKettleBLE::set_target_setpoint(float temp_f) {
  // Clamp to valid range
  if (temp_f < MIN_TEMP_F)
    temp_f = MIN_TEMP_F;
  if (temp_f > MAX_TEMP_F)
    temp_f = MAX_TEMP_F;

  this->target_setpoint_f_ = temp_f;
  ESP_LOGI(TAG, "Target setpoint changed to %.0f°F", temp_f);
  
  // Update number entity if it exists
  if (this->target_setpoint_number_ != nullptr) {
    this->target_setpoint_number_->publish_state(temp_f);
  }
}

void CosoriKettleBLE::set_register_enabled(bool enabled) {
  if (this->register_switch_ != nullptr) {
    this->use_register_command_ = enabled;
    this->register_switch_->publish_state(enabled);
  }

  if (enabled) {
    ESP_LOGI(TAG, "Registering device with kettle");
    this->send_register_();
  } else {
    ESP_LOGI(TAG, "Sending hello command");
    this->send_hello_();
  }
}

// TODO: add - delay start: 01F1 A300 {2b delay in seconds} {set mode payload}

void CosoriKettleBLE::set_hold_time(float seconds) {
  // Clamp to valid range (0-65535 seconds)
  if (seconds < 0.0f)
    seconds = 0.0f;
  if (seconds > 65535.0f)
    seconds = 65535.0f;

  uint16_t seconds_int = static_cast<uint16_t>(std::round(seconds));
  this->hold_time_seconds_ = seconds_int;
  this->pending_hold_time_ = true;
  ESP_LOGI(TAG, "Hold time changed to %u seconds", seconds_int);
  
  // Update number entity if it exists
  if (this->hold_time_number_ != nullptr) {
    this->hold_time_number_->publish_state(seconds);
  }

  // Send command to device
  if (this->is_connected()) {
    this->send_set_hold_time(seconds_int);
    // Clear pending flag after a delay (status update will confirm)
    // For now, we'll clear it when we receive a status update
  } else {
    this->pending_hold_time_ = false;
  }
}

void CosoriKettleBLE::set_my_temp(float temp_f) {
  // Clamp to valid range
  if (temp_f < MIN_TEMP_F)
    temp_f = MIN_TEMP_F;
  if (temp_f > MAX_TEMP_F)
    temp_f = MAX_TEMP_F;

  uint8_t temp_int = static_cast<uint8_t>(std::round(temp_f));
  this->my_temp_f_ = temp_int;
  this->pending_my_temp_ = true;
  ESP_LOGI(TAG, "My temp changed to %d°F", temp_int);
  
  // Update number entity if it exists
  if (this->my_temp_number_ != nullptr) {
    this->my_temp_number_->publish_state(temp_f);
  }

  // Send command to device
  if (this->is_connected()) {
    this->send_set_my_temp(temp_int);
  } else {
    this->pending_my_temp_ = false;
  }
}

void CosoriKettleBLE::set_baby_formula_enabled(bool enabled) {
  this->baby_formula_enabled_ = enabled;
  this->pending_baby_formula_ = true;
  ESP_LOGI(TAG, "Baby formula mode changed to %s", enabled ? "enabled" : "disabled");
  
  // Update switch entity if it exists
  if (this->baby_formula_switch_ != nullptr) {
    this->baby_formula_switch_->publish_state(enabled);
  }

  // Send command to device
  if (this->is_connected()) {
    this->send_set_baby_formula(enabled);
  } else {
    this->pending_baby_formula_ = false;
  }
}

void CosoriKettleBLE::start_heating() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot start heating: not connected");
    return;
  }

  uint8_t temp_f = static_cast<uint8_t>(std::round(this->target_setpoint_f_));
  uint8_t mode = (temp_f == MAX_TEMP_F) ? MODE_BOIL : MODE_HEAT;
  auto command_state = CommandState::HEAT_START;

  if (this->protocol_version_ == 1 && mode == MODE_HEAT) {
    // V1 doesn't support MODE_HEAT, so we need to use mytemp or set mode first
    if (temp_f == MODE_GREEN_TEA_F) {
      mode = MODE_GREEN_TEA;
    } else if (temp_f == MODE_OOLONG_F) {
      mode = MODE_OOLONG;
    } else if (temp_f == MODE_COFFEE_F) {
      mode = MODE_COFFEE;
    } else {
      mode = MODE_MY_TEMP;
      command_state = CommandState::HEAT_SET_TEMP;
    }
  }

  ESP_LOGI(TAG, "Starting kettle at %.0f°F", this->target_setpoint_f_);

  // Store parameters and start state machine
  this->pending_temp_f_ = temp_f;
  this->pending_mode_ = mode;
  this->command_state_ = command_state;
  this->command_state_time_ = millis();
}

void CosoriKettleBLE::stop_heating() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot stop heating: not connected");
    return;
  }

  ESP_LOGI(TAG, "Stopping kettle");

  // Start stop sequence state machine
  this->command_state_ = CommandState::STOP;
  this->command_state_time_ = millis();
}

void CosoriKettleBLE::enable_ble_connection(bool enable) {
  this->ble_enabled_ = enable;

  if (!enable && this->is_connected()) {
    ESP_LOGI(TAG, "Disabling BLE connection");
    // Disconnect
    this->parent_->set_enabled(false);
  } else if (enable && !this->is_connected()) {
    ESP_LOGI(TAG, "Enabling BLE connection");
    // Reconnect
    this->parent_->set_enabled(true);
  }

  // Update switch state to reflect actual setting
  if (this->ble_connection_switch_ != nullptr) {
    this->ble_connection_switch_->publish_state(enable);
  }
}

void CosoriKettleBLE::set_registration_key(const std::array<uint8_t, 16> &key) {
  this->registration_key_ = key;
  this->registration_key_set_ = true;
  ESP_LOGD(TAG, "Registration key set");
}

// ============================================================================
// Climate Interface
// ============================================================================

climate::ClimateTraits CosoriKettleBLE::traits() {
  auto traits = climate::ClimateTraits();

  // Temperature range in Celsius (ESPHome expects Celsius)
  // 104°F = 40°C, 212°F = 100°C
  traits.add_feature_flags(climate::CLIMATE_SUPPORTS_CURRENT_TEMPERATURE);
  traits.set_visual_min_temperature(40.0f);
  traits.set_visual_max_temperature(100.0f);
  traits.set_visual_temperature_step(0.5f);

  // Supported modes
  traits.set_supported_modes({
    climate::CLIMATE_MODE_OFF,
    climate::CLIMATE_MODE_HEAT,
  });

  // Supported actions
  traits.add_feature_flags(climate::CLIMATE_SUPPORTS_ACTION);

  return traits;
}

void CosoriKettleBLE::control(const climate::ClimateCall &call) {
  // Handle mode change
  if (call.get_mode().has_value()) {
    climate::ClimateMode mode = *call.get_mode();

    if (mode == climate::CLIMATE_MODE_OFF) {
      ESP_LOGI(TAG, "Climate: Setting mode to OFF");
      this->stop_heating();
      this->mode = climate::CLIMATE_MODE_OFF;
    } else if (mode == climate::CLIMATE_MODE_HEAT) {
      ESP_LOGI(TAG, "Climate: Setting mode to HEAT");
      this->mode = climate::CLIMATE_MODE_HEAT;
      // Start heating if we have a target temperature
      if (this->target_temperature > 0) {
        this->start_heating();
      }
    }
  }

  // Handle target temperature change
  if (call.get_target_temperature().has_value()) {
    float temp_c = *call.get_target_temperature();
    // Convert Celsius to Fahrenheit for the kettle
    float temp_f = temp_c * 9.0f / 5.0f + 32.0f;
    ESP_LOGI(TAG, "Climate: Setting target temperature to %.1f°C (%.0f°F)", temp_c, temp_f);
    this->target_temperature = temp_c;
    this->target_setpoint_f_ = temp_f;

    // Update number entity if it exists
    if (this->target_setpoint_number_ != nullptr) {
      this->target_setpoint_number_->publish_state(temp_f);
    }

    // If in heat mode, apply the new temperature
    if (this->mode == climate::CLIMATE_MODE_HEAT) {
      this->start_heating();
    }
  }

  // Publish updated state
  this->publish_state();
}

// ============================================================================
// State Management
// ============================================================================

uint8_t CosoriKettleBLE::next_tx_seq_() {
  if (this->tx_seq_ == 0 && this->last_rx_seq_ != 0) {
    this->tx_seq_ = (this->last_rx_seq_ + 1) & 0xFF;
  } else {
    this->tx_seq_ = (this->tx_seq_ + 1) & 0xFF;
  }
  return this->tx_seq_;
}

void CosoriKettleBLE::update_sensors_() {
  if (this->temperature_sensor_ != nullptr) {
    this->temperature_sensor_->publish_state(this->current_temp_f_);
  }

  if (this->kettle_setpoint_sensor_ != nullptr) {
    this->kettle_setpoint_sensor_->publish_state(this->kettle_setpoint_f_);
  }

  if (this->hold_time_remaining_sensor_ != nullptr) {
    this->hold_time_remaining_sensor_->publish_state(static_cast<float>(this->remaining_hold_time_seconds_));
  }

  if (this->on_base_binary_sensor_ != nullptr) {
    this->on_base_binary_sensor_->publish_state(this->on_base_);
  }

  if (this->heating_binary_sensor_ != nullptr) {
    this->heating_binary_sensor_->publish_state(this->heating_);
  }
}

void CosoriKettleBLE::update_mutable_entities_() {
  if (this->command_state_ != CommandState::IDLE) {
    return;
  }

  if (this->target_setpoint_number_ != nullptr) {
    this->target_setpoint_number_->publish_state(this->target_setpoint_f_);
  }

  if (this->hold_time_number_ != nullptr && !this->pending_hold_time_) {
    this->hold_time_number_->publish_state(static_cast<float>(this->hold_time_seconds_));
  }

  if (this->my_temp_number_ != nullptr && !this->pending_my_temp_) {
    this->my_temp_number_->publish_state(static_cast<float>(this->my_temp_f_));
  }

  if (this->baby_formula_switch_ != nullptr && !this->pending_baby_formula_) {
    this->baby_formula_switch_->publish_state(this->baby_formula_enabled_);
  }

  if (this->heating_switch_ != nullptr) {
    this->heating_switch_->publish_state(this->heating_);
  }
}

void CosoriKettleBLE::update_entities_() {
  this->update_sensors_();
  this->update_mutable_entities_();
  this->update_climate_state_();
}

void CosoriKettleBLE::update_climate_state_() {
  // Update current temperature (convert F to C for ESPHome climate)
  this->current_temperature = (this->current_temp_f_ - 32.0f) * 5.0f / 9.0f;

  // Initialize target temperature from kettle on first status
  // Use number entity's has_state() to determine if initialized
  bool target_initialized = (this->target_setpoint_number_ != nullptr) && 
                            this->target_setpoint_number_->has_state();
  if (!target_initialized) {
    this->target_setpoint_f_ = this->kettle_setpoint_f_;
    this->target_temperature = (this->kettle_setpoint_f_ - 32.0f) * 5.0f / 9.0f;
    ESP_LOGI(TAG, "Climate: Initialized target temperature to %.0f°F (%.1f°C) from kettle",
             this->target_setpoint_f_, this->target_temperature);
  }

  if (this->on_base_ && this->heating_) {
    this->mode = climate::CLIMATE_MODE_HEAT;
    this->action = climate::CLIMATE_ACTION_HEATING;
  } else {
    this->mode = climate::CLIMATE_MODE_OFF;
    this->action = climate::CLIMATE_ACTION_IDLE;
  }

  // Publish climate state
  this->publish_state();
}

void CosoriKettleBLE::track_online_status_() {
  if (this->no_response_count_ < NO_RESPONSE_THRESHOLD) {
    this->no_response_count_++;
  }

  if (this->no_response_count_ >= NO_RESPONSE_THRESHOLD && this->status_received_) {
    ESP_LOGW(TAG, "No response from kettle, marking offline");
    this->status_received_ = false;

    // Publish unavailable state
    if (this->temperature_sensor_ != nullptr)
      this->temperature_sensor_->publish_state(NAN);
    if (this->kettle_setpoint_sensor_ != nullptr)
      this->kettle_setpoint_sensor_->publish_state(NAN);
    if (this->hold_time_remaining_sensor_ != nullptr)
      this->hold_time_remaining_sensor_->publish_state(NAN);
    if (this->on_base_binary_sensor_ != nullptr)
      this->on_base_binary_sensor_->invalidate_state();
    if (this->heating_binary_sensor_ != nullptr)
      this->heating_binary_sensor_->invalidate_state();

    if (this->hold_time_number_ != nullptr)
      this->hold_time_number_->publish_state(NAN);
    if (this->my_temp_number_ != nullptr)
      this->my_temp_number_->publish_state(NAN);
    if (this->target_setpoint_number_ != nullptr)
      this->target_setpoint_number_->publish_state(NAN);

    // if (this->baby_formula_switch_ != nullptr)
    //   this->baby_formula_switch_->publish_state(false);
    // if (this->heating_switch_ != nullptr)
    //   this->heating_switch_->publish_state(false);
    // if (this->ble_connection_switch_ != nullptr)
    //   this->ble_connection_switch_->publish_state(false);
  }
}

void CosoriKettleBLE::reset_online_status_() {
  this->no_response_count_ = 0;
}

// ============================================================================
// Command State Machine
// ============================================================================

void CosoriKettleBLE::process_command_state_machine_() {
  uint32_t now = millis();
  uint32_t elapsed = now - this->command_state_time_;

  const auto initial_state = this->command_state_;

  switch (this->command_state_) {
    case CommandState::IDLE:
      // Nothing to do
      break;

    case CommandState::HANDSHAKE_START: {
      uint8_t payload[36];
      size_t payload_len;
      
      // Use register or hello command based on flag
      if (this->use_register_command_) {
        payload_len = build_register_payload(this->protocol_version_, 
                                             this->registration_key_,
                                             payload);
        if (payload_len == 0) {
          ESP_LOGW(TAG, "Failed to build register payload");
          this->command_state_ = CommandState::IDLE;
          break;
        }
      } else {
        payload_len = build_hello_payload(this->protocol_version_, 
                                             this->registration_key_,
                                             payload);
        if (payload_len == 0) {
          ESP_LOGW(TAG, "Failed to build hello payload");
          this->command_state_ = CommandState::IDLE;
          break;
        }
      }
      
      // Send command using send_command (seq=0 for handshake)
      const uint8_t sequence_number = 0;
      if (!this->send_command(sequence_number, payload, payload_len)) {
        ESP_LOGW(TAG, "Failed to send %s command", this->use_register_command_ ? "register" : "hello");
        this->command_state_ = CommandState::IDLE;
        break;
      }

      this->waiting_for_ack_seq_ = sequence_number;
      this->waiting_for_ack_complete_ = true;
      
      // Wait for all chunks to be sent before proceeding to poll
      this->command_state_ = CommandState::HANDSHAKE_WAIT_CHUNKS;
      this->command_state_time_ = now;
      break;
    }

    case CommandState::HANDSHAKE_WAIT_CHUNKS:
      if (!this->waiting_for_ack_complete_ && !this->waiting_for_write_ack_ && this->send_chunk_index_ >= this->send_total_chunks_) {
        this->command_state_ = CommandState::HANDSHAKE_POLL;
        this->command_state_time_ = now;
      }
      if (elapsed >= HANDSHAKE_TIMEOUT_MS) {
        ESP_LOGE(TAG, "Handshake timeout");
        this->command_state_ = CommandState::IDLE;
        break;
      }
      break;

    case CommandState::HANDSHAKE_POLL:
      if (!this->waiting_for_ack_complete_) {
        if (this->last_ack_error_code_ != 0) {
          ESP_LOGE(TAG, "Error in %s: %d", this->use_register_command_ ? "registration" : "handshake", this->last_ack_error_code_);
          this->command_state_ = CommandState::IDLE;
          break;
        }

        this->send_status_request_();
        this->command_state_ = CommandState::IDLE;
        ESP_LOGI(TAG, "%s complete", this->use_register_command_ ? "Device registration" : "Registration handshake");
        
        // If registration was successful, turn off the switch
        if (this->use_register_command_ && this->register_switch_ != nullptr) {
          this->register_switch_->publish_state(false);
        }
      }
      if (elapsed >= HANDSHAKE_TIMEOUT_MS) {
        ESP_LOGE(TAG, "Handshake timeout");
        this->command_state_ = CommandState::IDLE;
        break;
      }
      break;

    case CommandState::HEAT_SET_TEMP:
      if (elapsed >= PRE_SETPOINT_DELAY_MS) {
        if (this->protocol_version_ != 1 || this->pending_mode_ != MODE_MY_TEMP) {
          // Can use custom temp mode for v0
          this->command_state_ = CommandState::HEAT_START;
          break;
        }

        this->set_my_temp(this->pending_temp_f_);
        this->command_state_ = CommandState::HEAT_START;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::HEAT_START:
      if (elapsed >= PRE_SETPOINT_DELAY_MS && !this->pending_my_temp_) {
        this->send_set_mode(this->pending_mode_, this->pending_temp_f_);
        this->command_state_ = CommandState::HEAT_POLL;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::HEAT_POLL:
      if (elapsed >= POST_SETPOINT_DELAY_MS) {
        // Proceed to control even if no status (timeout after POST_SETPOINT_DELAY_MS)
        uint8_t seq_base = (this->last_status_seq_ != 0) ? this->last_status_seq_ : this->last_rx_seq_;
        this->send_request_compact_status_(seq_base);
        this->command_state_ = CommandState::HEAT_POLL_REPEAT;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::HEAT_POLL_REPEAT:
      if (elapsed >= CONTROL_DELAY_MS) {
        uint8_t seq_ack = this->next_tx_seq_();
        this->send_request_compact_status_(seq_ack);
        this->command_state_ = CommandState::HEAT_COMPLETE;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::HEAT_COMPLETE:
      if (elapsed >= CONTROL_DELAY_MS) {
        this->command_state_ = CommandState::IDLE;
        ESP_LOGD(TAG, "Start heating sequence complete");
      }
      break;

    case CommandState::STOP:
      this->send_stop();
      this->command_state_ = CommandState::STOP_POLL;
      this->command_state_time_ = now;
      break;

    case CommandState::STOP_POLL:
      if (elapsed >= CONTROL_DELAY_MS) {
        uint8_t seq_ctrl = (this->last_status_seq_ != 0) ? this->last_status_seq_ : this->last_rx_seq_;
        this->send_request_compact_status_(seq_ctrl);
        this->command_state_ = CommandState::STOP_REPEAT;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::STOP_REPEAT:
      if (elapsed >= CONTROL_DELAY_MS) {
        this->send_stop();
        this->command_state_ = CommandState::IDLE;
        ESP_LOGD(TAG, "Stop heating sequence complete");
      }
      break;
  }
  
  if (this->command_state_ != initial_state) {
    ESP_LOGD(TAG, "Command state changed from %d to %d", initial_state, this->command_state_);
    this->process_command_state_machine_();
  }
}

}  // namespace cosori_kettle_ble
}  // namespace esphome

#endif  // USE_ESP32
