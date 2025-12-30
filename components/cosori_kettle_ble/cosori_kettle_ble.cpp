#include "cosori_kettle_ble.h"
#include "envelope.h"
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

// Temperature limits (Fahrenheit)
static constexpr uint8_t MIN_TEMP_F = 104;
static constexpr uint8_t MAX_TEMP_F = 212;
static constexpr uint8_t MIN_VALID_READING_F = 40;
static constexpr uint8_t MAX_VALID_READING_F = 230;

// Operating modes
static constexpr uint8_t MODE_BOIL = 0x04;
static constexpr uint8_t MODE_HEAT = 0x06;

// Timing constants (milliseconds)
static constexpr uint32_t HANDSHAKE_DELAY_MS = 80;
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
  LOG_NUMBER("  ", "Target Setpoint", this->target_setpoint_number_);
  LOG_SWITCH("  ", "Heating Control", this->heating_switch_);
  LOG_SWITCH("  ", "BLE Connection", this->ble_connection_switch_);
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
      this->target_setpoint_initialized_ = false;
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
      this->send_registration_();

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
      }
      break;
    }

    case ESP_GATTC_NOTIFY_EVT: {
      if (param->notify.handle != this->rx_char_handle_)
        break;

      // Log full RX packet as hex dump (only when DEBUG level is enabled)
      if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
        std::string hex_str;
        hex_str.reserve(param->notify.value_len * 3);  // Pre-allocate: "xx:" per byte
        for (uint16_t i = 0; i < param->notify.value_len; i++) {
          char buf[4];
          snprintf(buf, sizeof(buf), "%02x%s", param->notify.value[i], (i < param->notify.value_len - 1) ? ":" : "");
          hex_str += buf;
        }
        ESP_LOGD(TAG, "RX: %s", hex_str.c_str());
      }

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
      break;
    }

    default:
      break;
  }
}

// // TODO: what calls this?
// void CosoriKettleBLE::update() {
//   this->track_online_status_();

//   if (!this->ble_enabled_) {
//     return;
//   }

//   if (this->node_state != esp32_ble_tracker::ClientState::ESTABLISHED) {
//     ESP_LOGD(TAG, "Not connected, skipping poll");
//     return;
//   }

//   if (!this->registration_sent_) {
//     ESP_LOGD(TAG, "Registration not complete, skipping poll");
//     return;
//   }

//   // Process command state machine
//   this->process_command_state_machine_();

//   // Send poll if not in the middle of a command sequence
//   // TODO: use if state is idle then state -> poll
//   if (this->command_state_ == CommandState::IDLE) {
//     this->send_poll_();
//   }
// }

// ============================================================================
// Protocol Implementation - Packet Sending
// ============================================================================

void CosoriKettleBLE::set_registration_key(const std::array<uint8_t, 16> &key) {
  this->registration_key_ = key;
  this->registration_key_set_ = true;
  ESP_LOGD(TAG, "Registration key set");
}

void CosoriKettleBLE::send_registration_() {
  // Verify registration key is set
  if (!this->registration_key_set_) {
    ESP_LOGE(TAG, "Registration key not set - cannot send hello command");
    return;
  }
  
  // Start handshake state machine instead of blocking
  ESP_LOGI(TAG, "Starting registration handshake");
  this->command_state_ = CommandState::HANDSHAKE_PACKET_1;
  this->command_state_time_ = millis();
}

