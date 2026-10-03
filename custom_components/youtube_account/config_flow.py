"""Config flow for YouTube Account: sign in with browser cookies."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from . import youtube
from .const import (
    ACCOUNT_UNIQUE_ID,
    CONF_COOKIES,
    CONF_COOKIES_FILE,
    CONF_MIN_REFRESH,
    DEFAULT_MIN_REFRESH,
    DOMAIN,
    LOGGER,
)

COOKIES_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_COOKIES): TextSelector(TextSelectorConfig(multiline=True)),
        vol.Optional(CONF_COOKIES_FILE): TextSelector(),
    }
)
ACCOUNT_TITLE = "YouTube account"
# A cookies.txt is a few kB; anything far larger is the wrong file.
MAX_COOKIES_FILE = 1_000_000


def _read_cookies_file(path: str) -> str | None:
    """Return a cookies file's text, or None when it can't be read."""
    try:
        file = Path(path).expanduser()
        if not file.is_file() or file.stat().st_size > MAX_COOKIES_FILE:
            return None
        return file.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None


class YouTubeAccountConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in to YouTube with cookies."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AccountOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the cookies: pasted, or a cookies.txt on the HA host."""
        errors: dict[str, str] = {}
        if user_input is not None:
            text = (user_input.get(CONF_COOKIES) or "").strip()
            path = (user_input.get(CONF_COOKIES_FILE) or "").strip()
            if not text and path:
                text = (
                    await self.hass.async_add_executor_job(_read_cookies_file, path)
                    or ""
                )
                if not text:
                    errors[CONF_COOKIES_FILE] = "file_unreadable"
            elif not text:
                errors["base"] = "no_cookies"
            if not errors:
                cookies, errors = await self._async_check_cookies(text)
                if cookies is not None:
                    return await self._async_finish(cookies)
        # Never suggest the value back: it's a sign-in.
        return self.async_show_form(
            step_id="user", data_schema=COOKIES_SCHEMA, errors=errors
        )

    async def _async_finish(self, cookies: str) -> ConfigFlowResult:
        data = {CONF_COOKIES: cookies}
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=data
            )
        await self.async_set_unique_id(ACCOUNT_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=ACCOUNT_TITLE, data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Give new cookies for the account."""
        return await self.async_step_user()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle YouTube rejecting the stored cookies."""
        return await self.async_step_user()

    async def _async_check_cookies(
        self, text: str
    ) -> tuple[str | None, dict[str, str]]:
        """Return the cookies as YouTube left them after reading the feed."""
        try:
            cookies = youtube.parse_cookies(text)
            _, refreshed, _ = await self.hass.async_add_executor_job(
                youtube.fetch_feed, cookies, 5
            )
        except youtube.InvalidCookies:
            return None, {"base": "invalid_cookies"}
        except youtube.SignedOut:
            return None, {"base": "signed_out"}
        except youtube.YouTubeError as err:
            LOGGER.debug("Error reading the home feed: %s", err)
            return None, {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error reading the home feed")
            return None, {"base": "unknown"}
        return refreshed, {}


class AccountOptionsFlow(OptionsFlowWithReload):
    """How often the feed may be read again by itself.

    Saving reloads the account, so the feed sensor shows the new minimum at
    once; the reload starts from the last read, kept in the cache.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the one option."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_MIN_REFRESH: int(user_input[CONF_MIN_REFRESH])}
            )
        current = self.config_entry.options.get(CONF_MIN_REFRESH, DEFAULT_MIN_REFRESH)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MIN_REFRESH, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=10080,
                            step=5,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
