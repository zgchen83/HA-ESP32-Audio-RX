"""Media player entity for each ESP-Audio-RX device.

Auto-discovered via MQTT wildcard — no YAML needed.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SIGNAL_NEW_DEVICE, get_device_state, is_device_available, _active_devices

LOGGER = logging.getLogger(__name__)

TOPIC_COMMAND = "esp-audio-rx/{mac}/command"
TOPIC_VOLUME  = "esp-audio-rx/{mac}/volume"
TOPIC_STATE   = "esp-audio-rx/{mac}/state"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up platform — create entities for known devices + listen for new ones."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["add_entities"] = async_add_entities

    # Create entities for already-discovered devices
    pending = hass.data[DOMAIN].get("pending_devices", [])
    entities = []
    for mac in list(pending):
        entities.append(ESPAudioRXPlayer(hass, mac))
    if entities:
        async_add_entities(entities)

    # Listen for future device discoveries
    @callback
    def on_new_device(mac: str) -> None:
        """Create entity for a newly discovered device."""
        LOGGER.info("Adding media_player for %s", mac)
        async_add_entities([ESPAudioRXPlayer(hass, mac)])

    async_dispatcher_connect(hass, SIGNAL_NEW_DEVICE, on_new_device)


class ESPAudioRXPlayer(MediaPlayerEntity):
    """Media player for a single ESP-Audio-RX device."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
    )

    def __init__(self, hass: HomeAssistant, mac: str) -> None:
        """Initialize the entity."""
        self.hass = hass
        self._mac = mac.upper()
        self._name = None          # populated from state
        self._state_str = "idle"
        self._volume = 50
        self._title: str | None = None
        self._artist: str | None = None
        self._attr_unique_id = f"esp_audio_rx_{self._mac}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": f"ESP-Audio-RX {self._mac[-6:]}",
            "manufacturer": "ESP-Audio-RX",
            "model": "ESP32-S3 Audio Receiver",
        }
        self._attr_name = self._mac[-6:]  # default name = last 6 MAC chars

    @property
    def _mac_lower(self) -> str:
        return self._mac.lower()

    # ---- State ----

    @property
    def state(self) -> str:
        s = self._state_str.lower()
        if s == "playing":
            return STATE_PLAYING
        if s == "paused":
            return STATE_PAUSED
        return STATE_IDLE

    @property
    def volume_level(self) -> float | None:
        return max(0.0, min(1.0, self._volume / 100.0))

    @property
    def media_title(self) -> str | None:
        return self._title

    @property
    def media_artist(self) -> str | None:
        return self._artist

    @property
    def available(self) -> bool:
        return is_device_available(self._mac, self.hass.loop.time())

    # ---- Commands — publish MQTT ----

    async def _pub(self, topic_tpl: str, payload: str) -> None:
        await mqtt.async_publish(self.hass, topic_tpl.format(mac=self._mac_lower), payload, 0, False)

    async def async_media_play(self) -> None:
        await self._pub(TOPIC_COMMAND, '{"cmd":"play"}')
    async def async_media_pause(self) -> None:
        await self._pub(TOPIC_COMMAND, '{"cmd":"pause"}')
    async def async_media_stop(self) -> None:
        await self._pub(TOPIC_COMMAND, '{"cmd":"stop"}')
    async def async_media_next_track(self) -> None:
        await self._pub(TOPIC_COMMAND, '{"cmd":"next"}')
    async def async_media_previous_track(self) -> None:
        await self._pub(TOPIC_COMMAND, '{"cmd":"prev"}')
    async def async_set_volume_level(self, volume: float) -> None:
        self._volume = int(round(volume * 100))
        await self._pub(TOPIC_VOLUME, f'{{"volume":{self._volume}}}')
    async def async_volume_up(self) -> None:
        self._volume = min(100, self._volume + 5)
        await self._pub(TOPIC_VOLUME, f'{{"volume":{self._volume}}}')
    async def async_volume_down(self) -> None:
        self._volume = max(0, self._volume - 5)
        await self._pub(TOPIC_VOLUME, f'{{"volume":{self._volume}}}')

    # ---- MQTT state sync ----

    async def async_added_to_hass(self) -> None:
        """Subscribe to this device's state topic."""

        @callback
        def _on_state(message):
            try:
                data = json.loads(message.payload)
            except (json.JSONDecodeError, TypeError):
                return
            self._state_str = data.get("state", self._state_str)
            self._volume = int(data.get("volume", self._volume))
            self._title = data.get("title") or None
            self._artist = data.get("artist") or None
            name = data.get("name")
            if name:
                self._name = name
            self.async_write_ha_state()

        await mqtt.async_subscribe(
            self.hass, TOPIC_STATE.format(mac=self._mac_lower), _on_state, 0
        )

    async def async_update(self) -> None:
        """Periodic refresh — pull from cached state."""
        data = get_device_state(self._mac) or {}
        if data:
            self._state_str = data.get("state", self._state_str)
            self._volume = int(data.get("volume", self._volume))
            self._title = data.get("title") or None
            self._artist = data.get("artist") or None
            if data.get("name"):
                self._name = data["name"]
    @property
    def name(self) -> str | None:
        return self._name or f"ESP-Audio {self._mac[-6:]}"
