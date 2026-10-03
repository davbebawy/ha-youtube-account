"""Actions: play on a TV, refresh the home feed, mark watched, Watch Later."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_ENQUEUE,
    ATTR_MEDIA_EXTRA,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaPlayerEnqueue,
    MediaType,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from . import youtube
from .const import DOMAIN, MIX_LIMIT, PLAYLIST_LIMIT, TV_PLATFORM
from .coordinator import YouTubeAccountCoordinator, async_expand_list, async_get_account

SERVICE_PLAY = "play"
SERVICE_REFRESH_FEED = "refresh_feed"
SERVICE_MARK_WATCHED = "mark_watched"
SERVICE_REMOVE_FROM_WATCH_LATER = "remove_from_watch_later"
SERVICE_ADD_TO_WATCH_LATER = "add_to_watch_later"
ATTR_MEDIA = "media"
ATTR_VIDEO = "video"
ATTR_MAX_AGE = "max_age"
ATTR_VIDEOS = "videos"
ATTR_MIN_PERCENT = "min_percent"
# What a YouTube on TV player takes with a list: the TV's id for it, so a
# Mix keeps going after the videos sent.
EXTRA_LIST_ID = "list_id"

PLAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_MEDIA): cv.string,
        vol.Optional(ATTR_MEDIA_ENQUEUE): vol.Coerce(MediaPlayerEnqueue),
    }
)
REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_MAX_AGE): cv.positive_int})
VIDEO_SCHEMA = vol.Schema({vol.Required(ATTR_VIDEO): cv.string})
REMOVE_FROM_WATCH_LATER_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_VIDEOS): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_MIN_PERCENT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
        }
    ),
    cv.has_at_least_one_key(ATTR_VIDEOS, ATTR_MIN_PERCENT),
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def play(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        _check_tv(hass, entity_id)
        data = await async_play_data(
            hass, call.data[ATTR_MEDIA], call.data.get(ATTR_MEDIA_ENQUEUE)
        )
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_PLAY_MEDIA,
            {ATTR_ENTITY_ID: entity_id, **data},
            blocking=True,
            context=call.context,
        )

    async def refresh_feed(call: ServiceCall) -> None:
        account = _account(hass)
        max_age = call.data.get(ATTR_MAX_AGE)
        await account.async_refresh_if_older(
            timedelta(seconds=max_age) if max_age is not None else None
        )

    async def mark_watched(call: ServiceCall) -> None:
        account = _account(hass)
        await account.async_mark_watched(_video_id(call.data[ATTR_VIDEO]))

    async def add_to_watch_later(call: ServiceCall) -> None:
        account = _account(hass)
        await account.async_add_to_watch_later(_video_id(call.data[ATTR_VIDEO]))

    async def remove_from_watch_later(call: ServiceCall) -> ServiceResponse:
        account = _account(hass)
        video_ids = None
        if ATTR_VIDEOS in call.data:
            video_ids = [_video_id(video) for video in call.data[ATTR_VIDEOS]]
        removed = await account.async_remove_from_watch_later(
            video_ids, call.data.get(ATTR_MIN_PERCENT)
        )
        return {"removed": removed}

    hass.services.async_register(DOMAIN, SERVICE_PLAY, play, PLAY_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH_FEED, refresh_feed, REFRESH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_MARK_WATCHED, mark_watched, VIDEO_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_TO_WATCH_LATER, add_to_watch_later, VIDEO_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_FROM_WATCH_LATER,
        remove_from_watch_later,
        REMOVE_FROM_WATCH_LATER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def async_play_data(
    hass: HomeAssistant, media: str, enqueue: MediaPlayerEnqueue | None
) -> dict[str, Any]:
    """Return the play_media data for a video, Mix or playlist id or link.

    A list is sent as its first videos (25 of a Mix, 50 of a playlist), read
    signed in when the account is set up, so a Mix is the account's own and
    Watch Later opens. A Mix also carries its id, so the TV keeps it going.
    """
    data: dict[str, Any] = {}
    if enqueue is not None:
        data[ATTR_MEDIA_ENQUEUE] = enqueue
    if (list_id := youtube.parse_list_id(media)) is not None:
        mix = list_id.startswith("RD")
        limit = MIX_LIMIT if mix else PLAYLIST_LIMIT
        account = async_get_account(hass)
        if account is not None:
            videos = await account.async_expand(list_id, limit)
        else:
            videos = await async_expand_list(hass, list_id, None, limit)
        data[ATTR_MEDIA_CONTENT_TYPE] = MediaType.PLAYLIST
        data[ATTR_MEDIA_CONTENT_ID] = ",".join(video_id for video_id, _, _ in videos)
        if mix:
            data[ATTR_MEDIA_EXTRA] = {EXTRA_LIST_ID: list_id}
        return data
    data[ATTR_MEDIA_CONTENT_TYPE] = MediaType.VIDEO
    data[ATTR_MEDIA_CONTENT_ID] = _video_id(media)
    return data


def _video_id(media: str) -> str:
    """Return the video id of an id or link, or reject it."""
    video_id = youtube.parse_video_id(media)
    if video_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_video",
            translation_placeholders={"media_id": media},
        )
    return video_id


def _check_tv(hass: HomeAssistant, entity_id: str) -> None:
    """Reject anything but a YouTube on TV media player."""
    entity = er.async_get(hass).async_get(entity_id)
    if (
        entity is None
        or entity.platform != TV_PLATFORM
        or entity.domain != MEDIA_PLAYER_DOMAIN
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_tv",
            translation_placeholders={"entity_id": entity_id},
        )


def _account(hass: HomeAssistant) -> YouTubeAccountCoordinator:
    """Return the YouTube account, or tell the caller to add one."""
    account = async_get_account(hass)
    if account is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_account"
        )
    return account