bool CosoriKettleBLE::send_command(uint8_t seq, const uint8_t *payload, size_t payload_len, bool is_ack) {
  if (this->tx_char_handle_ == 0) {
    ESP_LOGW(TAG, "TX characteristic not ready");
    return false;
  }

  // Check if already sending something or waiting
  if (this->waiting_for_write_ack_ || (this->send_chunk_index_ < this->send_total_chunks_)) {
    ESP_LOGW(TAG, "Cannot send command: already sending (chunk %zu/%zu, waiting=%d)",
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
  if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    std::string hex_str;
    hex_str.reserve(send_buffer.size() * 3);  // Pre-allocate: "xx:" per byte
    for (size_t i = 0; i < send_buffer.size(); i++) {
      char buf[4];
      snprintf(buf, sizeof(buf), "%02x%s", send_buffer.data()[i], (i < send_buffer.size() - 1) ? ":" : "");
      hex_str += buf;
    }
    ESP_LOGD(TAG, "TX: %s", hex_str.c_str());
  }

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

void CosoriKettleBLE::send_poll_() {
  if (!this->is_connected()) {
    ESP_LOGV(TAG, "Cannot send poll: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  const uint8_t payload[] = {0x00, 0x40, 0x40, 0x00};
  ESP_LOGV(TAG, "Sending POLL (seq=%02x)", seq);
  if (!this->send_command(seq, payload, sizeof(payload))) {
    ESP_LOGW(TAG, "Failed to send POLL");
  }
}

// TODO: this is "set hold time" 60 minutes
void CosoriKettleBLE::send_hello5_() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send HELLO5: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  const uint8_t payload[] = {0x00, 0xF2, 0xA3, 0x00, 0x00, 0x01, 0x10, 0x0E};
  ESP_LOGD(TAG, "Sending HELLO5 (seq=%02x)", seq);
  if (!this->send_command(seq, payload, sizeof(payload))) {
    ESP_LOGW(TAG, "Failed to send HELLO5");
  }
}

// TODO: this is "start heating" with a hold time of 60 minutes
void CosoriKettleBLE::send_setpoint_(uint8_t mode, uint8_t temp_f) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send setpoint: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  const uint8_t payload[] = {0x00, 0xF0, 0xA3, 0x00, mode, temp_f, 0x01, 0x10, 0x0E};
  ESP_LOGD(TAG, "Sending SETPOINT %d°F (seq=%02x, mode=%02x)", temp_f, seq, mode);
  if (!this->send_command(seq, payload, sizeof(payload))) {
    ESP_LOGW(TAG, "Failed to send SETPOINT");
  }
}

// TODO: f4 -> "stop"
void CosoriKettleBLE::send_f4_() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send F4: not connected");
    return;
  }
  
  uint8_t seq = this->next_tx_seq_();
  const uint8_t payload[] = {0x00, 0xF4, 0xA3, 0x00};
  ESP_LOGD(TAG, "Sending F4 (seq=%02x)", seq);
  if (!this->send_command(seq, payload, sizeof(payload))) {
    ESP_LOGW(TAG, "Failed to send F4");
  }
}

// TODO: ctrl -> "request compact status"  - probably not necessary?
void CosoriKettleBLE::send_ctrl_(uint8_t seq_base) {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot send CTRL: not connected");
    return;
  }
  
  const uint8_t payload[] = {0x00, 0x41, 0x40, 0x00};
  ESP_LOGD(TAG, "Sending CTRL (seq=%02x)", seq_base);
  if (!this->send_command(seq_base, payload, sizeof(payload), true)) {
    ESP_LOGW(TAG, "Failed to send CTRL");
  }
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
  if (esp_log_level_get(TAG) >= ESP_LOG_DEBUG) {
    std::string hex_str;
    hex_str.reserve(len * 3);  // Pre-allocate: "xx:" per byte
    for (size_t i = 0; i < len; i++) {
      char buf[4];
      snprintf(buf, sizeof(buf), "%02x%s", data[i], (i < len - 1) ? ":" : "");
      hex_str += buf;
    }
    ESP_LOGD(TAG, "TX: %s", hex_str.c_str());
  }
  
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
    ESP_LOGW(TAG, "Error sending chunk %zu/%zu, status=%d", current_chunk, this->send_total_chunks_, status);
    this->send_chunk_index_ = 0;
    this->send_total_chunks_ = 0;
    this->waiting_for_write_ack_ = false;
  } else {
    ESP_LOGD(TAG, "Sent chunk %zu/%zu (%zu bytes)", current_chunk, this->send_total_chunks_, chunk_size);
  }
}


// ============================================================================
// Frame Processing
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

    // TODO: parse based on frame type AND command
    if (frame.frame_type == MESSAGE_HEADER_TYPE) {
      this->parse_compact_status_(frame.payload, frame.payload_len);
    } else if (frame.frame_type == ACK_HEADER_TYPE) {
      this->parse_extended_status_(frame.payload, frame.payload_len);
    }
  }
  
  // Compact buffer periodically to free up space at the beginning
  recv_buffer.compact();
}

void CosoriKettleBLE::parse_compact_status_(const uint8_t *payload, size_t len) {
  // Compact status: 01 41 40 00 <stage> <mode> <sp> <temp> <status> ...
  if (len < 9 || payload[0] != 0x01 || payload[1] != 0x41)
    return;

  uint8_t stage = payload[4];     // Heating stage
  uint8_t mode = payload[5];      // Mode
  uint8_t sp = payload[6];        // Setpoint temperature
  uint8_t temp = payload[7];      // Current temperature
  uint8_t status = payload[8];    // Heating status

  // Validate temperature range
  if (temp < MIN_VALID_READING_F || temp > MAX_VALID_READING_F)
    return;

  // Update state (temp, setpoint, heating only - no on-base detection from compact packets)
  this->current_temp_f_ = temp;
  this->kettle_setpoint_f_ = sp;
  this->heating_ = (status != 0);
  this->status_received_ = true;
  this->last_status_seq_ = this->last_rx_seq_;

  // Reset offline counter
  this->reset_online_status_();

  // Update entities
  this->update_entities_();
}

