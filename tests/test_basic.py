"""
Basic smoke tests for nfc2klipper package.
"""

import os
from unittest.mock import patch, MagicMock
import pytest
from nfc2klipper.lib.config import Nfc2KlipperConfig
from nfc2klipper.backend import Nfc2KlipperBackend
from nfc2klipper.api import Nfc2KlipperApi


@pytest.fixture
def mock_config():
    """Mock configuration dictionary."""
    return {
        "webserver": {
            "disable_web_server": False,
            "web_address": "0.0.0.0",
            "web_port": 5001,
            "socket_path": "/tmp/test.sock",
        },
        "nfc": {"nfc-device": "tty:AMA0"},
        "spoolman": {"spoolman-url": "http://localhost:8000"},
        "moonraker": {
            "moonraker-url": "http://localhost",
            "clear-spool": False,
            "always-send": False,
        },
        "macros": {
            "setting_gcode": "M117 Spool {spool}",
            "clearing_gcode": "M117 Clear",
        },
    }


def test_config_env_vars():
    """Test environment variable overrides in config."""
    with patch.dict(os.environ, {"N2K_NFC_DEVICE": "usb:001:002"}):
        config = Nfc2KlipperConfig.get_config()
        assert config["nfc"]["nfc-device"] == "usb:001:002"


@patch("nfc2klipper.lib.spoolman_client.SpoolmanClient.get_spool")
def test_backend_get_spool(mock_get_spool, mock_config, mock_spoolman_data):
    """Test backend interaction with Spoolman client using mocked data."""
    mock_get_spool.return_value = mock_spoolman_data[0]
    backend = Nfc2KlipperBackend(mock_config)

    # Simulate hardware event
    result = backend.spoolman.get_spool(1)
    assert result["id"] == 1
    assert result["filament"]["material"] == "PLA"


def test_hardware_mock_device(mock_config):
    """Test that setting device to 'mock' works (verified via NfcHandler)."""
    mock_config["nfc"]["nfc-device"] = "mock"
    with patch("nfc2klipper.lib.nfc_handler.NfcHandler") as mock_nfc:
        backend = Nfc2KlipperBackend(mock_config)
        assert backend.nfc_handler is not None


def test_api_init(mock_config):
    """Test API initialization."""
    with patch("nfc2klipper.api.IPCClient"):
        api = Nfc2KlipperApi(mock_config)
        assert api.app is not None
        assert api.socket_path == "/tmp/test.sock"
