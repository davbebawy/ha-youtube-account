"""Media source: the home feed and Watch Later, under Media in Home Assistant.

An integration can't add to another integration's media browser, so the
feed is a media source of its own and plays to any player. A YouTube on TV
player gets what its play_media takes: a video id, or a list as comma
separated video ids. Any other player gets the youtube.com link.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import youtube
from .const import DOMAIN, MIX_LIMIT, PLAYLIST_LIMIT, TV_PLATFORM
from .coordinator import YouTubeAccountCoordinator, async_get_account

# Opening the media browser reads the feed again if it's older than this
# (raised to the account's minimum time between reads).
FEED_BROWSE_MAX_AGE = timedelta(minutes=15)

FEED = "feed"
WATCH_LATER = "watch_later"
VIDEO = "video"
LIST = "list"
# What a YouTube on TV player takes as media_content_type with each.
TV_VIDEO_TYPE = "video"
TV_LIST_TYPE = "playlist"
# For other players: a youtube.com link.
LINK_MIME_TYPE = "video/youtube"


async def async_get_media_source(hass: HomeAssistant) -> YouTubeAccountMediaSource:
    """Set up the media source."""
    return YouTubeAccountMediaSource(hass)


class YouTubeAccountMediaSource(MediaSource):
    """The signed-in home feed and Watch Later."""

    name = "YouTube"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the source."""
        super().__init__(DOMAIN)
        self.hass = hass

    def _account(self) -> YouTubeAccountCoordinator:
        account = async_get_account(self.hass)
        if account is None:
            raise Unresolvable(translation_domain=DOMAIN, translation_key="no_account")
        return account

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a video or list for the player it plays on."""
        kind, _, media_id = item.identifier.partition("/")
        if kind not in (VIDEO, LIST) or not media_id:
            raise Unresolvable(
                translation_domain=DOMAIN,
                translation_key="invalid_video",
                translation_placeholders={"media_id": item.identifier},
            )
        if not self._is_tv(item.target_media_player):
            if kind == VIDEO:
                return PlayMedia(
                    youtube.WATCH_URL.format(video_id=media_id), LINK_MIME_TYPE
                )
            return PlayMedia(youtube.list_url(media_id), LINK_MIME_TYPE)
        if kind == VIDEO:
            return PlayMedia(media_id, TV_VIDEO_TYPE)
        limit = MIX_LIMIT if media_id.startswith("RD") else PLAYLIST_LIMIT
        videos = await self._account().async_expand(media_id, limit)
        return PlayMedia(",".join(video_id for video_id, _, _ in videos), TV_LIST_TYPE)

    def _is_tv(self, entity_id: str | None) -> bool:
        if entity_id is None:
            return False
        entity = er.async_get(self.hass).async_get(entity_id)
        return entity is not None and entity.platform == TV_PLATFORM

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Show the two lists, or the items of one."""
        account = self._account()
        if item.identifier in (FEED, WATCH_LATER):
            await account.async_refresh_if_older(FEED_BROWSE_MAX_AGE)
        if item.identifier == FEED:
            return self._directory(FEED, "Home feed", self._feed(account))
        if item.identifier == WATCH_LATER:
            return self._directory(
                WATCH_LATER, "Watch Later", self._watch_later(account)
            )
        if item.identifier:
            raise Unresolvable(
                translation_domain=DOMAIN,
                translation_key="invalid_video",
                translation_placeholders={"media_id": item.identifier},
            )
        root = self._directory("", self.name, [])
        root.children = [
            self._directory(FEED, "Home feed", None),
            self._directory(WATCH_LATER, "Watch Later", None),
        ]
        root.children_media_class = MediaClass.DIRECTORY
        return root

    def _directory(
        self,
        identifier: str,
        title: str,
        children: list[BrowseMediaSource] | None,
    ) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.PLAYLIST,
            title=title,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.VIDEO if children is not None else None,
        )

    @staticmethod
    def _feed(account: YouTubeAccountCoordinator) -> list[BrowseMediaSource]:
        return [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{VIDEO if item.kind == 'video' else LIST}/{item.id}",
                media_class=MediaClass.VIDEO
                if item.kind == "video"
                else MediaClass.PLAYLIST,
                media_content_type=MediaType.VIDEO
                if item.kind == "video"
                else MediaType.PLAYLIST,
                title=item.title or item.id,
                can_play=True,
                can_expand=False,
                thumbnail=item.thumbnail,
            )
            for item in account.data.items
        ]

    @staticmethod
    def _watch_later(account: YouTubeAccountCoordinator) -> list[BrowseMediaSource]:
        return [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{VIDEO}/{item.id}",
                media_class=MediaClass.VIDEO,
                media_content_type=MediaType.VIDEO,
                title=item.title or item.id,
                can_play=True,
                can_expand=False,
                thumbnail=youtube.THUMBNAIL_URL.format(video_id=item.id),
            )
            for item in account.data.watch_later or ()
        ]
