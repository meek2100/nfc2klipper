# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Klipper HTTP client for Moonraker communication."""

import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

class KlipperClient:
    """HTTP client for interacting with Moonraker/Klipper."""

    def __init__(
        self,
        url: str,
        setting_template: List[str],
        clearing_template: List[str]
    ):
        self.url = url.rstrip("/")
        self.setting_template = setting_template
        self.clearing_template = clearing_template

    def set_spool_and_filament(self, spool_id: int, filament_id: int):
        """Invoke Klipper macros for active spool and filament."""
        formatted_commands = [
            t.format(spool=spool_id, filament=filament_id)
            for t in self.setting_template
        ]
        self._send_commands(formatted_commands)

    def clear_spool_and_filament(self):
        """Invoke Klipper macros to clear active settings."""
        self._send_commands(self.clearing_template)

    def _send_commands(self, commands: List[str]):
        """Send a list of G-Code commands to Moonraker via POST."""
        if not commands:
            return

        url = f"{self.url}/api/printer/command"
        payload = {"commands": commands}

        try:
            logger.info(f"Sending {len(commands)} commands to Klipper: {commands}")
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send commands to Klipper at {url}: {e}")
            raise
