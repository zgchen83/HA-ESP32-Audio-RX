"""ESP-Audio-RX — automatic MQTT media player discovery.

Subscribes to esp-audio-rx/+/state via MQTT wildcard and creates
a media_player entity for every ESP32 audio receiver on the network.
Zero YAML configuration required.

HACS install → Add Integration → "ESP-Audio-RX" → done.
"""

from __future__ import annotations

import json
import logging
import re

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

LOGGER = logging.getLogger(__name__)

DOMAIN = "esp_audio_rx"
PLATFORMS = [Platform.MEDIA_PLAYER]

SIGNAL_NEW_DEVICE = "esp_audio_rx_new_device"

# Regex: esp-audio-rx/MAC/state
_MAC_RE = re.compile(r"esp-audio-rx/([0-9A-F]{12})/state", re.I)

# Per-device state cache
_active_devices: dict[str, dict] = {}


def get_device_state(mac: str) -> dict | None:
    """Get the last known state dict for a device, or None."""
    dev = _active_devices.get(mac.upper())
    return dev.get("state") if dev else None


def is_device_available(mac: str, now: float) -> bool:
    """True if device is considered online."""
    dev = _active_devices.get(mac.upper())
    if not dev:
        return False
    if dev.get("available") is False:
        return False
    return (now - dev.get("last_seen", 0)) < 120


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the ESP-Audio-RX integration."""
    hass.data.setdefault(DOMAIN, {})
    if "pending_devices" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["pending_devices"] = []

    @callback
    def on_state_message(message):
        """MQTT state message → discover or update device."""
        m = _MAC_RE.search(message.topic)
        if not m:
            return
        mac = m.group(1).upper()

        try:
            data = json.loads(message.payload)
        except (json.JSONDecodeError, TypeError):
            return

        is_new = mac not in _active_devices
        _active_devices.setdefault(mac, {})
        _active_devices[mac]["last_seen"] = hass.loop.time()
        _active_devices[mac]["state"] = data

        if is_new:
            LOGGER.info("Discovered ESP-Audio-RX: %s (%s)", mac, data.get("name", "?"))
            # Signal platform to create entity for this new device
            pending = hass.data[DOMAIN].setdefault("pending_devices", [])
            if mac not in pending:
                pending.append(mac)
            async_dispatcher_send(hass, SIGNAL_NEW_DEVICE, mac)

    @callback
    def on_availability_message(message):
        """Track online/offline."""
        m = re.match(r"esp-audio-rx/([0-9A-F]{12})/availability", message.topic, re.I)
        if not m:
            return
        mac = m.group(1).upper()
        payload = message.payload
        if isinstance(payload, bytes):
            payload = payload.decode()
        _active_devices.setdefault(mac, {})
        _active_devices[mac]["available"] = payload != "offline"
        if payload != "offline":
            _active_devices[mac]["last_seen"] = hass.loop.time()

    await mqtt.async_subscribe(hass, "esp-audio-rx/+/state", on_state_message, 0)
    await mqtt.async_subscribe(hass, "esp-audio-rx/+/availability", on_availability_message, 0)

    LOGGER.info("ESP-Audio-RX MQTT listener active")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload integration."""
    _active_devices.clear()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
