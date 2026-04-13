# NFC2Klipper Plugin Guide

This document describes how to use **nfc2klipper** as a modular extension, specifically when integrated with **spoolman2slicer**.

## Installation

When using the unified toolset, you can install nfc2klipper as a package:

```bash
cd nfc2klipper
pip install .
```

## Hardware Configuration (Crucial)

NFC readers interact directly with system hardware (Serial/UART, I2C, or USB). To ensure the plugin can communicate with the hardware, the user running the process must have appropriate permissions.

### 1. Group Permissions
Add your user to the following groups:
```bash
sudo usermod -a -G dialout,i2c,lp $USER
```
*Note: You must log out and back in for these changes to take effect.*

### 2. Identifying your Device
- **UART (Raspberry Pi)**: Typically `/dev/ttyAMA0` or `/dev/ttyS0`.
- **USB**: Typically `/dev/ttyUSB0` or identified via `lsusb`.

### 3. PN532 Workaround
If using a PN532 over UART on a Raspberry Pi, there is a known bug in the `nfcpy` library. A patch is included in the repository (`pn532.py.patch`) and is automatically applied in the official Docker builds.

## Environment Variables

Configuration can be handled entirely via environment variables with the `N2K_` prefix:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `N2K_NFC_DEVICE` | Hardware device string (e.g., `tty:AMA0`) | `tty:AMA0` |
| `N2K_SPOOLMAN_URL` | URL to your Spoolman instance | `http://localhost:7912` |
| `N2K_MOONRAKER_URL` | URL to your Moonraker instance | `http://localhost` |
| `N2K_THREADED` | Run API and Backend in a single process | `False` |
| `N2K_WEB_DISABLE` | Disable the web interface | `False` |
| `N2K_WEB_PORT` | Port for the web API | `5001` |

## Docker Usage

When running in Docker, you **must** pass the hardware device through:

```yaml
services:
  nfc2klipper:
    image: ghcr.io/bofh69/nfc2klipper
    devices:
      - /dev/ttyAMA0:/dev/ttyAMA0
    environment:
      - N2K_NFC_DEVICE=tty:AMA0
      - N2K_SPOOLMAN_URL=http://spoolman:7912
```
