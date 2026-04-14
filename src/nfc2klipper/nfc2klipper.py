#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified entry point for the nfc2klipper agent and web API."""

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from typing import Any, Dict, Optional, Union
from pathlib import Path

from aiohttp import web
import jinja2

from .lib.config import Nfc2KlipperConfig
from .lib.nfc_handler import NfcHandler
from .lib.nfc_parsers import NdefTextParser, TagIdentifierParser
from .lib.opentag3d_parser import OpenTag3DParser

from .api import KlipperClient
from .engine import NfcSyncEngine
from .spoolman_common.api import SpoolmanClient

PROGNAME = "nfc2klipper"
logger = logging.getLogger(PROGNAME)

# Global objects
ARGS = None

class Nfc2KlipperApp:
    """Consolidated application runner for NFC hardware and Web API."""

    def __init__(self, config: Optional[Union[str, Dict[str, Any]]] = None):
        if isinstance(config, dict):
            self.config = config
        else:
            config_dir = config or (ARGS.config_dir if ARGS else None) or Nfc2KlipperConfig.CFG_DIR
            self.config = Nfc2KlipperConfig.get_config(config_dir)
        
        if not self.config:
            logger.error(f"Configuration file not found in {config_dir}")
            sys.exit(1)

        # 1. Initialize Clients
        self.spoolman = SpoolmanClient(self.config["spoolman"]["spoolman-url"])
        
        self.klipper = KlipperClient(
            url=self.config["moonraker"]["moonraker-url"],
            setting_template=Nfc2KlipperConfig.get_setting_gcode(self.config),
            clearing_template=Nfc2KlipperConfig.get_clearing_gcode(self.config)
        )

        # 2. Initialize Parsers
        self.parsers = [
            NdefTextParser(),
            TagIdentifierParser(self.spoolman),
            OpenTag3DParser(
                self.spoolman,
                Nfc2KlipperConfig.get_opentag3d_filament_name_template(self.config),
                Nfc2KlipperConfig.get_opentag3d_filament_field_mapping(self.config),
                Nfc2KlipperConfig.get_opentag3d_spool_field_mapping(self.config),
            )
        ]

        # 3. Initialize Engine
        self.engine = NfcSyncEngine(
            spoolman=self.spoolman,
            klipper=self.klipper,
            parsers=self.parsers,
            always_send=self.config["moonraker"].get("always-send", False),
            clear_on_missing=self.config["moonraker"].get("clear-spool", False)
        )

        # 4. Initialize Hardware Handler
        nfc_device = self.config["nfc"]["nfc-device"]
        self.nfc_handler = NfcHandler(nfc_device)
        self.nfc_handler.set_tag_present_callback(self.engine.on_tag_present)
        self.nfc_handler.set_no_tag_present_callback(self.engine.on_tag_removed)

        # 5. Web Application Setup
        self.web_app = web.Application()
        self.setup_web_routes()
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")),
            autoescape=jinja2.select_autoescape(['html', 'xml'])
        )

    def setup_web_routes(self):
        """Register the web API routes."""
        self.web_app.add_routes([
            web.get('/', self.handle_index),
            web.get('/w/{spool}/{filament}', self.handle_write),
            web.get('/set_nfc_id/{spool}', self.handle_set_nfc_id)
        ])

    # --- Route Handlers ---

    async def handle_index(self, request):
        """Render the main management dashboard."""
        try:
            # Spoolman calls are blocking, run in executor
            spools = await asyncio.get_event_loop().run_in_executor(
                None, self.spoolman.get_active_spools
            )
            state = self.engine.get_current_state()
            
            template = self.jinja_env.get_template("index.html")
            content = template.render(
                spools=spools,
                nfc_id=state["nfc_id"],
                spool_id=state["spool_id"]
            )
            return web.Response(text=content, content_type='text/html')
        except Exception as e:
            logger.error(f"Index handler failed: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def handle_write(self, request):
        """Handle the tag writing command."""
        spool_id = int(request.match_info['spool'])
        filament_id = int(request.match_info['filament'])
        
        # Hardware writing is blocking, run in executor
        success = await asyncio.get_event_loop().run_in_executor(
            None, self.engine.write_tag, spool_id, filament_id, self.nfc_handler
        )
        
        if success:
            return web.Response(text="OK")
        return web.Response(text="Failed to write tag", status=502)

    async def handle_set_nfc_id(self, request):
        """Handle linking the last read tag to a spool."""
        spool_id = int(request.match_info['spool'])
        
        success = await asyncio.get_event_loop().run_in_executor(
            None, self.engine.set_nfc_id_in_spoolman, spool_id
        )
        
        if success:
            return web.Response(text="OK")
        return web.Response(text="Failed to update Spoolman", status=502)

    # --- Lifecycle ---

    async def run(self):
        """Start the hardware thread and the web server."""
        self.stop_event = asyncio.Event()

        # 1. Start hardware polling in a separate thread
        hw_thread = threading.Thread(target=self.nfc_handler.run, daemon=True)
        hw_thread.start()
        logger.info("NFC Hardware Polling started")

        # 2. Start Web Server
        web_config = self.config.get("webserver", {})
        runner = None
        if not web_config.get("disable_web_server", False):
            host = web_config.get("web_address", "0.0.0.0")
            port = web_config.get("web_port", 5001)
            
            runner = web.AppRunner(self.web_app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            logger.info(f"Web API started at http://{host}:{port}")

        # Keep alive until stopped
        try:
            await self.stop_event.wait()
        finally:
            if runner:
                logger.info("Shutting down web server...")
                await runner.cleanup()
            logger.info("Cleanup complete.")

    def stop(self):
        """Trigger application shutdown."""
        if hasattr(self, 'stop_event'):
            self.stop_event.set()

def get_parser() -> argparse.ArgumentParser:
    """Initialize the argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROGNAME,
        description="Unified NFC2Klipper agent for hardware and Web API.",
    )
    parser.add_argument(
        "-c", "--config-dir",
        metavar="DIR",
        help="The folder where your configuration files are stored.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed progress information.",
    )
    return parser

def main():
    """CLI Entry point."""
    global ARGS
    Nfc2KlipperConfig.configure_logging()
    
    parser = get_parser()
    ARGS = parser.parse_args()

    # Set log level based on verbose flag
    if ARGS.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    app = Nfc2KlipperApp(ARGS.config_dir)
    
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
