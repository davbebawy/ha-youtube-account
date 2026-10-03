"""The signed-in home feed, Watch Later, Mixes and playlists.

YouTube's Data API has no home feed, and yt-dlp's OAuth login no longer
works, so these are read the way youtube.com reads them, with the account's
browser cookies. The home feed and Watch Later come from their pages'
data (yt-dlp's entries drop views, age and watched percent); lists and
mark watched go through yt-dlp. Everything here that reads YouTube blocks:
run it in the executor.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

HOME_URL = "https://www.youtube.com/"
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

# yt-dlp counts an account as signed in when LOGIN_INFO and one of these are
# set; YouTube clears LOGIN_INFO when it rotates the session away.
_LOGIN_COOKIE = "LOGIN_INFO"
_SID_COOKIES = ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID")
_ROTATED_WARNING = "cookies are no longer valid"
# yt-dlp only warns when it can't mark a video watched.
_MARK_FAILED_WARNING = "Unable to mark"
# A copied request header carries no expiry; YouTube ends the session, not
# this date.
_HEADER_COOKIE_LIFETIME = 400 * 86400

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

WATCH_LATER_URL = "https://www.youtube.com/playlist?list=WL"
_ORIGIN = "https://www.youtube.com"
# The playlist page holds 100 videos; each continuation adds 100.
_WATCH_LATER_PAGES = 50
# Home feed pages read at most; each continuation adds about 30 tiles.
_FEED_PAGES = 3
# Remove actions sent per edit_playlist request.
_REMOVE_CHUNK = 50


class YouTubeError(Exception):
    """YouTube could not be read."""


class InvalidCookies(YouTubeError):
    """The text is not a signed-in youtube.com cookie header or file."""


class SignedOut(YouTubeError):
    """YouTube no longer accepts the account's cookies."""


@dataclass(frozen=True, slots=True)
class FeedItem:
    """One entry of the home feed.

    kind is "video", "mix" or "playlist". A Mix is an endless list YouTube
    builds from one video, its seed; id is the video id for a video and the
    list id otherwise.
    """

    kind: str
    id: str
    title: str | None
    channel: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    video_id: str | None = None
    live: bool = False
    # "1.5M views \u2022 1d ago" (a bullet), as youtube.com shows it after the channel.
    details: str | None = None
    # The red bar under the thumbnail: how much was watched, 0 to 100.
    percent: int = 0

    @property
    def url(self) -> str:
        """Return the item's youtube.com link."""
        if self.kind == "video":
            return f"https://www.youtube.com/watch?v={self.id}"
        return list_url(self.id, self.video_id)

    def as_dict(self) -> dict[str, Any]:
        """Return the item for a state attribute."""
        return {**asdict(self), "url": self.url}