void CosoriKettleBLE::parse_extended_status_(const uint8_t *payload, size_t len) {
  // Extended status: 01 40 40 00 <stage> <mode> <sp> <temp> ... <on_base> ...
  // NOTE: Extended packets (A512 = A5 + 12, len=29) contain on-base detection at payload[14] (byte 20)
  // Compact packets (A522 = A5 + 22, len=12) do NOT contain on-base information
  if (len < 8 || payload[0] != 0x01 || payload[1] != 0x40)
    return;

  uint8_t stage = payload[4];
  uint8_t mode = payload[5];
  uint8_t sp = payload[6];
  uint8_t temp = payload[7];

  // Validate temperature range
  if (temp < MIN_VALID_READING_F || temp > MAX_VALID_READING_F)
    return;

  // Update state (temp, setpoint, heating)
  this->current_temp_f_ = temp;
  this->kettle_setpoint_f_ = sp;
  this->heating_ = (stage != 0);
  this->status_received_ = true;
  this->last_status_seq_ = this->last_rx_seq_;

  // On-base detection from payload[14] (byte 20 in full packet)
  if (len >= 15) {
    uint8_t on_base_byte = payload[14];
    bool prev_on_base = this->on_base_;
    this->on_base_ = (on_base_byte == 0x00);  // 0x00=on-base, 0x01=off-base

    if (prev_on_base != this->on_base_) {
      ESP_LOGI(TAG, "On-base: %s (payload[14]=0x%02x)",
               this->on_base_ ? "ON" : "OFF", on_base_byte);
    }
  }

  // Reset offline counter
  this->reset_online_status_();

  // Update entities
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

void CosoriKettleBLE::start_heating() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot start heating: not connected");
    return;
  }

  uint8_t temp_f = static_cast<uint8_t>(std::round(this->target_setpoint_f_));
  uint8_t mode = (temp_f == MAX_TEMP_F) ? MODE_BOIL : MODE_HEAT;

  ESP_LOGI(TAG, "Starting kettle at %.0f°F", this->target_setpoint_f_);

  // Store parameters and start state machine
  this->pending_temp_f_ = temp_f;
  this->pending_mode_ = mode;
  this->command_state_ = CommandState::START_HELLO5;
  this->command_state_time_ = millis();
}

