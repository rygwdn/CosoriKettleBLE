"""Tests for custom exceptions."""
import pytest

from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import (
    CosoriKettleError,
    ProtocolError,
    InvalidRegistrationKeyError,
    DeviceNotInPairingModeError,
    ConnectionError,
)


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_base_exception(self):
        """Test CosoriKettleError base exception."""
        exc = CosoriKettleError("Test error")
        assert str(exc) == "Test error"
        assert isinstance(exc, Exception)

    def test_protocol_error_without_status_code(self):
        """Test ProtocolError without status code."""
        exc = ProtocolError("Protocol error")
        assert str(exc) == "Protocol error"
        assert exc.status_code is None
        assert isinstance(exc, CosoriKettleError)

    def test_protocol_error_with_status_code(self):
        """Test ProtocolError with status code."""
        exc = ProtocolError("Protocol error", status_code=1)
        assert str(exc) == "Protocol error"
        assert exc.status_code == 1
        assert isinstance(exc, CosoriKettleError)

    def test_invalid_registration_key_error(self):
        """Test InvalidRegistrationKeyError."""
        exc = InvalidRegistrationKeyError("Invalid key", status_code=1)
        assert "Invalid key" in str(exc)
        assert exc.status_code == 1
        assert isinstance(exc, ProtocolError)
        assert isinstance(exc, CosoriKettleError)

    def test_device_not_in_pairing_mode_error(self):
        """Test DeviceNotInPairingModeError."""
        exc = DeviceNotInPairingModeError("Not in pairing mode", status_code=1)
        assert "Not in pairing mode" in str(exc)
        assert exc.status_code == 1
        assert isinstance(exc, ProtocolError)
        assert isinstance(exc, CosoriKettleError)

    def test_connection_error(self):
        """Test ConnectionError."""
        exc = ConnectionError("Connection failed")
        assert str(exc) == "Connection failed"
        assert isinstance(exc, CosoriKettleError)

    def test_exception_can_be_caught_as_base(self):
        """Test that specific exceptions can be caught as base exception."""
        try:
            raise InvalidRegistrationKeyError("Test", status_code=1)
        except CosoriKettleError as exc:
            assert isinstance(exc, InvalidRegistrationKeyError)

    def test_exception_can_be_caught_as_protocol_error(self):
        """Test that specific exceptions can be caught as ProtocolError."""
        try:
            raise DeviceNotInPairingModeError("Test", status_code=1)
        except ProtocolError as exc:
            assert isinstance(exc, DeviceNotInPairingModeError)
            assert exc.status_code == 1


class TestExceptionMessages:
    """Test exception message formatting."""

    def test_protocol_error_message_with_status_code(self):
        """Test that ProtocolError includes status code in repr."""
        exc = ProtocolError("Error occurred", status_code=0x42)
        assert exc.status_code == 0x42

    def test_invalid_registration_key_error_message(self):
        """Test InvalidRegistrationKeyError message."""
        exc = InvalidRegistrationKeyError(
            "Registration key was rejected. Please reconfigure.", status_code=1
        )
        assert "rejected" in str(exc).lower()
        assert exc.status_code == 1

    def test_device_not_in_pairing_mode_error_message(self):
        """Test DeviceNotInPairingModeError message."""
        exc = DeviceNotInPairingModeError(
            "Device is not in pairing mode. Please put the device into pairing mode.",
            status_code=1,
        )
        assert "pairing mode" in str(exc).lower()
        assert exc.status_code == 1
