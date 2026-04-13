#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Web API service for nfc2klipper."""

import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple, Union

from flask import Flask, render_template

from .lib.config import Nfc2KlipperConfig
from .lib.ipc import IPCClient

logger = logging.getLogger(__name__)

class Nfc2KlipperApi:
    """Class to handle the web API for nfc2klipper."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.socket_path = os.path.expanduser(
            config.get("webserver", {}).get("socket_path", Nfc2KlipperConfig.DEFAULT_SOCKET_PATH)
        )
        self.ipc_client = IPCClient(self.socket_path)
        
        # Initialize Flask app
        # templates_dir is now in the same directory as this file
        template_folder = os.path.join(os.path.dirname(__file__), "templates")
        self.app = Flask(__name__, template_folder=template_folder)
        self._register_routes()

    def _register_routes(self):
        self.app.add_url_rule("/w/<int:spool>/<int:filament>", "write_tag", self.write_tag)
        self.app.add_url_rule("/set_nfc_id/<int:spool>", "set_nfc_id", self.set_nfc_id)
        self.app.add_url_rule("/", "index", self.index)

    def write_tag(self, spool: int, filament: int) -> Union[str, Tuple[str, int]]:
        """Web-api to write spool & filament data to NFC tag."""
        response: Dict[str, Any] = self.ipc_client.send_request(
            {"command": "write_tag", "spool": spool, "filament": filament}
        )
        if response.get("status") == "ok":
            return "OK"
        return ("Failed to write to tag", 502)

    def set_nfc_id(self, spool: int) -> Union[str, Tuple[str, int]]:
        """Web-api to write current nfc_id to Spoolman."""
        response: Dict[str, Any] = self.ipc_client.send_request(
            {"command": "set_nfc_id", "spool": spool}
        )
        if response.get("status") == "ok":
            return "OK"
        return ("Failed to send nfc_id to Spoolman", 502)

    def index(self) -> Union[str, Tuple[str, int]]:
        """Returns the main index page."""
        spools_response = self.ipc_client.send_request({"command": "get_spools"})
        state_response = self.ipc_client.send_request({"command": "get_state"})

        if spools_response.get("status") != "ok":
            error_msg = spools_response.get("message", "Unknown error")
            logger.error("Spoolman error: %s", error_msg)
            return (f"Got error fetching spool data from Spoolman via backend: {error_msg}", 502)
        
        if state_response.get("status") != "ok":
            error_msg = state_response.get("message", "Unknown error")
            logger.error("Backend state error: %s", error_msg)
            return (f"Got error fetching spool state from backend: {error_msg}", 502)

        spools = spools_response.get("spools", [])
        nfc_id = state_response.get("nfc_id")
        spool_id = state_response.get("spool_id")

        return render_template(
            "index.html", spools=spools, nfc_id=nfc_id, spool_id=spool_id
        )

    def run(self):
        """Run the Flask development server."""
        addr = self.config["webserver"]["web_address"]
        port = self.config["webserver"]["web_port"]
        logger.info("Starting web server on %s:%s", addr, port)
        self.app.run(addr, port=port)

def main():
    """Main entry point for standalone API."""
    import argparse
    parser = argparse.ArgumentParser(description="Web API for nfc2klipper.")
    parser.add_argument("-c", "--config-dir", help="Configuration directory")
    args = parser.parse_args()

    Nfc2KlipperConfig.configure_logging()
    config = Nfc2KlipperConfig.get_config(args.config_dir)
    
    if not config:
        logger.error("Configuration not found.")
        sys.exit(1)

    api = Nfc2KlipperApi(config)
    api.run()

if __name__ == "__main__":
    main()
