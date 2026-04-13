#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Orchestrator to run NFC2Klipper backend and API (Threading or Processes)."""

import argparse
import logging
import os
import signal
import sys
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from .lib.config import Nfc2KlipperConfig
from .backend import Nfc2KlipperBackend
from .api import Nfc2KlipperApi

logger = logging.getLogger(__name__)

class Nfc2KlipperOrchestrator:
    """Class to manage the lifecycle of NFC2Klipper components."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.backend: Optional[Nfc2KlipperBackend] = None
        self.api: Optional[Nfc2KlipperApi] = None
        self.backend_process: Optional[subprocess.Popen] = None
        self.api_process: Optional[subprocess.Popen] = None
        self.is_running = False

    def start_threaded(self):
        """Start both backend and API as threads in the same process."""
        self.is_running = True
        logger.info("Starting NFC2Klipper in threaded mode")
        
        self.backend = Nfc2KlipperBackend(self.config)
        self.api = Nfc2KlipperApi(self.config)

        # Start Backend thread
        self.backend_thread = threading.Thread(target=self.backend.start, name="BackendThread")
        self.backend_thread.daemon = True
        self.backend_thread.start()

        if not self.config["webserver"].get("disable_web_server"):
            # Start API thread
            self.api_thread = threading.Thread(target=self.api.run, name="ApiThread")
            self.api_thread.daemon = True
            self.api_thread.start()

    def start_processes(self, config_dir: Optional[str] = None):
        """Start backend and API as separate subprocesses (Legacy behavior)."""
        self.is_running = True
        logger.info("Starting NFC2Klipper in process mode")
        
        # We use sys.executable -m to ensure we run the modules correctly if installed
        # But for absolute path backward compatibility, we can find the script paths
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        backend_script = os.path.join(pkg_dir, "backend.py")
        api_script = os.path.join(pkg_dir, "api.py")

        backend_cmd = [sys.executable, backend_script]
        if config_dir:
            backend_cmd.extend(["-c", config_dir])
        
        self.backend_process = subprocess.Popen(backend_cmd)
        
        if not self.config["webserver"].get("disable_web_server"):
            time.sleep(2)
            api_cmd = [sys.executable, api_script]
            if config_dir:
                 api_cmd.extend(["-c", config_dir])
            self.api_process = subprocess.Popen(api_cmd)

    def stop(self):
        """Stop all running components."""
        self.is_running = False
        if self.api_process:
            logger.info("Terminating API process")
            self.api_process.terminate()
        if self.backend_process:
            logger.info("Terminating backend process")
            self.backend_process.terminate()
            
        if self.backend:
            self.backend.stop()
        # API doesn't have a clean stop in Flask dev server easily without extra work
        # but in threaded mode daemon=True handles it.

    def wait(self):
        """Wait for processes to complete."""
        if self.api_process:
            self.api_process.wait()
        if self.backend_process:
            self.backend_process.wait()
        
        while self.is_running and self.backend:
            time.sleep(1)

def main():
    parser = argparse.ArgumentParser(description="Program to set current filament & spool in klipper.")
    parser.add_argument("-c", "--config-dir", help="Configuration directory")
    parser.add_argument("--threaded", action="store_true", help="Run in threaded mode instead of processes")
    args = parser.parse_args()

    Nfc2KlipperConfig.configure_logging()
    config = Nfc2KlipperConfig.get_config(args.config_dir)
    
    if not config:
        logger.error("Configuration not found.")
        sys.exit(1)

    orchestrator = Nfc2KlipperOrchestrator(config)
    
    def signal_handler(signum, _frame):
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.threaded or os.getenv("N2K_THREADED"):
        orchestrator.start_threaded()
    else:
        orchestrator.start_processes(args.config_dir)

    try:
        orchestrator.wait()
    except (KeyboardInterrupt, SystemExit):
        orchestrator.stop()

if __name__ == "__main__":
    main()
