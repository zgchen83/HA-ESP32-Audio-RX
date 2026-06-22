"""Config flow — auto-discovered via MQTT, no user input needed."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME

from .const import DOMAIN


class ESPAudioRXConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow — just confirm, no settings required."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — user adds the integration."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return self.async_create_entry(title="ESP-Audio-RX", data={})
