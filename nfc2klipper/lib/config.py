#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read config file and environment variables"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import toml  # pylint: disable=import-error


class Nfc2KlipperConfig:
    """Class to handle configuration data for the application"""

    PROGNAME: str = "nfc2klipper"
    CFG_DIR: str = "~/.config/nfc2klipper"
    DEFAULT_SOCKET_PATH: str = "~/nfc2klipper/nfc2klipper.sock"

    @classmethod
    def configure_logging(cls) -> None:
        """Configure the logging"""
        log_level = logging.DEBUG if os.getenv("N2K_DEBUG") else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s - %(name)s: %(message)s",
        )

    @classmethod
    def get_config(cls, config_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the config data, merging file and environment variables"""
        config: Dict[str, Any] = {
            "webserver": {
                "disable_web_server": os.getenv("N2K_WEB_DISABLE", "").lower() in ("1", "true", "yes"),
                "web_address": os.getenv("N2K_WEB_ADDRESS", "0.0.0.0"),
                "web_port": int(os.getenv("N2K_WEB_PORT", "5001")),
                "socket_path": os.getenv("N2K_SOCKET_PATH", cls.DEFAULT_SOCKET_PATH),
            },
            "nfc": {
                "nfc-device": os.getenv("N2K_NFC_DEVICE", "tty:AMA0"),
            },
            "spoolman": {
                "spoolman-url": os.getenv("N2K_SPOOLMAN_URL", "http://localhost:7912"),
            },
            "moonraker": {
                "moonraker-url": os.getenv("N2K_MOONRAKER_URL", "http://localhost"),
                "clear-spool": os.getenv("N2K_CLEAR_SPOOL", "").lower() in ("1", "true", "yes"),
                "always-send": os.getenv("N2K_ALWAYS_SEND", "").lower() in ("1", "true", "yes"),
            },
            "macros": {
                "setting_gcode": os.getenv("N2K_SETTING_GCODE"),
                "clearing_gcode": os.getenv("N2K_CLEARING_GCODE"),
            },
            "opentag3d": {
                "filament_name_template": os.getenv("N2K_FILAMENT_TEMPLATE"),
                "filament_field_mapping": {},
                "spool_field_mapping": {},
            }
        }

        search_paths: List[str] = []
        if config_dir:
            search_paths.append(os.path.join(config_dir, "nfc2klipper.cfg"))
        elif os.getenv("N2K_CONFIG_PATH"):
             search_paths.append(os.getenv("N2K_CONFIG_PATH"))
        else:
            search_paths.extend([
                "~/nfc2klipper.cfg",
                os.path.expanduser(cls.CFG_DIR + "/nfc2klipper.cfg"),
            ])

        file_config = None
        for path in search_paths:
            cfg_filename: str = os.path.expanduser(path)
            if os.path.exists(cfg_filename):
                try:
                    with open(cfg_filename, "r", encoding="utf-8") as fp:
                        file_config = toml.load(fp)
                        logging.info("Loaded config from %s", path)
                        break
                except Exception as e:
                    logging.warning("Failed to load config from %s: %s", path, e)

        if file_config:
            # Deep merge file_config into config, but only if environment variables are NOT set
            # For simplicity, we'll just check each key
            cls._merge_section(config, file_config, "webserver", ["disable_web_server", "web_address", "web_port", "socket_path"], "N2K_WEB_")
            cls._merge_section(config, file_config, "nfc", ["nfc-device"], "N2K_NFC_")
            cls._merge_section(config, file_config, "spoolman", ["spoolman-url"], "N2K_SPOOLMAN_")
            cls._merge_section(config, file_config, "moonraker", ["moonraker-url", "clear-spool", "always-send"], "N2K_MOONRAKER_")
            cls._merge_section(config, file_config, "macros", ["setting_gcode", "clearing_gcode"], "N2K_")
            
            if "opentag3d" in file_config:
                ot3d = file_config["opentag3d"]
                if "filament_name_template" in ot3d and not os.getenv("N2K_FILAMENT_TEMPLATE"):
                    config["opentag3d"]["filament_name_template"] = ot3d["filament_name_template"]
                config["opentag3d"]["filament_field_mapping"] = ot3d.get("filament_field_mapping", {})
                config["opentag3d"]["spool_field_mapping"] = ot3d.get("spool_field_mapping", {})

        return config

    @classmethod
    def _merge_section(cls, dest, src, section, keys, env_prefix):
        if section not in src:
            return
        for key in keys:
            env_key = env_prefix + key.upper().replace("-", "_")
            if key in src[section] and not os.getenv(env_key):
                dest[section][key] = src[section][key]

    @classmethod
    def install_config(cls, config_dir: Optional[str] = None) -> None:
        """Copy the default config file to the right place"""
        cfg_dir: str = os.path.expanduser(
            config_dir if config_dir else Nfc2KlipperConfig.CFG_DIR
        )
        if not os.path.exists(cfg_dir):
            print(f"Creating dir {cfg_dir}", file=sys.stderr)
            Path(cfg_dir).mkdir(parents=True, exist_ok=True)
        
        # Search for for the default config file in current and parent dirs
        script_dir: str = os.path.dirname(os.path.abspath(__file__))
        search_dirs = [
            os.path.join(script_dir, "..", ".."), # repo root
            os.path.join(script_dir, ".."),       # package root
            os.path.join(script_dir)              # current dir
        ]
        
        from_filename = None
        for d in search_dirs:
            path = os.path.join(d, "nfc2klipper.cfg")
            if os.path.exists(path):
                from_filename = path
                break
        
        if not from_filename:
             print("Could not find default nfc2klipper.cfg to install", file=sys.stderr)
             return

        to_filename: str = os.path.join(cfg_dir, "nfc2klipper.cfg")
        shutil.copyfile(from_filename, to_filename)
        print(f"Created {to_filename}, please update it", file=sys.stderr)

    @classmethod
    def get_setting_gcode(cls, config: Dict[str, Any]) -> List[str]:
        """Get spool & filament setting gcode templates from config, or default value"""
        setting_gcode = config.get("macros", {}).get("setting_gcode")
        if not setting_gcode:
            setting_gcode = "SET_ACTIVE_SPOOL ID={spool}\nSET_ACTIVE_FILAMENT ID={filament}"
        return [cmd.strip() for cmd in setting_gcode.split("\n") if cmd.strip()]

    @classmethod
    def get_clearing_gcode(cls, config: Dict[str, Any]) -> List[str]:
        """Get spool & filament clearing gcode templates from config, or default value"""
        clearing_gcode = config.get("macros", {}).get("clearing_gcode")
        if not clearing_gcode:
            clearing_gcode = "CLEAR_ACTIVE_SPOOL\nSET_ACTIVE_FILAMENT ID=0"
        return [cmd.strip() for cmd in clearing_gcode.split("\n") if cmd.strip()]

    @classmethod
    def get_opentag3d_filament_name_template(cls, config: Dict[str, Any]) -> str:
        """Get OpenTag3D filament name template from config, or default value"""
        template = config.get("opentag3d", {}).get("filament_name_template")
        return template if template else "{color_name}"

    @classmethod
    def get_opentag3d_filament_field_mapping(cls, config: Dict[str, Any]) -> Dict[str, str]:
        """Get OpenTag3D to Spoolman filament field mapping from config"""
        mapping = config.get("opentag3d", {}).get("filament_field_mapping")
        if mapping:
            return mapping
        return {
            "weight": "target_weight",
            "settings_bed_temp": "bed_temp",
            "settings_extruder_temp": "print_temp",
        }

    @classmethod
    def get_opentag3d_spool_field_mapping(cls, config: Dict[str, Any]) -> Dict[str, str]:
        """Get OpenTag3D to Spoolman spool field mapping from config"""
        mapping = config.get("opentag3d", {}).get("spool_field_mapping")
        if mapping:
            return mapping
        return {
            "remaining_weight": "measured_filament_weight",
            "lot_nr": "serial",
        }
