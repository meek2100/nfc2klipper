#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend service for NFC handling and communication with Moonraker/Spoolman."""

import logging
import os
import signal
import sys
import threading
from typing import Any, Dict, List, Optional, Union

from .lib.config import Nfc2KlipperConfig
from .lib.ipc import IPCServer
from .lib.moonraker_web_client import MoonrakerWebClient
from .lib.nfc_handler import NfcHandler
from .lib.nfc_parsers import NdefTextParser, TagIdentifierParser
from .lib.opentag3d_parser import OpenTag3DParser
from .lib.spoolman_client import SpoolmanClient

logger = logging.getLogger(__name__)

class Nfc2KlipperBackend:
    """Class to handle NFC reading and communication with Moonraker/Spoolman."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.socket_path = os.path.expanduser(
            config.get("webserver", {}).get("socket_path", Nfc2KlipperConfig.DEFAULT_SOCKET_PATH)
        )
        
        self.setting_gcode_template = Nfc2KlipperConfig.get_setting_gcode(config)
        self.clearing_gcode_template = Nfc2KlipperConfig.get_clearing_gcode(config)
        
        self.last_nfc_id: Optional[str] = None
        self.last_spool_id: Optional[str] = None
        
        # Setup clients
        self.use_mock = os.environ.get("NFC2KLIPPER_USE_MOCKS", "").lower() in ("1", "true", "yes")
        
        if self.use_mock:
            from .lib.mock_objects import MockNfcHandler, MockSpoolmanClient, MockMoonrakerWebClient
            self.spoolman = MockSpoolmanClient(config["spoolman"]["spoolman-url"])
            self.moonraker = MockMoonrakerWebClient(
                config["moonraker"]["moonraker-url"],
                self.setting_gcode_template,
                self.clearing_gcode_template
            )
            self.nfc_handler = MockNfcHandler(config["nfc"]["nfc-device"])
        else:
            self.spoolman = SpoolmanClient(config["spoolman"]["spoolman-url"])
            self.moonraker = MoonrakerWebClient(
                config["moonraker"]["moonraker-url"],
                self.setting_gcode_template,
                self.clearing_gcode_template
            )
            self.nfc_handler = NfcHandler(config["nfc"]["nfc-device"])

        self.ipc_server = IPCServer(self.socket_path)
        self._register_ipc_handlers()

        # Parsers
        self.opentag3d_filament_template = Nfc2KlipperConfig.get_opentag3d_filament_name_template(config)
        self.opentag3d_filament_mapping = Nfc2KlipperConfig.get_opentag3d_filament_field_mapping(config)
        self.opentag3d_spool_mapping = Nfc2KlipperConfig.get_opentag3d_spool_field_mapping(config)

        self.parsers = [
            NdefTextParser(),
            TagIdentifierParser(self.spoolman),
            OpenTag3DParser(
                self.spoolman,
                self.opentag3d_filament_template,
                self.opentag3d_filament_mapping,
                self.opentag3d_spool_mapping,
            ),
        ]

        self._old_spool: Optional[int] = None
        self._old_filament: Optional[int] = None
        self._stop_event = threading.Event()

    def _register_ipc_handlers(self):
        self.ipc_server.register_handler("write_tag")(self.handle_write_tag)
        self.ipc_server.register_handler("set_nfc_id")(self.handle_set_nfc_id)
        self.ipc_server.register_handler("get_spools")(self.handle_get_spools)
        self.ipc_server.register_handler("get_state")(self.handle_get_state)

    def should_always_send(self) -> bool:
        return self.config["moonraker"].get("always-send", False)

    def should_clear_spool(self) -> bool:
        return self.config["moonraker"].get("clear-spool", False)

    def set_spool_and_filament(self, spool: int, filament: int) -> None:
        if not self.should_always_send() and (self._old_spool == spool and self._old_filament == filament):
            logger.info("Read same spool & filament")
            return

        logger.info("Sending spool #%s, filament #%s to klipper", spool, filament)
        self._old_spool = None
        self._old_filament = None

        try:
            if spool and filament:
                self.moonraker.set_spool_and_filament(spool, filament)
            else:
                self.moonraker.clear_spool_and_filament()
        except Exception as ex:
            logger.error("Failed to send to moonraker: %s", ex)
            return

        self._old_spool = spool
        self._old_filament = filament

    def on_nfc_tag_present(self, ndef_data: Any, identifier: str) -> None:
        if identifier:
            self.last_nfc_id = identifier

        spool: Optional[str] = None
        filament: Optional[str] = None

        for tag_parser in self.parsers:
            spool_and_filament = tag_parser.parse(ndef_data, identifier)
            if spool_and_filament:
                spool, filament = spool_and_filament
                if spool and filament:
                    break

        if spool:
            self.last_spool_id = spool

        if spool and filament:
            self.set_spool_and_filament(int(spool), int(filament))
        else:
            logger.info("Did not find spool and filament data in tag (%s)", identifier)

    def on_nfc_no_tag_present(self) -> None:
        if self.should_clear_spool():
            self.set_spool_and_filament(0, 0)

    def handle_write_tag(self, spool: int, filament: int) -> Dict[str, Any]:
        logger.info("  write spool=%s, filament=%s", spool, filament)
        if self.nfc_handler.write_to_tag(spool, filament):
            return {"status": "ok"}
        return {"status": "error", "message": "Failed to write to tag"}

    def handle_set_nfc_id(self, spool: int) -> Dict[str, Any]:
        logger.info("Set nfc_id=%s to spool=%s in Spoolman", self.last_nfc_id, spool)
        if self.last_nfc_id is None:
            return {"status": "error", "message": "No nfc_id to write"}
        if self.spoolman.set_nfc_id_for_spool(spool, self.last_nfc_id):
            return {"status": "ok"}
        return {"status": "error", "message": "Failed to send nfc_id to Spoolman"}

    def handle_get_spools(self) -> Dict[str, Any]:
        spools = self.spoolman.get_spools()
        return {"status": "ok", "spools": spools}

    def handle_get_state(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "nfc_id": self.last_nfc_id,
            "spool_id": self.last_spool_id,
        }

    def start(self):
        """Start the backend services."""
        if self.should_clear_spool():
            self.set_spool_and_filament(0, 0)

        self.nfc_handler.set_no_tag_present_callback(self.on_nfc_no_tag_present)
        self.nfc_handler.set_tag_present_callback(self.on_nfc_tag_present)

        logger.info("Starting IPC socket server")
        self.socket_thread = threading.Thread(target=self.ipc_server.start)
        self.socket_thread.daemon = True
        self.socket_thread.start()

        logger.info("Starting NFC handler")
        self.nfc_handler.run()

    def stop(self):
        """Stop the backend services."""
        logger.info("Stopping backend...")
        self.nfc_handler.stop()
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

def main():
    """Main entry point for standalone backend."""
    import argparse
    parser = argparse.ArgumentParser(description="Backend service for NFC handling.")
    parser.add_argument("-c", "--config-dir", help="Configuration directory")
    args = parser.parse_args()

    Nfc2KlipperConfig.configure_logging()
    config = Nfc2KlipperConfig.get_config(args.config_dir)
    
    if not config:
        logger.error("Configuration not found.")
        sys.exit(1)

    backend = Nfc2KlipperBackend(config)
    
    def signal_handler(signum, _frame):
        backend.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        backend.start()
    except (KeyboardInterrupt, SystemExit):
        backend.stop()

if __name__ == "__main__":
    main()
