"""Exceptions for Cosori Kettle BLE."""
from __future__ import annotations


class CosoriKettleError(Exception):
    """Base exception for Cosori Kettle errors."""


class ProtocolError(CosoriKettleError):
    """Protocol-level error with status code."""

    def __init__(self, message: str, status_code: int | None = None):
        """Initialize protocol error.

        Args:
            message: Error message
            status_code: Optional status code from device ACK response
        """
        self.status_code = status_code
        super().__init__(message)


class InvalidRegistrationKeyError(ProtocolError):
    """Registration key was rejected (ACK status=1 during hello)."""


class DeviceNotInPairingModeError(ProtocolError):
    """Device not in pairing mode (ACK status=1 during register)."""


class ConnectionError(CosoriKettleError):
    """Failed to connect to device."""
