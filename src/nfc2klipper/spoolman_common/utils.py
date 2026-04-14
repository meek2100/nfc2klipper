# SPDX-FileCopyrightText: 2024-2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Common utility functions shared across Spoolman tools.
"""

import os
import tempfile

def get_env_bool(name, legacy_name=None, default=False):
    """Helper to parse boolean environment variables with explicit validation."""
    val = os.environ.get(name)
    if val is None and legacy_name:
        val = os.environ.get(legacy_name)

    if not val:
        return default
    val_lower = val.lower()
    if val_lower in ("true", "1", "yes", "on"):
        return True
    if val_lower in ("false", "0", "no", "off"):
        return False

    err_msg = f"Invalid boolean environment variable {name}"
    if legacy_name:
        err_msg += f" or {legacy_name}"
    err_msg += f": {val!r}. Use: true/false, 1/0, yes/no, or on/off."
    raise ValueError(err_msg)

def get_arg_default(parser, name, legacy_name=None, default_val=False):
    """Safely fetch boolean defaults from environment for argparse."""
    try:
        return get_env_bool(name, legacy_name=legacy_name, default=default_val)
    except ValueError as err:
        parser.error(str(err))
        return None

def get_env_choice(parser, name, choices, legacy_name=None, default=None):
    """Fetch value from env and validate against choices."""
    val = os.environ.get(name)
    if val is None and legacy_name:
        val = os.environ.get(legacy_name)

    if not val:
        return default

    val_lower = val.lower()
    if val_lower in choices:
        return val_lower

    env_name_str = f"environment variable {name}"
    if legacy_name:
        env_name_str += f" (or legacy {legacy_name})"

    parser.error(f"Invalid {env_name_str}: {val!r}. Choose from: {choices}")
    return None

def atomic_write(filename, content, encoding="utf-8"):
    """Write content to a file atomically."""
    directory = os.path.dirname(filename) or "."
    basename = os.path.basename(filename)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=directory,
        prefix=f".tmp_{basename}_",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_filename = tmp_file.name
        tmp_file.write(content)
        tmp_file.flush()
        try:
            os.fsync(tmp_file.fileno())
        except (AttributeError, OSError):
            pass

    try:
        os.replace(tmp_filename, filename)
        return True
    except Exception:
        try:
            os.unlink(tmp_filename)
        except OSError:
            pass
        raise
