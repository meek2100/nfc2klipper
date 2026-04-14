# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Orchestration logic for syncing NFC tag reads to Spoolman and Klipper."""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple
from .api import KlipperClient
from .spoolman_common.api import SpoolmanClient

# Import legacy parsers for now - we'll keep them in lib/ to minimize churn
from .lib.nfc_parsers import NdefTextParser, TagIdentifierParser
from .lib.opentag3d_parser import OpenTag3DParser

logger = logging.getLogger(__name__)

class NfcSyncEngine:
    """The core engine that processes NFC events and coordinates updates."""

    def __init__(
        self,
        spoolman: SpoolmanClient,
        klipper: KlipperClient,
        parsers: List[Any],
        always_send: bool = False,
        clear_on_missing: bool = False
    ):
        self.spoolman = spoolman
        self.klipper = klipper
        self.parsers = parsers
        self.always_send = always_send
        self.clear_on_missing = clear_on_missing
        self._lock = threading.Lock()

        # State tracking
        self.last_nfc_id: Optional[str] = None
        self.last_spool_id: Optional[int] = None
        self.last_filament_id: Optional[int] = None

    def on_tag_present(self, ndef_data: Any, nfc_id: str):
        """Callback for when a physical tag is detected."""
        logger.info(f"NFC Tag Detected: {nfc_id}")
        with self._lock:
            self.last_nfc_id = nfc_id

        # Try all parsers in sequence
        spool_id_str = None
        filament_id_str = None

        for parser in self.parsers:
            try:
                res = parser.parse(ndef_data, nfc_id)
                if res and res[0] and res[1]:
                    spool_id_str, filament_id_str = res
                    break
            except Exception as e:
                logger.error(f"Parser {parser.__class__.__name__} failed: {e}")

        if spool_id_str and filament_id_str:
            spool_id = int(spool_id_str)
            filament_id = int(filament_id_str)
            self._update_klipper(spool_id, filament_id)
        else:
            logger.warning(f"No valid Spoolman data found on tag {nfc_id}")

    def on_tag_removed(self):
        """Callback for when no tag is present under the reader."""
        if self.clear_on_missing:
            logger.info("Tag removed, clearing Klipper state as per config.")
            self._update_klipper(0, 0)

    def _update_klipper(self, spool_id: int, filament_id: int):
        """Update Klipper macros if the data has changed or always_send is True."""
        is_change = (spool_id != self.last_spool_id) or (filament_id != self.last_filament_id)
        
        if self.always_send or is_change:
            try:
                if spool_id > 0 and filament_id > 0:
                    self.klipper.set_spool_and_filament(spool_id, filament_id)
                else:
                    self.klipper.clear_spool_and_filament()
                
                with self._lock:
                    self.last_spool_id = spool_id
                    self.last_filament_id = filament_id
            except Exception as e:
                logger.error(f"Failed to update Klipper: {e}")
        else:
            logger.debug("Spool/Filament unchanged, skipping Klipper update.")

    def get_current_state(self) -> Dict[str, Any]:
        """Return the current sync state for API consumption."""
        with self._lock:
            return {
                "nfc_id": self.last_nfc_id,
                "spool_id": self.last_spool_id,
                "filament_id": self.last_filament_id
            }

    def write_tag(self, spool_id: int, filament_id: int, handler: Any) -> bool:
        """Command the hardware handler to write data to the next available tag."""
        # This will be called via the Web API
        logger.info(f"Queueing write to tag: Spool={spool_id}, Filament={filament_id}")
        return handler.write_to_tag(spool_id, filament_id)

    def set_nfc_id_in_spoolman(self, spool_id: int) -> bool:
        """Explicitly link the last read NFC ID to a Spoolman spool."""
        if not self.last_nfc_id:
            logger.error("Cannot set NFC ID: No tag has been read yet.")
            return False
            
        try:
            return self.spoolman.set_nfc_id_to_spool(spool_id, self.last_nfc_id)
        except Exception as e:
            logger.error(f"Failed to update Spoolman with NFC ID: {e}")
            return False
