"""ESP-Audio-RX — MQTT media_player.

Discovery via esp-audio-rx/+/state.
Browse uses HA's built-in media_source (DLNA, etc.) — fast, no ESP32 SSDP needed.
Play resolves media URLs via HA and sends play_url via MQTT.
"""
from __future__ import annotations

import json
import logging
import re

from homeassistant.components import media_source, mqtt
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

LOGGER = logging.getLogger(__name__)
DOMAIN = "esp_audio_rx"

# Regexen for DIDL-Lite XML field extraction
import html
_DIDL_RE = {
    'title':  re.compile(r'<dc:title[^>]*>([^<]*)</dc:title>', re.I),
    'artist': re.compile(r'<(?:upnp:artist|dc:creator)[^>]*>([^<]*)</(?:upnp:artist|dc:creator)>', re.I),
    'album':  re.compile(r'<upnp:album[^>]*>([^<]*)</upnp:album>', re.I),
    'art':    re.compile(r'<upnp:albumArtURI[^>]*>([^<]*)</upnp:albumArtURI>', re.I),
    'dur':    re.compile(r'duration="([^"]*)"', re.I),
}


def _parse_didl(didl_xml: str) -> dict:
    """Extract title/artist/album/art/duration from DIDL-Lite XML."""
    result: dict = {}
    # HTML-entity decode once before matching
    try:
        decoded = html.unescape(didl_xml)
    except Exception:
        decoded = didl_xml
    for key, regex in _DIDL_RE.items():
        m = regex.search(decoded)
        if m:
            val = m.group(1).strip()
            if val:
                if key == 'dur':
                    result[key] = _parse_didl_duration(val)
                else:
                    result[key] = val
    return result


def _parse_didl_duration(dur: str) -> int | None:
    """Parse DIDL duration like '0:03:45.000' → seconds."""
    try:
        parts = dur.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except (ValueError, IndexError):
        pass
    return None

LOGGER.warning("ESP-Audio-RX media_player module loaded (v6-queue)")

# Backward compat: MEDIA_ENQUEUE added in HA 2024.2
_ENQUEUE_FLAG = getattr(MediaPlayerEntityFeature, 'MEDIA_ENQUEUE', 0)

_STATE_TOPIC_RE = re.compile(r"^esp-audio-rx/([0-9A-F]{12})/state$")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    LOGGER.warning("ESP-Audio-RX: async_setup_entry running")

    known_macs: set[str] = set()
    _add_entities = async_add_entities

    @callback
    def on_state(message):
        try:
            mac = _extract_mac(message.topic)
            if not mac or mac in known_macs:
                return
            known_macs.add(mac)
            try:
                data = json.loads(message.payload)
            except (json.JSONDecodeError, TypeError):
                return
            dev_name = data.get("name", f"ESP-Audio-RX {mac[-6:]}")
            LOGGER.warning("ESP-Audio-RX: DISCOVERED %s (%s)", mac, dev_name)
            _add_entities([ESPAudioRXPlayer(hass, mac, dev_name)])
        except Exception:
            LOGGER.error("ESP-Audio-RX: on_state crashed for %s", message.topic, exc_info=True)

    await mqtt.async_subscribe(hass, "esp-audio-rx/+/state", on_state, 0)
    LOGGER.warning("ESP-Audio-RX: subscribed OK")


