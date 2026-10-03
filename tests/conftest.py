"""Fixtures for YouTube Account tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.youtube_account import youtube
from custom_components.youtube_account.const import (
    ACCOUNT_UNIQUE_ID,
    CONF_COOKIES,
    DOMAIN,
)
from custom_components.youtube_account.youtube import FeedItem
from homeassistant.core import HomeAssistant

# Fake values: the names a signed-in cookie header has, nothing real.
HEADER = "SID=s; SAPISID=sap; LOGIN_INFO=li"
COOKIES = youtube.parse_cookies(HEADER)
REFRESHED = COOKIES + "# refreshed\n"
FEED = [
    FeedItem("video", "OmmaHKzxtVw", "Groceries", "Internet Shaquille", 511),
    FeedItem(
        "mix", "RDqyUPz6_TciY", "Mix - Though You Slay Me", video_id="qyUPz6_TciY"
    ),
]
A, B, C = "aqz-KE-bpKQ", "eRsGyueVLvQ", "R6MlUcmOul8"
WATCH_LATER = [
    youtube.WatchLaterItem(A, "Done", "Chan", 600, 100, "sA"),
    youtube.WatchLaterItem(B, "Half", "Chan", 600, 50, "sB"),
    youtube.WatchLaterItem(C, "Most", "Chan", 600, 92, "sC"),
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_watch_later() -> Generator[MagicMock]:
    """Patch reading Watch Later; keeps the cookies it is given."""
    with patch.object(
        youtube,
        "fetch_watch_later",
        side_effect=lambda cookies: (list(WATCH_LATER), cookies),
    ) as mock:
        yield mock


@pytest.fixture
def mock_fetch() -> Generator[MagicMock]:
    """Patch reading the feed; returns two items and refreshed cookies."""
    with patch.object(
        youtube, "fetch_feed", return_value=(list(FEED), REFRESHED, 1)
    ) as mock:
        yield mock


@pytest.fixture
def mock_expand() -> Generator[MagicMock]:
    """Patch reading a list's videos."""
    with patch.object(
        youtube,
        "expand_list",
        return_value=[(A, "Video A", "Chan"), (C, "Video C", None)],
    ) as mock:
        yield mock


@pytest.fixture
def account_entry() -> MockConfigEntry:
    """Return the YouTube account entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="YouTube account",
        unique_id=ACCOUNT_UNIQUE_ID,
        data={CONF_COOKIES: COOKIES},
    )


@pytest.fixture
async def init_account(
    hass: HomeAssistant,
    account_entry: MockConfigEntry,
    mock_fetch: MagicMock,
    mock_watch_later: MagicMock,
) -> MockConfigEntry:
    """Set up the account."""
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()
    return account_entry
