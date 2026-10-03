"""Tests for the media source: the feed and Watch Later under Media."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.youtube_account.const import DOMAIN
from homeassistant.components import media_source
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import REFRESHED, A, B, C

TV = "media_player.youtube_on_tv"
OTHER = "media_player.kitchen_speaker"
ROOT = f"media-source://{DOMAIN}"


@pytest.fixture
async def source(hass: HomeAssistant, init_account: MockConfigEntry) -> None:
    """Set up the media source with the account."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player", "youtube_on_tv", "screen1", suggested_object_id="youtube_on_tv"
    )
    registry.async_get_or_create(
        "media_player", "cast", "speaker1", suggested_object_id="kitchen_speaker"
    )
    assert await async_setup_component(hass, "media_source", {})
    await hass.async_block_till_done()


async def test_browse(hass: HomeAssistant, source: None) -> None:
    root = await media_source.async_browse_media(hass, ROOT)
    assert [c.title for c in root.children] == ["Home feed", "Watch Later"]

    feed = await media_source.async_browse_media(hass, f"{ROOT}/feed")
    assert [(c.media_content_id, c.media_class) for c in feed.children] == [
        (f"{ROOT}/video/OmmaHKzxtVw", "video"),
        (f"{ROOT}/list/RDqyUPz6_TciY", "playlist"),
    ]
    assert all(c.can_play for c in feed.children)

    later = await media_source.async_browse_media(hass, f"{ROOT}/watch_later")
    assert [c.media_content_id for c in later.children] == [
        f"{ROOT}/video/{A}",
        f"{ROOT}/video/{B}",
        f"{ROOT}/video/{C}",
    ]
    assert later.children[0].thumbnail == f"https://i.ytimg.com/vi/{A}/hqdefault.jpg"


async def test_resolve_for_the_tv(
    hass: HomeAssistant, source: None, mock_expand: MagicMock
) -> None:
    video = await media_source.async_resolve_media(
        hass, f"{ROOT}/video/OmmaHKzxtVw", TV
    )
    assert (video.url, video.mime_type) == ("OmmaHKzxtVw", "video")

    mix = await media_source.async_resolve_media(hass, f"{ROOT}/list/RDqyUPz6_TciY", TV)
    mock_expand.assert_called_once_with("RDqyUPz6_TciY", REFRESHED, 25)
    assert (mix.url, mix.mime_type) == (f"{A},{C}", "playlist")


async def test_resolve_for_another_player(
    hass: HomeAssistant, source: None, mock_expand: MagicMock
) -> None:
    video = await media_source.async_resolve_media(
        hass, f"{ROOT}/video/OmmaHKzxtVw", OTHER
    )
    assert video.url == "https://www.youtube.com/watch?v=OmmaHKzxtVw"
    mix = await media_source.async_resolve_media(
        hass, f"{ROOT}/list/RDqyUPz6_TciY", OTHER
    )
    assert mix.url == ("https://www.youtube.com/watch?v=qyUPz6_TciY&list=RDqyUPz6_TciY")
    mock_expand.assert_not_called()


async def test_resolve_unknown(hass: HomeAssistant, source: None) -> None:
    with pytest.raises(media_source.Unresolvable):
        await media_source.async_resolve_media(hass, f"{ROOT}/channel/x", TV)