void CosoriKettleBLE::stop_heating() {
  if (!this->is_connected()) {
    ESP_LOGW(TAG, "Cannot stop heating: not connected");
    return;
  }

  ESP_LOGI(TAG, "Stopping kettle");

  // Start stop sequence state machine
  this->command_state_ = CommandState::STOP_PRE_F4;
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

void CosoriKettleBLE::update_entities_() {
  if (this->temperature_sensor_ != nullptr) {
    this->temperature_sensor_->publish_state(this->current_temp_f_);
  }

  if (this->kettle_setpoint_sensor_ != nullptr) {
    this->kettle_setpoint_sensor_->publish_state(this->kettle_setpoint_f_);
  }

  // Initialize target setpoint number with kettle's setpoint on first status
  if (this->target_setpoint_number_ != nullptr && !this->target_setpoint_initialized_) {
    this->target_setpoint_f_ = this->kettle_setpoint_f_;
    this->target_setpoint_number_->publish_state(this->target_setpoint_f_);
    this->target_setpoint_initialized_ = true;
    ESP_LOGI(TAG, "Initialized target setpoint to %d°F from kettle", static_cast<int>(this->target_setpoint_f_));
  }

  if (this->on_base_binary_sensor_ != nullptr) {
    this->on_base_binary_sensor_->publish_state(this->on_base_);
  }

  if (this->heating_binary_sensor_ != nullptr) {
    this->heating_binary_sensor_->publish_state(this->heating_);
  }

  // Update heating switch state (without triggering action)
  if (this->heating_switch_ != nullptr) {
    this->heating_switch_->publish_state(this->heating_);
  }

  // Update climate state
  this->update_climate_state_();
}

void CosoriKettleBLE::update_climate_state_() {
  // Update current temperature (convert F to C for ESPHome climate)
  this->current_temperature = (this->current_temp_f_ - 32.0f) * 5.0f / 9.0f;

  // Initialize target temperature from kettle on first status
  if (!this->target_setpoint_initialized_) {
    this->target_setpoint_f_ = this->kettle_setpoint_f_;
    this->target_temperature = (this->kettle_setpoint_f_ - 32.0f) * 5.0f / 9.0f;
    this->target_setpoint_initialized_ = true;
    ESP_LOGI(TAG, "Climate: Initialized target temperature to %.0f°F (%.1f°C) from kettle",
             this->target_setpoint_f_, this->target_temperature);
  }

  // Update mode based on heating state and base status
  if (!this->on_base_) {
    // Off base - set to OFF mode
    this->mode = climate::CLIMATE_MODE_OFF;
    this->action = climate::CLIMATE_ACTION_IDLE;
  } else if (this->heating_) {
    // On base and heating
    this->mode = climate::CLIMATE_MODE_HEAT;
    this->action = climate::CLIMATE_ACTION_HEATING;
  } else {
    // On base but not heating - set to OFF mode
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

  switch (this->command_state_) {
    case CommandState::IDLE:
      // Nothing to do
      break;

    case CommandState::HANDSHAKE_PACKET_1: {
      uint8_t payload[36];
      payload[0] = this->protocol_version_; // Protocol version (0 or 1)
      payload[1] = 0x81;
      payload[2] = 0xD1;
      payload[3] = 0x00;
      
      // Convert 16-byte binary key to 32-byte ASCII hex
      static const char hex_chars[] = "0123456789abcdef";
      for (size_t i = 0; i < 16; i++) {
        uint8_t byte = this->registration_key_[i];
        payload[4 + i * 2] = hex_chars[(byte >> 4) & 0x0F];
        payload[4 + i * 2 + 1] = hex_chars[byte & 0x0F];
      }
      
      // Send hello command using send_command (seq=0 for hello)
      if (!this->send_command(0, payload, sizeof(payload))) {
        ESP_LOGW(TAG, "Failed to send hello command");
        this->command_state_ = CommandState::IDLE;
        break;
      }
      
      // Wait for all chunks to be sent before proceeding to poll
      this->command_state_ = CommandState::HANDSHAKE_WAIT_CHUNKS;
      this->command_state_time_ = now;
      break;
    }

    case CommandState::HANDSHAKE_WAIT_CHUNKS:
      // Wait for all chunks to be sent (waiting_for_write_ack_ will be false when done)
      if (!this->waiting_for_write_ack_ && this->send_chunk_index_ >= this->send_total_chunks_) {
        // All chunks sent, proceed to poll
        // TODO: add wait for ack before poll
        this->command_state_ = CommandState::HANDSHAKE_POLL;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::HANDSHAKE_POLL:
      if (elapsed >= HANDSHAKE_DELAY_MS) {
        this->send_poll_();
        this->command_state_ = CommandState::IDLE;
        ESP_LOGI(TAG, "Registration handshake complete");
      }
      break;

    case CommandState::START_HELLO5:
      this->send_hello5_();
      this->command_state_ = CommandState::START_SETPOINT;
      this->command_state_time_ = now;
      break;

    case CommandState::START_SETPOINT:
      if (elapsed >= PRE_SETPOINT_DELAY_MS) {
        this->send_setpoint_(this->pending_mode_, this->pending_temp_f_);
        this->command_state_ = CommandState::START_WAIT_STATUS;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::START_WAIT_STATUS:
      if (elapsed >= POST_SETPOINT_DELAY_MS) {
        // Proceed to control even if no status (timeout after POST_SETPOINT_DELAY_MS)
        uint8_t seq_base = (this->last_status_seq_ != 0) ? this->last_status_seq_ : this->last_rx_seq_;
        this->send_ctrl_(seq_base);
        this->command_state_ = CommandState::START_CTRL;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::START_CTRL:
      if (elapsed >= CONTROL_DELAY_MS) {
        uint8_t seq_ack = this->next_tx_seq_();
        this->send_ctrl_(seq_ack);
        this->command_state_ = CommandState::START_CTRL_REINFORCE;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::START_CTRL_REINFORCE:
      if (elapsed >= CONTROL_DELAY_MS) {
        this->command_state_ = CommandState::IDLE;
        ESP_LOGD(TAG, "Start heating sequence complete");
      }
      break;

    case CommandState::STOP_PRE_F4:
      this->send_f4_();
      this->command_state_ = CommandState::STOP_CTRL;
      this->command_state_time_ = now;
      break;

    case CommandState::STOP_CTRL:
      if (elapsed >= CONTROL_DELAY_MS) {
        uint8_t seq_ctrl = (this->last_status_seq_ != 0) ? this->last_status_seq_ : this->last_rx_seq_;
        this->send_ctrl_(seq_ctrl);
        this->command_state_ = CommandState::STOP_POST_F4;
        this->command_state_time_ = now;
      }
      break;

    case CommandState::STOP_POST_F4:
      if (elapsed >= CONTROL_DELAY_MS) {
        this->send_f4_();
        this->command_state_ = CommandState::IDLE;
        ESP_LOGD(TAG, "Stop heating sequence complete");
      }
      break;
  }
}

}  // namespace cosori_kettle_ble
}  // namespace esphome

#endif  // USE_ESP32
