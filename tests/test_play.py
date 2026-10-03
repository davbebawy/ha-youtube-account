"""Tests for youtube_account.play: it only calls media_player.play_media."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
import voluptuous as vol

from custom_components.youtube_account.const import DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import REFRESHED, A, C

TV = "media_player.youtube_on_tv"
OTHER = "media_player.kitchen_speaker"
PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"


@pytest.fixture
def players(hass: HomeAssistant) -> None:
    """Register a YouTube on TV player and a player of another integration."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player", "youtube_on_tv", "screen1", suggested_object_id="youtube_on_tv"
    )
    registry.async_get_or_create(
        "media_player", "cast", "speaker1", suggested_object_id="kitchen_speaker"
    )


@pytest.fixture
def play_media(hass: HomeAssistant) -> list[ServiceCall]:
    """Stand in for the TV's play_media; the account never talks to the TV."""
    return async_mock_service(hass, "media_player", "play_media")


async def _play(hass: HomeAssistant, media: str, **data) -> None:
    await hass.services.async_call(
        DOMAIN, "play", {"entity_id": TV, "media": media, **data}, blocking=True
    )


@pytest.mark.parametrize("media", ["OmmaHKzxtVw", "https://youtu.be/OmmaHKzxtVw?si=x"])
async def test_play_video(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    players: None,
    play_media: list[ServiceCall],
    media: str,
) -> None:
    await _play(hass, media, enqueue="next")
    assert len(play_media) == 1
    assert play_media[0].data == {
        "entity_id": TV,
        "media_content_type": "video",
        "media_content_id": "OmmaHKzxtVw",
        "enqueue": "next",
    }


async def test_play_mix(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    players: None,
    play_media: list[ServiceCall],
    mock_expand: MagicMock,
) -> None:
    await _play(hass, "RDqyUPz6_TciY")
    # Signed in, so the Mix is the account's own.
    mock_expand.assert_called_once_with("RDqyUPz6_TciY", REFRESHED, 25)
    assert play_media[0].data == {
        "entity_id": TV,
        "media_content_type": "playlist",
        "media_content_id": f"{A},{C}",
        "extra": {"list_id": "RDqyUPz6_TciY"},
    }


@pytest.mark.parametrize("enqueue", ["add", "next", "replace", "play"])
async def test_queue_playlist(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    players: None,
    play_media: list[ServiceCall],
    mock_expand: MagicMock,
    enqueue: str,
) -> None:
    await _play(
        hass, f"https://www.youtube.com/playlist?list={PLAYLIST}", enqueue=enqueue
    )
    mock_expand.assert_called_once_with(PLAYLIST, REFRESHED, 50)
    # A playlist carries no list id: only a Mix needs the TV to go on.
    assert play_media[0].data == {
        "entity_id": TV,
        "media_content_type": "playlist",
        "media_content_id": f"{A},{C}",
        "enqueue": enqueue,
    }


async def test_play_playlist_without_account(
    hass: HomeAssistant,
    players: None,
    mock_expand: MagicMock,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    calls = async_mock_service(hass, "media_player", "play_media")
    await _play(hass, PLAYLIST)
    mock_expand.assert_called_once_with(PLAYLIST, None, 50)
    assert calls[0].data["media_content_id"] == f"{A},{C}"


async def test_video_link_in_list_is_the_video(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    players: None,
    play_media: list[ServiceCall],
    mock_expand: MagicMock,
) -> None:
    await _play(hass, f"https://www.youtube.com/watch?v={A}&list=RDqyUPz6_TciY")
    mock_expand.assert_not_called()
    assert play_media[0].data["media_content_id"] == A


async def test_play_rejects(
    hass: HomeAssistant,
    init_account: MockConfigEntry,
    players: None,
    play_media: list[ServiceCall],
) -> None:
    with pytest.raises(ServiceValidationError, match="not a YouTube on TV"):
        await hass.services.async_call(
            DOMAIN, "play", {"entity_id": OTHER, "media": A}, blocking=True
        )
    with pytest.raises(ServiceValidationError, match="not a YouTube on TV"):
        await hass.services.async_call(
            DOMAIN,
            "play",
            {"entity_id": "media_player.nowhere", "media": A},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError, match="not a YouTube video"):
        await _play(hass, "https://example.com/watch?v=OmmaHKzxtVw")
    with pytest.raises(vol.Invalid):
        await _play(hass, A, enqueue="later")
    assert play_media == []