@dataclass(frozen=True, slots=True)
class WatchLaterItem:
    """One Watch Later video and how much of it the account has watched.

    percent is YouTube's red bar: 0 when the video has no progress. set_id is
    the entry's id in the list, which the remove call needs.
    """

    id: str
    title: str | None
    channel: str | None
    duration: int | None
    percent: int
    set_id: str | None
    details: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the item for a state attribute."""
        return {
            "id": self.id,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "percent": self.percent,
            "details": self.details,
            "thumbnail": THUMBNAIL_URL.format(video_id=self.id),
            "url": WATCH_URL.format(video_id=self.id),
        }


def mix_seed(list_id: str) -> str | None:
    """Return the video a Mix id was built from, if the id carries it."""
    if list_id.startswith("RD") and _VIDEO_ID_RE.match(list_id[2:]):
        return list_id[2:]
    return None


def list_url(list_id: str, seed: str | None = None) -> str:
    """Return the link that opens a list.

    A Mix only opens from a watch page; its playlist page says "This playlist
    type is unviewable".
    """
    seed = seed or mix_seed(list_id)
    if seed:
        return f"https://www.youtube.com/watch?v={seed}&list={list_id}"
    return f"https://www.youtube.com/playlist?list={list_id}"


def parse_cookies(text: str) -> str:
    """Return a Netscape cookies.txt for a pasted header value or file.

    Accepts the value of a "cookie" request header (DevTools > Network), with
    or without the "cookie:" prefix, or a whole cookies.txt export.
    """
    text = text.strip()
    cookies: list[tuple[str, ...]] = []
    if "\t" in text:
        for line in text.splitlines():
            fields = line.strip("\r").split("\t")
            if line.startswith("#HttpOnly_"):
                fields[0] = fields[0].removeprefix("#HttpOnly_")
            elif line.startswith("#"):
                continue
            if len(fields) == 7 and fields[0].lstrip(".").endswith("youtube.com"):
                cookies.append(tuple(fields))
    else:
        if text.lower().startswith("cookie:"):
            text = text[len("cookie:") :]
        expiry = str(int(time.time()) + _HEADER_COOKIE_LIFETIME)
        for part in text.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                cookies.append(
                    (".youtube.com", "TRUE", "/", "TRUE", expiry, name, value)
                )
    names = {fields[5] for fields in cookies}
    if _LOGIN_COOKIE not in names or not names.intersection(_SID_COOKIES):
        raise InvalidCookies
    lines = ["# Netscape HTTP Cookie File", *("\t".join(f) for f in cookies)]
    return "\n".join(lines) + "\n"


def fetch_feed(cookies: str, limit: int) -> tuple[list[FeedItem], str, int]:
    """Read the home feed.

    Returns the items, the cookies as YouTube left them (it refreshes some on
    each visit; store them so the session lasts) and how many Shorts were
    left out. Ads are left out too. Raises SignedOut when the account is no
    longer signed in.
    """
    with _cookie_file(cookies) as path:
        with _Web(path) as web:
            html = web.get(HOME_URL)
            cfg = _ytcfg(html)
            if not cfg.get("LOGGED_IN"):
                raise SignedOut
            data = _json_after(html, "var ytInitialData =")
            if data is None:
                raise YouTubeError("home page has no data")
            items: list[FeedItem] = []
            tokens: list[str] = []
            shorts = _collect_feed(data, items, tokens)
            for _ in range(_FEED_PAGES - 1):
                if len(items) >= limit or not tokens:
                    break
                token = tokens.pop(0)
                tokens.clear()
                page = web.post(cfg, "browse", {"continuation": token})
                shorts += _collect_feed(page, items, tokens)
        with open(path, encoding="utf-8") as file:
            refreshed = file.read()
    seen: set[str] = set()
    unique = [i for i in items if not (i.id in seen or seen.add(i.id))]
    return unique[:limit], refreshed, shorts


def expand_list(
    list_id: str, cookies: str | None, limit: int
) -> list[tuple[str, str | None, str | None]]:
    """Return the first videos of a Mix or playlist as (id, title, channel).

    Cookies make a Mix personal and open private lists such as Watch Later.
    """
    with _cookie_file(cookies) as path:
        info, _ = _extract(list_url(list_id), path, limit)
    videos = []
    for entry in (info or {}).get("entries") or []:
        video_id = entry.get("id") or ""
        if _VIDEO_ID_RE.match(video_id):
            videos.append(
                (
                    video_id,
                    entry.get("title"),
                    entry.get("channel") or entry.get("uploader"),
                )
            )
    if not videos:
        raise YouTubeError(f"{list_id} has no videos")
    return videos


def mark_watched(cookies: str, video_id: str) -> str:
    """Mark a video fully watched on the account, so the feed drops it.

    yt-dlp sends the two playback pings the web player sends, with the
    position set just before the end. Returns the cookies as YouTube left
    them. Raises SignedOut when the account is no longer signed in.
    """
    with _cookie_file(cookies) as path:
        _, warnings = _extract(
            WATCH_URL.format(video_id=video_id),
            path,
            1,
            mark_watched=True,
            # Only the player data is needed, not a playable format.
            ignore_no_formats_error=True,
        )
        if any(_ROTATED_WARNING in w for w in warnings):
            raise SignedOut
        failed = next((w for w in warnings if _MARK_FAILED_WARNING in w), None)
        if failed:
            raise YouTubeError(failed)
        with open(path, encoding="utf-8") as file:
            refreshed = file.read()
    return refreshed


def fetch_watch_later(cookies: str) -> tuple[list[WatchLaterItem], str]:
    """Read Watch Later with each video's watched percent.

    yt-dlp's flat entries carry no progress, so this reads the playlist page
    the way youtube.com does. Returns the videos in list order and the cookies
    as YouTube left them. Raises SignedOut when the account is signed out.
    """
    with _cookie_file(cookies) as path:
        with _Web(path) as web:
            items, _ = _read_watch_later(web)
        with open(path, encoding="utf-8") as file:
            refreshed = file.read()
    return items, refreshed


def remove_from_watch_later(
    cookies: str, video_ids: list[str]
) -> tuple[list[str], str]:
    """Remove videos from Watch Later on the account.

    Reads the list first for each entry's set id; ids not in the list are
    skipped. Returns the ids removed and the cookies as YouTube left them.
    """
    with _cookie_file(cookies) as path:
        with _Web(path) as web:
            items, cfg = _read_watch_later(web)
            set_ids = {item.id: item.set_id for item in items if item.set_id}
            wanted = [vid for vid in dict.fromkeys(video_ids) if vid in set_ids]
            for start in range(0, len(wanted), _REMOVE_CHUNK):
                chunk = wanted[start : start + _REMOVE_CHUNK]
                answer = web.post(
                    cfg,
                    "browse/edit_playlist",
                    {
                        "playlistId": "WL",
                        "actions": [
                            {
                                "action": "ACTION_REMOVE_VIDEO",
                                "setVideoId": set_ids[vid],
                            }
                            for vid in chunk
                        ],
                    },
                )
                if answer.get("status") != "STATUS_SUCCEEDED":
                    raise YouTubeError(
                        f"Watch Later remove answered {answer.get('status')}"
                    )
        with open(path, encoding="utf-8") as file:
            refreshed = file.read()
    return wanted, refreshed


def add_to_watch_later(cookies: str, video_id: str) -> tuple[list[WatchLaterItem], str]:
    """Save a video to Watch Later on the account; a saved one stays as is.

    Returns Watch Later as read after the change (YouTube decides where the
    video goes in the list) and the cookies as YouTube left them.
    """
    with _cookie_file(cookies) as path:
        with _Web(path) as web:
            items, cfg = _read_watch_later(web)
            if all(item.id != video_id for item in items):
                answer = web.post(
                    cfg,
                    "browse/edit_playlist",
                    {
                        "playlistId": "WL",
                        "actions": [
                            {"action": "ACTION_ADD_VIDEO", "addedVideoId": video_id}
                        ],
                    },
                )
                if answer.get("status") != "STATUS_SUCCEEDED":
                    raise YouTubeError(
                        f"Watch Later add answered {answer.get('status')}"
                    )
                items, _ = _read_watch_later(web)
        with open(path, encoding="utf-8") as file:
            refreshed = file.read()
    return items, refreshed


def _read_watch_later(web: _Web) -> tuple[list[WatchLaterItem], dict[str, Any]]:
    html = web.get(WATCH_LATER_URL)
    cfg = _ytcfg(html)
    if not cfg.get("LOGGED_IN"):
        raise SignedOut
    data = _json_after(html, "var ytInitialData =")
    if data is None:
        raise YouTubeError("Watch Later page has no data")
    items: list[WatchLaterItem] = []
    tokens: list[str] = []
    _collect_watch_later(data, items, tokens)
    for _ in range(_WATCH_LATER_PAGES - 1):
        if not tokens:
            break
        token = tokens.pop(0)
        tokens.clear()
        _collect_watch_later(
            web.post(cfg, "browse", {"continuation": token}), items, tokens
        )
    return items, cfg


def _collect_watch_later(
    node: Any, items: list[WatchLaterItem], tokens: list[str]
) -> None:
    if isinstance(node, list):
        for child in node:
            _collect_watch_later(child, items, tokens)
        return
    if not isinstance(node, dict):
        return
    if (video := node.get("playlistVideoRenderer")) is not None:
        if item := _watch_later_item(video):
            items.append(item)
        return
    if (more := node.get("continuationItemRenderer")) is not None:
        token = (
            more.get("continuationEndpoint", {})
            .get("continuationCommand", {})
            .get("token")
        )
        if token:
            tokens.append(token)
        return
    for child in node.values():
        _collect_watch_later(child, items, tokens)


def _watch_later_item(video: dict[str, Any]) -> WatchLaterItem | None:
    video_id = video.get("videoId") or ""
    if not _VIDEO_ID_RE.match(video_id):
        return None
    percent = 0
    for overlay in video.get("thumbnailOverlays") or []:
        resume = overlay.get("thumbnailOverlayResumePlaybackRenderer")
        if resume:
            percent = int(resume.get("percentDurationWatched") or 0)
    length = video.get("lengthSeconds")
    return WatchLaterItem(
        id=video_id,
        title=_text(video.get("title")),
        channel=_text(video.get("shortBylineText")),
        duration=int(length) if str(length or "").isdigit() else None,
        percent=percent,
        set_id=video.get("setVideoId"),
        details=_details(
            [p.strip() for p in (_text(video.get("videoInfo")) or "").split("\u2022")]
        ),
    )


def _text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if "simpleText" in value:
        return value["simpleText"]
    runs = value.get("runs") or []
    return "".join(run.get("text", "") for run in runs) or None


def _json_after(html: str, marker: str) -> Any:
    start = html.find(marker)
    if start < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[start + len(marker) :].lstrip())[0]
    except ValueError:
        return None


def _ytcfg(html: str) -> dict[str, Any]:
    """Merge every ytcfg.set({...}) block of a youtube.com page."""
    cfg: dict[str, Any] = {}
    for match in re.finditer(r"ytcfg\.set\(\{", html):
        with contextlib.suppress(ValueError):
            cfg.update(json.JSONDecoder().raw_decode(html[match.end() - 1 :])[0])
    return cfg


class _Web:
    """youtube.com requests with the account's cookies, through yt-dlp.

    yt-dlp sends the cookies and saves the ones YouTube changes back to the
    file when it closes.
    """

    def __init__(self, cookiefile: str) -> None:
        import yt_dlp  # noqa: PLC0415  # slow import, kept off the event loop

        self._yt_dlp = yt_dlp
        self._ydl = yt_dlp.YoutubeDL(
            {"cookiefile": cookiefile, "quiet": True, "logger": _Collector()}
        )

    def __enter__(self) -> _Web:
        return self

    def __exit__(self, *exc: object) -> None:
        self._ydl.close()

    def get(self, url: str) -> str:
        """Return a page's HTML."""
        from yt_dlp.networking import Request  # noqa: PLC0415

        return self._open(Request(url, headers={"Accept-Language": "en-US"})).decode()

    def post(self, cfg: dict[str, Any], endpoint: str, body: dict[str, Any]) -> Any:
        """Call a youtubei endpoint as the signed-in web client."""
        from yt_dlp.networking import Request  # noqa: PLC0415

        payload = {"context": cfg.get("INNERTUBE_CONTEXT") or {}, **body}
        headers = {
            "Content-Type": "application/json",
            "Origin": _ORIGIN,
            "X-Origin": _ORIGIN,
            "X-Goog-AuthUser": str(cfg.get("SESSION_INDEX") or 0),
            "X-Youtube-Client-Name": "1",
            "X-Youtube-Client-Version": str(cfg.get("INNERTUBE_CLIENT_VERSION") or ""),
            "Authorization": self._authorization(),
        }
        if cfg.get("VISITOR_DATA"):
            headers["X-Goog-Visitor-Id"] = cfg["VISITOR_DATA"]
        if cfg.get("DELEGATED_SESSION_ID"):
            # A brand account's channel.
            headers["X-Goog-PageId"] = cfg["DELEGATED_SESSION_ID"]
        request = Request(
            f"{_ORIGIN}/youtubei/v1/{endpoint}?prettyPrint=false",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        return json.loads(self._open(request))

    def _authorization(self) -> str:
        """SAPISIDHASH headers, the way youtube.com signs its own calls."""
        values = {
            cookie.name: cookie.value
            for cookie in self._ydl.cookiejar
            if cookie.domain.lstrip(".").endswith("youtube.com")
        }
        stamp = str(int(time.time()))
        parts = []
        for scheme, name in (
            ("SAPISIDHASH", "SAPISID"),
            ("SAPISID1PHASH", "__Secure-1PAPISID"),
            ("SAPISID3PHASH", "__Secure-3PAPISID"),
        ):
            value = values.get(name) or (
                values.get("__Secure-3PAPISID") if name == "SAPISID" else None
            )
            if value:
                # YouTube's scheme, not ours to choose.
                digest = hashlib.sha1(
                    f"{stamp} {value} {_ORIGIN}".encode(), usedforsecurity=False
                ).hexdigest()
                parts.append(f"{scheme} {stamp}_{digest}")
        if not parts:
            raise SignedOut
        return " ".join(parts)

    def _open(self, request: Any) -> bytes:
        try:
            with self._ydl.urlopen(request) as response:
                return response.read()
        except self._yt_dlp.networking.exceptions.HTTPError as err:
            if err.status in (401, 403):
                raise SignedOut from err
            raise YouTubeError(f"HTTP {err.status}") from err
        except self._yt_dlp.utils.YoutubeDLError as err:
            raise YouTubeError(str(err)) from err


def _collect_feed(node: Any, items: list[FeedItem], tokens: list[str]) -> int:
    """Add the feed tiles under node; return how many Shorts were skipped."""
    if isinstance(node, list):
        return sum(_collect_feed(child, items, tokens) for child in node)
    if not isinstance(node, dict):
        return 0
    if "adSlotRenderer" in node:
        return 0
    if "shortsLockupViewModel" in node:
        return 1
    if (lockup := node.get("lockupViewModel")) is not None:
        if item := _feed_item(lockup):
            items.append(item)
        return 0
    if (more := node.get("continuationItemRenderer")) is not None:
        token = (
            more.get("continuationEndpoint", {})
            .get("continuationCommand", {})
            .get("token")
        )
        if token:
            tokens.append(token)
        return 0
    return sum(_collect_feed(child, items, tokens) for child in node.values())


def _feed_item(lockup: dict[str, Any]) -> FeedItem | None:
    """Return the feed item for a home page tile, None for ads and unknowns."""
    watch = (
        lockup.get("rendererContext", {})
        .get("commandContext", {})
        .get("onTap", {})
        .get("innertubeCommand", {})
        .get("watchEndpoint")
    )
    if not watch:
        return None
    meta = lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
    title = (meta.get("title") or {}).get("content")
    parts = [
        part.get("text", {}).get("content")
        for row in meta.get("metadata", {})
        .get("contentMetadataViewModel", {})
        .get("metadataRows", [])
        for part in row.get("metadataParts", [])
    ]
    parts = [p for p in parts if p]
    channel = parts[0] if parts else None
    kind = lockup.get("contentType")
    if kind == "LOCKUP_CONTENT_TYPE_PLAYLIST":
        list_id = watch.get("playlistId") or lockup.get("contentId") or ""
        if not list_id:
            return None
        seed = mix_seed(list_id)
        return FeedItem(
            kind="mix" if list_id.startswith("RD") else "playlist",
            id=list_id,
            title=title,
            channel=channel,
            thumbnail=THUMBNAIL_URL.format(video_id=seed)
            if seed
            else _first_image(lockup.get("contentImage")),
            video_id=seed or watch.get("videoId"),
        )
    video_id = watch.get("videoId") or ""
    if kind != "LOCKUP_CONTENT_TYPE_VIDEO" or not _VIDEO_ID_RE.match(video_id):
        return None
    duration, live, percent = None, False, 0
    for overlay in (
        lockup.get("contentImage", {}).get("thumbnailViewModel", {}).get("overlays", [])
    ):
        bottom = overlay.get("thumbnailBottomOverlayViewModel") or {}
        bar = (bottom.get("progressBar") or {}).get(
            "thumbnailOverlayProgressBarViewModel"
        ) or {}
        percent = int(bar.get("startPercent") or percent)
        for entry in bottom.get("badges", []):
            badge = entry.get("thumbnailBadgeViewModel", {})
            text = badge.get("text") or ""
            if "LIVE" in (badge.get("badgeStyle") or "") or text.upper() == "LIVE":
                live = True
            elif re.fullmatch(r"\d+(:\d{2}){1,2}", text):
                duration = _seconds(text)
    return FeedItem(
        kind="video",
        id=video_id,
        title=title,
        channel=channel,
        duration=duration,
        thumbnail=THUMBNAIL_URL.format(video_id=video_id),
        video_id=video_id,
        live=live,
        details=_details(parts[1:]),
        percent=percent,
    )


def _details(parts: list[str]) -> str | None:
    """Join what follows the channel: a bare count ("1.5M") gets "views"."""
    out = [f"{p} views" if re.fullmatch(r"[\d.,]+[KMB]?", p) else p for p in parts if p]
    return " \u2022 ".join(out) or None


def _seconds(text: str) -> int:
    total = 0
    for part in text.split(":"):
        total = total * 60 + int(part)
    return total


def _first_image(node: Any) -> str | None:
    """Return the largest source of the first image under node."""
    if isinstance(node, list):
        for child in node:
            if url := _first_image(child):
                return url
        return None
    if not isinstance(node, dict):
        return None
    sources = node.get("sources")
    if isinstance(sources, list) and sources and sources[-1].get("url"):
        return sources[-1]["url"]
    for child in node.values():
        if url := _first_image(child):
            return url
    return None


class _Collector:
    """yt-dlp logger that keeps warnings and errors, for sign-in checks."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, msg: str) -> None:
        """Drop progress output."""

    info = debug

    def warning(self, msg: str) -> None:
        """Keep a warning."""
        self.messages.append(msg)

    def error(self, msg: str) -> None:
        """Keep an error."""
        self.messages.append(msg)


def _extract(
    url: str, cookiefile: str | None, limit: int, **extra: Any
) -> tuple[Any, list[str]]:
    """Run yt-dlp on a URL; a list is read flat, never its videos."""
    import yt_dlp  # noqa: PLC0415  # slow import, kept off the event loop

    log = _Collector()
    options: dict[str, Any] = {
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "noplaylist": False,
        "skip_download": True,
        "quiet": True,
        "logger": log,
        **extra,
    }
    if cookiefile:
        options["cookiefile"] = cookiefile
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.YoutubeDLError as err:
        raise YouTubeError(str(err)) from err
    return info, log.messages


@contextlib.contextmanager
def _cookie_file(cookies: str | None) -> Iterator[str | None]:
    """Yield a private temporary cookies.txt; yt-dlp saves changes back to it."""
    if cookies is None:
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="youtube_account_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(cookies)
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
# Mixes (RD), playlists (PL), albums (OL), a channel's uploads (UU) and
# favourites (FL); Watch Later and Liked videos are just WL and LL.
_LIST_ID_RE = re.compile(r"^(?:(?:PL|RD|OL|UU|FL)[A-Za-z0-9_-]{10,}|WL|LL)$")


def parse_video_id(media_id: str) -> str | None:
    """Return the video id from a YouTube video id or URL."""
    media_id = media_id.strip()
    if _VIDEO_ID_RE.match(media_id):
        return media_id
    url = urlparse(media_id if "://" in media_id else f"https://{media_id}")
    host = (url.hostname or "").removeprefix("www.")
    if host not in _YOUTUBE_HOSTS:
        return None
    if host == "youtu.be":
        candidate = url.path.strip("/")
    elif url.path.startswith(("/shorts/", "/live/", "/embed/")):
        candidate = url.path.split("/")[2]
    else:
        candidate = parse_qs(url.query).get("v", [""])[0]
    return candidate if _VIDEO_ID_RE.match(candidate) else None


def parse_list_id(media_id: str) -> str | None:
    """Return the list id of a Mix or playlist id or URL.

    A link to a video in a list (watch?v=...&list=...) is the video: that's
    what a shared link means.
    """
    media_id = media_id.strip()
    if _LIST_ID_RE.match(media_id):
        return media_id
    url = urlparse(media_id if "://" in media_id else f"https://{media_id}")
    host = (url.hostname or "").removeprefix("www.")
    if host not in _YOUTUBE_HOSTS:
        return None
    query = parse_qs(url.query)
    if query.get("v"):
        return None
    candidate = query.get("list", [""])[0]
    return candidate if _LIST_ID_RE.match(candidate) else None
