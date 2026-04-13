# SPDX-FileCopyrightText: 2026 Sebastian Andersson <sebastian@bittr.nu>
# SPDX-License-Identifier: GPL-3.0-or-later

FROM python:3.10-slim

# Install system dependencies for nfcpy and hardware access
RUN apt-get update && apt-get install -y --no-install-recommends \
    libusb-1.0-0 \
    patch \
    && rm -rf /var/lib/apt/lists/*

# Make UID and GID configurable
ARG USER_UID=1000
ARG USER_GID=1000

# Create a non-root user and group
RUN groupadd -g ${USER_GID} nfc2klipper && \
    useradd -m -u ${USER_UID} -g nfc2klipper nfc2klipper && \
    usermod -a -G dialout,i2c nfc2klipper

WORKDIR /app

# Copy the source code
COPY . .

# Install the package
RUN pip install --no-cache-dir .

# Apply PN532 patch to nfcpy
RUN find /usr/local/lib/python3.10/site-packages/nfc/clf/ -name "pn532.py" -exec patch {} /app/pn532.py.patch \;

# Pre-seed the configuration directory
RUN mkdir -p /home/nfc2klipper/.config/nfc2klipper && \
    cp nfc2klipper.cfg /home/nfc2klipper/.config/nfc2klipper/ && \
    chown -R nfc2klipper:nfc2klipper /home/nfc2klipper

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV N2K_THREADED=true

# Switch to the non-root user
USER nfc2klipper

# Launch the service
ENTRYPOINT [ "nfc2klipper" ]
