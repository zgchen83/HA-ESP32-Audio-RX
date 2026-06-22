"""Constants for ESP-Audio-RX Home Assistant integration."""

DOMAIN = "esp_audio_rx"

# MQTT topic base — auto-discovery scans this wildcard
DISCOVERY_TOPIC = "esp-audio-rx/+/state"

# Per-device topic patterns
TOPIC_STATE        = "esp-audio-rx/{mac}/state"
TOPIC_COMMAND      = "esp-audio-rx/{mac}/command"
TOPIC_VOLUME       = "esp-audio-rx/{mac}/volume"
TOPIC_AVAILABILITY = "esp-audio-rx/{mac}/availability"

# How long before marking device unavailable (seconds)
AVAILABILITY_TIMEOUT = 120
