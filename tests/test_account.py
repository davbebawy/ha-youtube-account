"""Tests for the YouTube account: sign-in, home feed, Watch Later."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
import voluptuous as vol

from custom_components.youtube_account import youtube
from custom_components.youtube_account.const import (
    ACCOUNT_UNIQUE_ID,
    CONF_COOKIES,
    CONF_COOKIES_FILE,
    DOMAIN,
)
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .conftest import (
    COOKIES,
    FEED,
    HEADER,
    REFRESHED,
    WATCH_LATER,
    A,
    B,
    C,
)

FEED_ID = "sensor.youtube_account_home_feed"
SIGNED_IN_ID = "binary_sensor.youtube_account_signed_in"
REFRESH_ID = "button.youtube_account_refresh_home_feed"
WATCH_LATER_ID = "sensor.youtube_account_watch_later"


@pytest.fixture(autouse=True)
def _watch_later(mock_watch_later: MagicMock) -> None:
    """Every account read here reads Watch Later too."""


# Config flow


async def test_account_flow(hass: HomeAssistant, mock_fetch: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "no_cookies"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES: "not cookies"}
    )
    assert result["errors"] == {"base": "invalid_cookies"}

    mock_fetch.side_effect = youtube.SignedOut
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES: HEADER}
    )
    assert result["errors"] == {"base": "signed_out"}

    mock_fetch.side_effect = youtube.YouTubeError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES: HEADER}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_fetch.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES: f"cookie: {HEADER}"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "YouTube account"
    assert result["data"] == {CONF_COOKIES: REFRESHED}
    assert result["result"].unique_id == ACCOUNT_UNIQUE_ID


async def test_account_flow_from_file(
    hass: HomeAssistant, mock_fetch: MagicMock, tmp_path: Path
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES_FILE: str(tmp_path / "missing.txt")}
    )
    assert result["errors"] == {CONF_COOKIES_FILE: "file_unreadable"}

    # A fake cookies.txt export, only the names a signed-in one has.
    file = tmp_path / "cookies.txt"
    file.write_text(COOKIES, encoding="utf-8")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES_FILE: str(file)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_COOKIES: REFRESHED}
    # The path is not kept.
    assert CONF_COOKIES_FILE not in result["data"]
    # The form checks the file's cookies; the new entry then reads the feed.
    assert mock_fetch.call_args_list[0].args == (COOKIES, 5)


async def test_account_flow_once(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_account(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    result = await init_account.start_reconfigure_flow(hass)
    assert result["step_id"] == "user"
    mock_fetch.return_value = (list(FEED), COOKIES + "# new\n", 0)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COOKIES: HEADER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_account.data[CONF_COOKIES] == COOKIES + "# new\n"


# Feed


async def test_entity_ids_and_device(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    # The same ids the account had inside YouTube on TV, so dashboards and
    # automations keep working after the move.
    for entity_id in (FEED_ID, WATCH_LATER_ID, SIGNED_IN_ID, REFRESH_ID):
        assert hass.states.get(entity_id) is not None, entity_id
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ACCOUNT_UNIQUE_ID), init_account.entry_id
    )
    assert device.name == "YouTube account"


async def test_feed_entities(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    state = hass.states.get(FEED_ID)
    assert state.state == "2"
    items = state.attributes["items"]
    assert [i["id"] for i in items] == ["OmmaHKzxtVw", "RDqyUPz6_TciY"]
    assert items[1]["url"].endswith("watch?v=qyUPz6_TciY&list=RDqyUPz6_TciY")
    assert state.attributes["shorts_hidden"] == 1
    assert state.attributes["min_refresh_minutes"] == 15
    assert hass.states.get(SIGNED_IN_ID).state == "on"
    # YouTube's refreshed cookies are kept.
    assert init_account.data[CONF_COOKIES] == REFRESHED
    mock_fetch.assert_called_once_with(COOKIES, 30)

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: REFRESH_ID}, blocking=True
    )
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 2
    assert mock_fetch.call_args.args == (REFRESHED, 30)


async def test_refresh_feed_max_age(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    mock_fetch: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await hass.services.async_call(
        DOMAIN, "refresh_feed", {"max_age": 900}, blocking=True
    )
    assert mock_fetch.call_count == 1
    freezer.tick(901)
    await hass.services.async_call(
        DOMAIN, "refresh_feed", {"max_age": 900}, blocking=True
    )
    assert mock_fetch.call_count == 2
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    assert mock_fetch.call_count == 3


async def test_min_refresh_option(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    mock_fetch: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    result = await hass.config_entries.options.async_init(init_account.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"min_refresh_minutes": 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_account.options == {"min_refresh_minutes": 120}
    await hass.async_block_till_done()
    assert hass.states.get(FEED_ID).attributes["min_refresh_minutes"] == 120
    await hass.services.async_call(
        DOMAIN, "refresh_feed", {"max_age": 900}, blocking=True
    )
    assert mock_fetch.call_count == 1
    # The card asks after 15 minutes; the option holds it off to 2 hours.
    freezer.tick(901)
    await hass.services.async_call(
        DOMAIN, "refresh_feed", {"max_age": 900}, blocking=True
    )
    assert mock_fetch.call_count == 1
    freezer.tick(7200)
    await hass.services.async_call(
        DOMAIN, "refresh_feed", {"max_age": 900}, blocking=True
    )
    assert mock_fetch.call_count == 2
    # Refresh always reads.
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    assert mock_fetch.call_count == 3


async def test_restart_uses_fresh_cache(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    mock_fetch: MagicMock,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict,
) -> None:
    assert mock_fetch.call_count == 1
    freezer.tick(2)  # past the delayed save
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert f"youtube_account.feed_cache.{init_account.entry_id}" in hass_storage
    # A reload stands in for a restart: the read on disk is 10 minutes old.
    freezer.tick(600)
    assert await hass.config_entries.async_reload(init_account.entry_id)
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 1
    assert hass.states.get(FEED_ID).state == "2"
    assert hass.states.get(WATCH_LATER_ID).state == "3"
    # Older than the 15 minute default: the start reads YouTube.
    freezer.tick(600)
    assert await hass.config_entries.async_reload(init_account.entry_id)
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 2


async def test_cache_removed_with_account(
    hass: HomeAssistant, init_account: MockConfigEntry, hass_storage: dict
) -> None:
    await hass.config_entries.async_remove(init_account.entry_id)
    await hass.async_block_till_done()
    assert f"youtube_account.feed_cache.{init_account.entry_id}" not in hass_storage


async def test_actions_without_account(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "mark_watched", {"video": "OmmaHKzxtVw"}, blocking=True
        )


async def test_signed_out_starts_reauth(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    mock_fetch.side_effect = youtube.SignedOut
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(SIGNED_IN_ID).state == "off"
    assert hass.states.get(REFRESH_ID).state != "unavailable"
    flows = hass.config_entries.flow.async_progress()
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [
        ("reauth", "user")
    ]

    mock_fetch.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_COOKIES: HEADER}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert init_account.state is ConfigEntryState.LOADED
    assert hass.states.get(SIGNED_IN_ID).state == "on"


async def test_signed_out_at_setup(
    hass: HomeAssistant, account_entry: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    mock_fetch.side_effect = youtube.SignedOut
    account_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()
    assert account_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        f["context"]["source"] == "reauth"
        for f in hass.config_entries.flow.async_progress()
    )


async def test_feed_error_keeps_last_items(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    mock_fetch.side_effect = youtube.YouTubeError("down")
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(FEED_ID).state == "unavailable"
    assert hass.states.get(SIGNED_IN_ID).state == "on"


async def test_mark_watched(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    with patch.object(youtube, "mark_watched", return_value=REFRESHED + "#2\n") as mark:
        await hass.services.async_call(
            DOMAIN,
            "mark_watched",
            {"video": "https://youtu.be/OmmaHKzxtVw?si=x"},
            blocking=True,
        )
    mark.assert_called_once_with(REFRESHED, "OmmaHKzxtVw")
    assert init_account.data[CONF_COOKIES] == REFRESHED + "#2\n"
    state = hass.states.get(FEED_ID)
    assert [i["id"] for i in state.attributes["items"]] == ["RDqyUPz6_TciY"]

    # A later read that still has it leaves it out.
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    await hass.async_block_till_done()
    assert mock_fetch.call_count == 2
    assert hass.states.get(FEED_ID).state == "1"


async def test_mark_watched_errors(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "mark_watched", {"video": "not a video"}, blocking=True
        )
    with (
        patch.object(youtube, "mark_watched", side_effect=youtube.YouTubeError("x")),
        pytest.raises(HomeAssistantError, match="Failed to mark OmmaHKzxtVw"),
    ):
        await hass.services.async_call(
            DOMAIN, "mark_watched", {"video": "OmmaHKzxtVw"}, blocking=True
        )
    assert hass.states.get(FEED_ID).state == "2"
    with (
        patch.object(youtube, "mark_watched", side_effect=youtube.SignedOut),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            DOMAIN, "mark_watched", {"video": "OmmaHKzxtVw"}, blocking=True
        )
    await hass.async_block_till_done()
    assert hass.states.get(SIGNED_IN_ID).state == "off"
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_watch_later_sensor(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    state = hass.states.get(WATCH_LATER_ID)
    assert state.state == "3"
    assert [(i["id"], i["percent"]) for i in state.attributes["items"]] == [
        (A, 100),
        (B, 50),
        (C, 92),
    ]


async def test_watch_later_error_keeps_feed(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_watch_later: MagicMock
) -> None:
    mock_watch_later.side_effect = youtube.YouTubeError("x")
    await hass.services.async_call(DOMAIN, "refresh_feed", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(FEED_ID).state == "2"
    assert hass.states.get(WATCH_LATER_ID).state == "3"


async def test_remove_from_watch_later_by_percent(
    hass: HomeAssistant, init_account: MockConfigEntry, mock_fetch: MagicMock
) -> None:
    with patch.object(
        youtube, "remove_from_watch_later", return_value=([A, C], REFRESHED + "#2\n")
    ) as remove:
        result = await hass.services.async_call(
            DOMAIN,
            "remove_from_watch_later",
            {"min_percent": 90},
            blocking=True,
            return_response=True,
        )
    remove.assert_called_once_with(REFRESHED, [A, C])
    assert result == {"removed": [A, C]}
    assert init_account.data[CONF_COOKIES] == REFRESHED + "#2\n"
    state = hass.states.get(WATCH_LATER_ID)
    assert state.state == "1"
    assert [i["id"] for i in state.attributes["items"]] == [B]


async def test_remove_from_watch_later_by_id(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    with patch.object(
        youtube, "remove_from_watch_later", return_value=([B], REFRESHED)
    ) as remove:
        await hass.services.async_call(
            DOMAIN,
            "remove_from_watch_later",
            {"videos": [f"https://youtu.be/{B}"]},
            blocking=True,
        )
    remove.assert_called_once_with(REFRESHED, [B])
    assert hass.states.get(WATCH_LATER_ID).state == "2"


async def test_add_to_watch_later(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    new = youtube.WatchLaterItem("OmmaHKzxtVw", "Groceries", "Chan", 511, 0, "sN")
    with patch.object(
        youtube,
        "add_to_watch_later",
        return_value=([new, *WATCH_LATER], REFRESHED),
    ) as add:
        await hass.services.async_call(
            DOMAIN,
            "add_to_watch_later",
            {"video": "https://youtu.be/OmmaHKzxtVw"},
            blocking=True,
        )
    add.assert_called_once_with(REFRESHED, "OmmaHKzxtVw")
    state = hass.states.get(WATCH_LATER_ID)
    assert state.state == "4"
    assert state.attributes["items"][0]["id"] == "OmmaHKzxtVw"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_to_watch_later", {"video": "nope"}, blocking=True
        )


async def test_remove_from_watch_later_errors(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "remove_from_watch_later", {}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "remove_from_watch_later", {"videos": ["nope"]}, blocking=True
        )
    with (
        patch.object(
            youtube, "remove_from_watch_later", side_effect=youtube.YouTubeError("x")
        ),
        pytest.raises(HomeAssistantError, match="Failed to change Watch Later"),
    ):
        await hass.services.async_call(
            DOMAIN, "remove_from_watch_later", {"min_percent": 90}, blocking=True
        )
    assert hass.states.get(WATCH_LATER_ID).state == "3"


async def test_account_diagnostics_redact(
    hass: HomeAssistant, init_account: MockConfigEntry
) -> None:
    from custom_components.youtube_account.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    result = await async_get_config_entry_diagnostics(hass, init_account)
    assert result["entry"]["data"][CONF_COOKIES] == "**REDACTED**"
    assert result["feed_items"] == 2
    assert result["watch_later_items"] == 3