def _extract_mac(topic: str) -> str | None:
    m = _STATE_TOPIC_RE.match(topic)
    return m.group(1).upper() if m else None


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
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | _ENQUEUE_FLAG
    )

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
    def media_album_name(self) -> str | None:
        return self._album

    @property
    def media_image_url(self) -> str | None:
        return self._image_url

    @property
    def media_duration(self) -> int | None:
        return self._duration

    @property
    def media_content_types(self) -> list[str]:
        """Accept all content types — DLNA sources may have varied formats."""
        return [
            MediaType.MUSIC, MediaType.URL, MediaType.PLAYLIST,
            MediaType.ALBUM, MediaType.ARTIST, MediaType.GENRE,
            MediaType.TRACK, MediaType.CHANNEL, MediaType.PODCAST,
            MediaType.EPISODE,
        ]

    @property
    def media_position(self) -> int | None:
        return self._position

    @property
    def media_position_updated_at(self):
        if self._position_updated:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(self._position_updated, tz=timezone.utc)
        return None

    async def _pub(self, topic: str, payload: str, qos: int = 0) -> None:
        await mqtt.async_publish(self.hass, topic, payload, qos, False)

    async def async_media_play(self) -> None:
        self._state_str = "playing"
        self.async_write_ha_state()
        await self._pub(self._command_topic, '{"cmd":"play"}')
    async def async_media_pause(self) -> None:
        self._state_str = "paused"
        self.async_write_ha_state()
        await self._pub(self._command_topic, '{"cmd":"pause"}')
    async def async_media_stop(self) -> None:
        self._state_str = "idle"
        self.async_write_ha_state()
        await self._pub(self._command_topic, '{"cmd":"stop"}')
    async def async_media_next_track(self) -> None:
        await self._pub(self._command_topic, '{"cmd":"next"}')
    async def async_media_previous_track(self) -> None:
        await self._pub(self._command_topic, '{"cmd":"prev"}')
    async def async_set_volume_level(self, volume: float) -> None:
        self._volume = int(round(volume * 100))
        await self._pub(self._volume_topic, f'{{"volume":{self._volume}}}')

    # ---- Media browsing via HA media_source ----

    def __init__(self, hass: HomeAssistant, mac: str, dev_name: str) -> None:
        super().__init__()
        self.hass = hass
        self._mac = mac.upper()
        self._state_str = "idle"
        self._volume = 50
        self._title: str | None = None
        self._artist: str | None = None
        self._album: str | None = None
        self._image_url: str | None = None
        self._duration: int | None = None
        self._position: int | None = None
        self._position_updated: float = 0
        self._media_cache: dict[str, dict] = {}  # content_id → metadata
        self._last_browse_children: list[dict] = []  # {content_id, url?, title, ...}

        self._state_topic = f"esp-audio-rx/{self._mac}/state"
        self._command_topic = f"esp-audio-rx/{self._mac}/command"
        self._volume_topic = f"esp-audio-rx/{self._mac}/volume"
        self._avail_topic = f"esp-audio-rx/{self._mac}/availability"

        self._attr_unique_id = f"esp_audio_rx_{self._mac}"
        self._attr_name = dev_name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._mac)},
            "name": dev_name,
            "manufacturer": "ESP-Audio-RX",
            "model": "ESP32-S3 Audio Receiver",
        }
        self._attr_available = False

    async def async_browse_media(
        self, media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse media using HA's built-in media_source (DLNA etc)."""
        result = await media_source.async_browse_media(
            self.hass, media_content_id,
        )
        # Cache metadata and store siblings for auto-enqueue
        if result.children:
            self._last_browse_children = []
            for child in result.children:
                if child.can_play and child.media_content_id:
                    # Log available attrs for first playable child (debug)
                    if len(self._media_cache) == 0:
                        LOGGER.warning("BrowseMedia child attrs: title=%s thumbnail=%s "
                                        "duration=%s artist=%s album=%s",
                                        child.title, child.thumbnail,
                                        getattr(child, 'duration', 'N/A'),
                                        getattr(child, 'artist', 'N/A'),
                                        getattr(child, 'album', 'N/A'))
                    meta = {
                        'title': child.title or '',
                        'artist': getattr(child, 'artist', '') or '',
                        'album': getattr(child, 'album', '') or '',
                        'thumbnail': child.thumbnail or '',
                        'duration': getattr(child, 'duration', None),
                        'content_id': child.media_content_id or '',
                        'can_play': child.can_play,
                    }
                    self._media_cache[child.media_content_id] = meta
                    self._last_browse_children.append(meta)
        return result

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        """Resolve media URL via HA and send play_url to ESP32."""
        LOGGER.warning("play_media: type=%s id=%.120s", media_type, media_id)

        # Resolve the media source to an actual URL
        try:
            resolved = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id)
        except Exception as exc:
            LOGGER.error("Failed to resolve media: %s", exc)
            return

        if not resolved or not resolved.url:
            LOGGER.error("Resolved media has no URL")
            return

        LOGGER.warning("Resolved URL: %s", resolved.url[:120])
        didl = getattr(resolved, 'didl_metadata', '') or ''

        # Extract metadata from didl_metadata (MusicTrack object or XML string)
        didl_meta: dict = {}
        if didl:
            if isinstance(didl, str):
                didl_meta = _parse_didl(didl)
            else:
                # MusicTrack / DIDL object — read attrs directly
                title = getattr(didl, 'title', '') or ''
                artist = getattr(didl, 'artist', '') or getattr(didl, 'creator', '') or ''
                album = getattr(didl, 'album', '') or getattr(didl, 'album_name', '') or ''
                art_uri = getattr(didl, 'album_art_uri', '') or ''

                # Duration from first <res> element
                duration = None
                res_list = getattr(didl, 'res', None)
                if res_list:
                    res_items = res_list if isinstance(res_list, list) else [res_list]
                    for r in res_items:
                        dur_str = getattr(r, 'duration', None)
                        if dur_str:
                            duration = _parse_didl_duration(str(dur_str))
                            break

                didl_meta = {
                    'title': title, 'artist': artist, 'album': album,
                    'art': art_uri, 'dur': duration,
                }
        if didl_meta:
            LOGGER.warning("DIDL parsed: %s", didl_meta)

        # Fall back to browse cache
        cache_meta = self._media_cache.pop(media_id, {})

        title = didl_meta.get('title') or cache_meta.get('title') or ''
        artist = didl_meta.get('artist') or cache_meta.get('artist') or ''
        album = didl_meta.get('album') or cache_meta.get('album') or ''
        thumbnail = didl_meta.get('art') or cache_meta.get('thumbnail') or ''
        duration = didl_meta.get('dur') or cache_meta.get('duration')

        # Fallback: extract filename from URL
        if not title:
            path = resolved.url.split("?")[0].split("/")[-1]
            title = path.rsplit(".", 1)[0] if "." in path else path

        enqueue = kwargs.get("enqueue")
        if enqueue not in ("next", "add", "replace"):
            # Auto-enqueue siblings in background (continuous album play)
            self.hass.async_create_background_task(
                self._enqueue_siblings(media_id), "esp_audio_enqueue_siblings")

        if enqueue in ("next", "add", "replace"):
            cmd = {"cmd": "enqueue", "url": resolved.url}
            if title:
                cmd["title"] = title
            await self._pub(self._command_topic, json.dumps(cmd))
            return
        else:
            cmd = {"cmd": "play_url", "url": resolved.url}
            if title:
                cmd["title"] = title
            if artist:
                cmd["artist"] = artist
            if album:
                cmd["album"] = album
            if thumbnail:
                cmd["art"] = thumbnail
            if duration:
                cmd["dur"] = duration
        await self._pub(self._command_topic, json.dumps(cmd))

        # Update local state immediately
        self._state_str = "playing"
        self._title = title or None
        self._artist = artist or None
        self._album = album or None
        self._image_url = thumbnail or None
        self._duration = int(duration) if duration else None
        self.async_write_ha_state()

    async def _enqueue_siblings(self, played_id: str) -> None:
        """Background: resolve & enqueue sibling tracks from last browse."""
        siblings = [s for s in self._last_browse_children
                     if s.get('can_play') and s.get('content_id') != played_id]
        if not siblings:
            return
        count = 0
        for sib in siblings[:10]:  # max 10 siblings
            sid = sib.get('content_id', '')
            if not sid:
                continue
            try:
                sres = await media_source.async_resolve_media(
                    self.hass, sid, self.entity_id)
                if sres and sres.url:
                    stitle = sib.get('title', '') or ''
                    scmd = {"cmd": "enqueue", "url": sres.url}
                    if stitle:
                        scmd["title"] = stitle
                    await self._pub(self._command_topic, json.dumps(scmd))
                    count += 1
            except Exception:
                pass
        if count:
            LOGGER.warning("Auto-enqueued %d sibling tracks", count)

    # ---- MQTT state sync ----

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_state(message):
            try:
                data = json.loads(message.payload)
            except (json.JSONDecodeError, TypeError):
                return
            self._state_str = data.get("state", self._state_str)
            self._volume = int(data.get("volume", self._volume))
            if data.get("title"):
                self._title = data["title"]
            if data.get("artist"):
                self._artist = data["artist"]
            # Position from ESP32 heartbeat
            if "pos_s" in data:
                self._position = data["pos_s"]
                import time
                self._position_updated = time.time()
            if "dur_s" in data and data["dur_s"] > 0 and not self._duration:
                self._duration = data["dur_s"]
            self._attr_available = True
            self.async_write_ha_state()

        @callback
        def _on_avail(message):
            payload = message.payload
            if isinstance(payload, bytes):
                payload = payload.decode()
            self._attr_available = payload == "online"
            self.async_write_ha_state()

        await mqtt.async_subscribe(self.hass, self._state_topic, _on_state, 0)
        await mqtt.async_subscribe(self.hass, self._avail_topic, _on_avail, 0)
