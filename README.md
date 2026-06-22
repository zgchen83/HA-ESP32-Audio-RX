# ESP-Audio-RX — Home Assistant Integration

Auto-discovers ESP32 audio receivers on your network and creates full-featured **media_player** entities in Home Assistant.

## Features

- **Zero YAML** — install once, all devices auto-appear
- **Full media controls** — play/pause/stop/next/prev/volume
- **Live metadata** — title, artist, album display in HA
- **Multi-device** — any number of ESP32 receivers, auto-distinguished by MAC

## Installation

### HACS (recommended)

1. In HACS, add this repository as a **custom repository** (type: Integration)
2. Install "ESP-Audio-RX"
3. Go to **Settings → Devices & Services → Add Integration → ESP-Audio-RX**
4. Done — devices will appear as they connect

### Manual

```bash
cd /config/custom_components
git clone <this-repo-url> esp_audio_rx
# Or copy the custom_components/esp_audio_rx/ folder
```

Then restart HA and add the integration.

## How It Works

The integration subscribes to `esp-audio-rx/+/state` on your MQTT broker. When an ESP32 publishes its state, HA automatically creates a `media_player.` entity. Commands are sent back via MQTT to control the device.

## Requirements

- Home Assistant 2025.1 or later
- MQTT integration configured and connected to the same broker as your ESP32 devices
- ESP-Audio-RX firmware with MQTT enabled (HA Discovery checkbox ON in Web UI)
