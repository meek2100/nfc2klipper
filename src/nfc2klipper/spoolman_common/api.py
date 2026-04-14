# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Spoolman API client for fetching, monitoring, and managing spool data."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests
from websockets.client import connect, WebSocketClientProtocol

from .constants import REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

class SpoolmanClient:
    """Stateful client for the Spoolman REST and WebSocket APIs."""

    def __init__(self, base_url: str, timeout: int = REQUEST_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def _request_json(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Any:
        """Centralized helper for JSON requests with retries and decoding."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        last_exception = None

        for attempt in range(max_retries):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    timeout=self.timeout,
                    json=data
                )
                response.raise_for_status()
                
                if response.status_code == 204: # No content
                    return True
                
                try:
                    res_data = response.json()
                    self._decode_extra_fields(res_data)
                    return res_data
                except (json.JSONDecodeError, ValueError) as ex:
                    logger.error(f"Failed to parse JSON from {url}: {ex}")
                    raise

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ex:
                last_exception = ex
                if attempt < max_retries - 1:
                    wait_time = 2**attempt
                    logger.warning(f"Connection error to {url}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to connect to Spoolman at {url}: {ex}")
                    raise
            except requests.exceptions.HTTPError as ex:
                logger.error(f"HTTP error {ex.response.status_code} from {url}: {ex.response.text}")
                raise

        if last_exception:
            raise last_exception
        return None

    def _get_json(self, endpoint: str, max_retries: int = 3) -> Any:
        return self._request_json("GET", endpoint, max_retries=max_retries)

    def _post_json(self, endpoint: str, data: Dict[str, Any]) -> Any:
        return self._request_json("POST", endpoint, data=data)

    def _patch_json(self, endpoint: str, data: Dict[str, Any]) -> Any:
        return self._request_json("PATCH", endpoint, data=data)

    def _decode_extra_fields(self, data: Any) -> None:
        """Recursively decode JSON strings within 'extra' fields into Python objects."""
        if isinstance(data, list):
            for item in data:
                self._decode_extra_fields(item)
        elif isinstance(data, dict):
            extra = data.get("extra")
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if isinstance(value, str):
                        try:
                            # Try to decode, stay as string if it's just a raw value
                            extra[key] = json.loads(value)
                        except (json.JSONDecodeError, TypeError):
                            pass
            
            for nested in ["filament", "vendor", "spool"]:
                if nested in data:
                    self._decode_extra_fields(data[nested])

    # --- Read Operations ---

    def get_active_spools(self) -> List[Dict[str, Any]]:
        """Fetch all non-archived spools."""
        return self._get_json("spool?archived=false")

    def get_spools(self, **kwargs) -> List[Dict[str, Any]]:
        """Fetch spools with optional filters."""
        query = "&".join([f"{k}={v}" for k, v in kwargs.items()])
        endpoint = f"spool?{query}" if query else "spool"
        return self._get_json(endpoint)

    def get_spool(self, spool_id: int) -> Dict[str, Any]:
        """Fetch details for a specific spool."""
        return self._get_json(f"spool/{spool_id}")

    def get_filament(self, filament_id: int) -> Dict[str, Any]:
        """Fetch details for a specific filament."""
        return self._get_json(f"filament/{filament_id}")

    def get_filaments(self, **kwargs) -> List[Dict[str, Any]]:
        """Fetch filaments with optional filters."""
        query = "&".join([f"{k}={v}" for k, v in kwargs.items()])
        endpoint = f"filament?{query}" if query else "filament"
        return self._get_json(endpoint)

    def get_vendors(self) -> List[Dict[str, Any]]:
        """Fetch all vendors."""
        return self._get_json("vendor")

    # --- Write & Creation Operations ---

    def create_vendor(self, name: str) -> Dict[str, Any]:
        """Create a new vendor."""
        return self._post_json("vendor", {"name": name})

    def create_filament(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new filament."""
        return self._post_json("filament", data)

    def create_spool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new spool."""
        return self._post_json("spool", data)

    def patch_spool(self, spool_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a subset of spool fields."""
        return self._patch_json(f"spool/{spool_id}", data)

    # --- NFC Specific Logic ---

    def get_spool_by_nfc_id(self, nfc_id: str) -> Optional[Dict[str, Any]]:
        """Search for a spool that has the given NFC ID in its extra fields."""
        search_id = nfc_id.lower()
        # We fetch active spools first as they are the most likely targets
        spools = self.get_active_spools()
        for spool in spools:
            extra = spool.get("extra")
            if isinstance(extra, dict):
                stored_id = str(extra.get("nfc_id", "")).lower()
                # Handle potential JSON escaped strings (legacy nfc2klipper behavior)
                if stored_id.startswith('"') and stored_id.endswith('"'):
                    stored_id = stored_id[1:-1]
                if stored_id == search_id:
                    return spool
        return None

    def set_nfc_id_to_spool(self, spool_id: int, nfc_id: str) -> bool:
        """Assign an NFC ID to a spool, clearing it from any other spool first."""
        existing = self.get_spool_by_nfc_id(nfc_id)
        if existing:
            if existing["id"] == spool_id:
                return True # Already assigned
            # Clear from other spool
            self._clear_nfc_id(existing["id"])
        
        # Assign to new spool
        # Note: We store as a raw string, if the user wants JSON encoding we handle it here
        # nfc2klipper legacy stored it as a quoted JSON string. We'll stick to a clean string.
        extra = {"nfc_id": nfc_id.lower()}
        return self.patch_spool(spool_id, {"extra": extra})

    def _clear_nfc_id(self, spool_id: int):
        """Internal helper to clear NFC ID from a spool."""
        return self.patch_spool(spool_id, {"extra": {"nfc_id": ""}})

    # --- Search Helpers (NFC/Suite) ---

    def find_vendor_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find vendor by name (case-insensitive)."""
        vendors = self.get_vendors()
        for v in vendors:
            if v.get("name", "").lower() == name.lower():
                return v
        return None

    def find_filament(self, vendor_id: int, name: str, material: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Search for a filament matching vendor, name, and optionally material."""
        filaments = self.get_filaments(vendor_id=vendor_id)
        for f in filaments:
            name_match = f.get("name", "").lower() == name.lower()
            mat_match = True
            if material:
                mat_match = f.get("material", "").lower() == material.lower()
            
            if name_match and mat_match:
                return f
        return None

    # --- WebSocket ---

    async def connect_websocket(self) -> WebSocketClientProtocol:
        """Create a websocket connection for real-time monitoring."""
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/v1/event"
        return await connect(ws_url)
