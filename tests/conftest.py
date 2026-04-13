import json
import pytest
from pathlib import Path

@pytest.fixture
def mock_spoolman_data():
    """Load mock spool data from JSON."""
    mock_path = Path(__file__).parent / "mocks" / "spools.json"
    with open(mock_path, "r") as f:
        return json.load(f)

@pytest.fixture
def mock_filament_data():
    """Load mock filament data from JSON."""
    mock_path = Path(__file__).parent / "mocks" / "filaments.json"
    with open(mock_path, "r") as f:
        return json.load(f)

@pytest.fixture
def mock_moonraker_data():
    """Load mock moonraker data from JSON."""
    mock_path = Path(__file__).parent / "mocks" / "moonraker.json"
    with open(mock_path, "r") as f:
        return json.load(f)
