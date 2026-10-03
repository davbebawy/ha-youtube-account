"""The YouTube account: home feed, Watch Later, and Mixes and playlists to play."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from . import youtube
from .const import (
    ACCOUNT_UNIQUE_ID,
    CONF_COOKIES,
    CONF_MIN_REFRESH,
    DEFAULT_MIN_REFRESH,
    DOMAIN,
    FEED_LIMIT,
    LOGGER,
)
from .youtube import FeedItem, WatchLaterItem

if TYPE_CHECKING:
    from . import YouTubeAccountConfigEntry


# The last read, kept on disk so a restart need not read YouTube again.
CACHE_VERSION = 1


def cache_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the store that keeps an account's last feed read."""
    return Store(hass, CACHE_VERSION, f"{DOMAIN}.feed_cache.{entry_id}", private=True)


@callback
def async_get_account(hass: HomeAssistant) -> YouTubeAccountCoordinator | None:
    """Return the loaded account, if one is set up."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    return None


@dataclass(frozen=True, slots=True)
class FeedState:
    """The home feed as last read."""

    items: tuple[FeedItem, ...] = ()
    updated_at: datetime | None = None
    shorts_hidden: int = 0
    # None until Watch Later was read once; a failed read keeps the last list.
    watch_later: tuple[WatchLaterItem, ...] | None = None


class YouTubeAccountCoordinator(DataUpdateCoordinator[FeedState]):
    """Reads the home feed when asked; never on a timer."""

    config_entry: YouTubeAccountConfigEntry

    def __init__(self, hass: HomeAssistant, entry: YouTubeAccountConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
            always_update=False,
        )
        self.signed_in = True
        # Videos marked watched here; later reads leave them out too, in case
        # YouTube keeps them in the feed for a while.
        self._watched: set[str] = set()
        self._cache = cache_store(hass, entry.entry_id)
        self.async_add_listener(self._save_cache)

    async def async_load_cache(self) -> bool:
        """Start from the last read on disk; True when it is new enough.

        "New enough" is the min_refresh option, so a restart reads YouTube
        only when the feed card would have.
        """
        stored = await self._cache.async_load()
        if not stored:
            return False
        try:
            state = FeedState(
                items=tuple(FeedItem(**i) for i in stored["items"]),
                updated_at=dt_util.parse_datetime(stored["updated_at"]),
                shorts_hidden=stored.get("shorts_hidden", 0),
                watch_later=None
                if stored.get("watch_later") is None
                else tuple(WatchLaterItem(**i) for i in stored["watch_later"]),
            )
        except KeyError, TypeError, ValueError:
            # Written by another version: read YouTube instead.
            return False
        if (
            state.updated_at is None
            or dt_util.utcnow() - state.updated_at >= self.min_refresh
        ):
            return False
        self.async_set_updated_data(state)
        return True

    def _cache_data(self) -> dict[str, Any] | None:
        data = self.data
        if data is None or data.updated_at is None:
            return None
        return {
            "items": [asdict(i) for i in data.items],
            "updated_at": data.updated_at.isoformat(),
            "shorts_hidden": data.shorts_hidden,
            "watch_later": None
            if data.watch_later is None
            else [asdict(i) for i in data.watch_later],
        }

    @callback
    def _save_cache(self) -> None:
        if self.data is not None and self.data.updated_at is not None:
            self._cache.async_delay_save(lambda: self._cache_data() or {}, 1)

    async def async_shutdown(self) -> None:
        """Write the last read now, so a reload (an options change) starts from it."""
        await super().async_shutdown()
        if (data := self._cache_data()) is not None:
            await self._cache.async_save(data)

    @property
    def cookies(self) -> str:
        """Return the account's cookies.txt."""
        return self.config_entry.data[CONF_COOKIES]

    async def _async_update_data(self) -> FeedState:
        try:
            items, refreshed, shorts = await self.hass.async_add_executor_job(
                youtube.fetch_feed, self.cookies, FEED_LIMIT
            )
        except youtube.SignedOut as err:
            self._set_signed_in(False)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="signed_out"
            ) from err
        except youtube.YouTubeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="feed_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        watch_later = self.data.watch_later if self.data else None
        try:
            later, refreshed = await self.hass.async_add_executor_job(
                youtube.fetch_watch_later, refreshed
            )
            watch_later = tuple(later)
        except youtube.YouTubeError as err:
            LOGGER.warning("Error reading Watch Later: %s", err)
        self._set_signed_in(True)
        self._store_cookies(refreshed)
        return FeedState(self._unwatched(items), dt_util.utcnow(), shorts, watch_later)

    @callback
    def _store_cookies(self, refreshed: str) -> None:
        if refreshed != self.cookies:
            # YouTube refreshes some cookies on each visit; keeping them makes
            # the session last longer.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_COOKIES: refreshed},
            )

    def _unwatched(self, items: Iterable[FeedItem]) -> tuple[FeedItem, ...]:
        return tuple(
            item
            for item in items
            if item.kind != "video" or item.id not in self._watched
        )

    async def async_mark_watched(self, video_id: str) -> None:
        """Mark a video watched on the account and drop it from the feed."""
        try:
            refreshed = await self.hass.async_add_executor_job(
                youtube.mark_watched, self.cookies, video_id
            )
        except youtube.SignedOut as err:
            self._set_signed_in(False)
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="signed_out"
            ) from err
        except youtube.YouTubeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="mark_watched_failed",
                translation_placeholders={"video_id": video_id, "error": str(err)},
            ) from err
        self._set_signed_in(True)
        self._store_cookies(refreshed)
        self._watched.add(video_id)
        if self.data is not None:
            self.async_set_updated_data(
                replace(self.data, items=self._unwatched(self.data.items))
            )

    async def async_add_to_watch_later(self, video_id: str) -> None:
        """Save a video to Watch Later on the account."""
        try:
            items, refreshed = await self.hass.async_add_executor_job(
                youtube.add_to_watch_later, self.cookies, video_id
            )
        except youtube.SignedOut as err:
            self._set_signed_in(False)
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="signed_out"
            ) from err
        except youtube.YouTubeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="watch_later_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._set_signed_in(True)
        self._store_cookies(refreshed)
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, watch_later=tuple(items)))

    async def async_remove_from_watch_later(
        self, video_ids: list[str] | None, min_percent: int | None
    ) -> list[str]:
        """Remove videos from Watch Later on the account; return the ids removed.

        video_ids names them; min_percent picks every video in the last read
        list watched that far or more.
        """
        if video_ids is None:
            listed = self.data.watch_later if self.data else None
            if listed is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="watch_later_unread"
                )
            video_ids = [i.id for i in listed if i.percent >= (min_percent or 0)]
        if not video_ids:
            return []
        try:
            removed, refreshed = await self.hass.async_add_executor_job(
                youtube.remove_from_watch_later, self.cookies, video_ids
            )
        except youtube.SignedOut as err:
            self._set_signed_in(False)
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="signed_out"
            ) from err
        except youtube.YouTubeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="watch_later_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._set_signed_in(True)
        self._store_cookies(refreshed)
        if self.data is not None and self.data.watch_later is not None:
            gone = set(removed)
            self.async_set_updated_data(
                replace(
                    self.data,
                    watch_later=tuple(
                        i for i in self.data.watch_later if i.id not in gone
                    ),
                )
            )
        return removed

    @callback
    def _set_signed_in(self, signed_in: bool) -> None:
        if signed_in != self.signed_in:
            self.signed_in = signed_in
            self.async_update_listeners()

    @property
    def min_refresh(self) -> timedelta:
        """Return the shortest time between automatic reads (an option)."""
        minutes = self.config_entry.options.get(CONF_MIN_REFRESH, DEFAULT_MIN_REFRESH)
        return timedelta(minutes=minutes)

    async def async_refresh_if_older(self, max_age: timedelta | None) -> None:
        """Read the feed again if it's older than max_age, or always if None.

        A max_age shorter than the min_refresh option is raised to it, so a
        card that opens often does not read the feed each time.
        """
        if max_age is not None:
            max_age = max(max_age, self.min_refresh)
        updated_at = self.data.updated_at if self.data else None
        if (
            max_age is None
            or updated_at is None
            or dt_util.utcnow() - updated_at >= max_age
        ):
            await self.async_refresh()

    async def async_expand(
        self, list_id: str, limit: int
    ) -> list[tuple[str, str | None, str | None]]:
        """Return the first videos of a Mix or playlist, signed in."""
        return await async_expand_list(self.hass, list_id, self.cookies, limit)


async def async_expand_list(
    hass: HomeAssistant, list_id: str, cookies: str | None, limit: int
) -> list[tuple[str, str | None, str | None]]:
    """Return the first videos of a Mix or playlist as (id, title, channel)."""
    try:
        return await hass.async_add_executor_job(
            youtube.expand_list, list_id, cookies, limit
        )
    except youtube.YouTubeError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="list_failed",
            translation_placeholders={"list_id": list_id, "error": str(err)},
        ) from err


class YouTubeAccountEntity(CoordinatorEntity[YouTubeAccountCoordinator]):
    """Entity of the YouTube account device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: YouTubeAccountCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{ACCOUNT_UNIQUE_ID}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ACCOUNT_UNIQUE_ID)},
            translation_key="account",
            entry_type=DeviceEntryType.SERVICE,
        )
