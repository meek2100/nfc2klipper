#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

"""A program to write NFC tags from Spoolman's data"""

import argparse
import json
import time
import logging
from typing import Any, Dict, List, Optional

import ndef
import nfc
import npyscreen
import requests

logger = logging.getLogger(__name__)

SPOOL = "SPOOL"
FILAMENT = "FILAMENT"
NDEF_TEXT_TYPE = "urn:nfc:wkt:T"


def record_to_text(record):
    """Translate a json spool object to a readable string"""
    return (
        f"#{record['id']} {record['filament']['vendor']['name']} - "
        f"{record['filament']['material']} - "
        f"{record['filament']['name']}"
    )


class PostList(npyscreen.MultiLineAction):
    """A wrapper for MultiLineAction to call the write_tag function"""

    def actionHighlighted(self, _act_on_this, _key_press):
        """Called when a line is chosen"""
        record = self.parent.records[self.cursor_line]
        self.parent.parentApp.write_tag(record)


class PostSelectForm(npyscreen.FormBaseNew):
    """Simple form for showing the spools"""

    def create(self):
        """Create the forms widgets"""
        self.add(
            npyscreen.ButtonPress,
            name="Exit",
            when_pressed_function=self.exit_app,
        )

        url = self.parentApp.spoolman_url + "/api/v1/spool"
        try:
            records = requests.get(url, timeout=10)
            self.records = json.loads(records.text)
            self.records = sorted(self.records, key=lambda x: x["id"], reverse=True)
        except Exception as e:
            npyscreen.notify_confirm(f"Failed to fetch spools: {e}", title="Error")
            self.records = []

        self.posts = self.add(
            PostList,
            values=list(map(record_to_text, self.records)),
            name="Choose spools to write",
            scroll_exit=True,
        )

    def exit_app(self):
        """Called when exit is choosen"""
        self.parentApp.switchForm(None)


class TagWritingApp(npyscreen.NPSAppManaged):
    """The npyscreen's main class for the application"""

    def __init__(self, nfc_device: str, spoolman_url: str):
        super().__init__()
        self.nfc_device = nfc_device
        self.spoolman_url = spoolman_url
        self.status = ""

    def on_nfc_connect(self, tag, spool: int, filament: int) -> bool:
        """Write given spool/filament ids to the tag"""
        try:
            if tag.ndef and tag.ndef.is_writeable:
                tag.ndef.records = [
                    ndef.TextRecord(f"SPOOL:{spool}\nFILAMENT:{filament}\n")
                ]
                self.status = "Written Successfully"
            else:
                self.status = "Tag is write protected"
        except Exception as ex:
            self.status = f"Got error while writing: {ex}"
        return False

    def write_tag(self, record):
        """Write the choosen records's data to the tag"""
        npyscreen.notify("Writing " + record_to_text(record), title="Writing to tag")

        spool = record["id"]
        filament = record["filament"]["id"]

        try:
            clf = nfc.ContactlessFrontend(self.nfc_device)
            clf.connect(
                rdwr={
                    "on-connect": lambda tag: self.on_nfc_connect(tag, spool, filament)
                }
            )
            clf.close()
        except Exception as e:
            self.status = f"Failed to connect to NFC device: {e}"

        npyscreen.notify(self.status, title="Results")
        time.sleep(1)

    def onStart(self):
        """Called when application starts, just add the form"""
        form = self.addForm(
            "MAIN",
            PostSelectForm,
            name="Choose spool, press enter to write to tag",
        )
        form.set_editing(form.posts)


def main():
    parser = argparse.ArgumentParser(
        description="Fetches spools from Spoolman and allows writing info about them to RFID tags.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.0.1")
    parser.add_argument(
        "-d",
        "--nfc-device",
        metavar="device",
        default="ttyAMA0",
        help="Which NFC reader to use",
    )
    parser.add_argument(
        "-u",
        "--url",
        metavar="URL",
        default="http://mainsailos.local:8000",
        help="URL for the Spoolman installation",
    )
    args = parser.parse_args()

    # Prefer environment variables if set
    nfc_device = os.getenv("N2K_NFC_DEVICE", args.nfc_device)
    spoolman_url = os.getenv("N2K_SPOOLMAN_URL", args.url)

    app = TagWritingApp(nfc_device=nfc_device, spoolman_url=spoolman_url)
    app.run()


if __name__ == "__main__":
    main()
