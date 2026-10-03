"""Tests for reading the home feed and lists with yt-dlp."""

from __future__ import annotations

import json
import os
from typing import ClassVar
from unittest.mock import patch

import pytest
import yt_dlp

from custom_components.youtube_account import youtube
from custom_components.youtube_account.youtube import (
    FeedItem,
    InvalidCookies,
    SignedOut,
    YouTubeError,
    list_url,
    mix_seed,
    parse_cookies,
)

HEADER = "GPS=1; YSC=abc; SID=s; SAPISID=sap; LOGIN_INFO=li; PREF=f=1"


@pytest.mark.parametrize("prefix", ["", "cookie: ", "Cookie:"])
def test_parse_header(prefix: str) -> None:
    text = parse_cookies(prefix + HEADER)
    lines = text.splitlines()
    assert lines[0] == "# Netscape HTTP Cookie File"
    fields = [line.split("\t") for line in lines[1:]]
    assert [f[5] for f in fields] == [
        "GPS",
        "YSC",
        "SID",
        "SAPISID",
        "LOGIN_INFO",
        "PREF",
    ]
    assert all(f[0] == ".youtube.com" and len(f) == 7 for f in fields)
    assert fields[5][6] == "f=1"


def test_parse_cookies_file() -> None:
    text = (
        "# Netscape HTTP Cookie File\n"
        "# comment\n"
        ".youtube.com\tTRUE\t/\tTRUE\t1\tSAPISID\tsap\n"
        "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1\tLOGIN_INFO\tli\n"
        ".google.com\tTRUE\t/\tTRUE\t1\tSID\tother\n"
    )
    lines = parse_cookies(text).splitlines()
    assert len(lines) == 3
    assert lines[2].startswith(".youtube.com\t") and lines[2].endswith("LOGIN_INFO\tli")


@pytest.mark.parametrize(
    "text", ["", "hello", "GPS=1; SAPISID=sap", "LOGIN_INFO=li; PREF=1"]
)
def test_parse_cookies_not_signed_in(text: str) -> None:
    with pytest.raises(InvalidCookies):
        parse_cookies(text)


def test_mix_seed_and_urls() -> None:
    assert mix_seed("RDqyUPz6_TciY") == "qyUPz6_TciY"
    assert mix_seed("RDCLAK5uy_abcdefghijklmnop") is None
    assert mix_seed("PLabc") is None
    assert list_url("RDqyUPz6_TciY") == (
        "https://www.youtube.com/watch?v=qyUPz6_TciY&list=RDqyUPz6_TciY"
    )
    assert list_url("PLx") == "https://www.youtube.com/playlist?list=PLx"


def _lockup(kind, content_id, watch, title, parts, overlays=None, image=None):
    return {
        "lockupViewModel": {
            "contentType": kind,
            "contentId": content_id,
            "contentImage": image
            or {"thumbnailViewModel": {"overlays": overlays or []}},
            "metadata": {
                "lockupMetadataViewModel": {
                    "title": {"content": title},
                    "metadata": {
                        "contentMetadataViewModel": {
                            "metadataRows": [
                                {
                                    "metadataParts": [
                                        {"text": {"content": p}} for p in parts
                                    ]
                                }
                            ]
                        }
                    },
                }
            },
            "rendererContext": {
                "commandContext": {"onTap": {"innertubeCommand": watch}}
            },
        }
    }


def _bottom(badges, percent=None):
    bottom = {
        "badges": [
            {"thumbnailBadgeViewModel": {"text": text, "badgeStyle": style}}
            for text, style in badges
        ]
    }
    if percent is not None:
        bottom["progressBar"] = {
            "thumbnailOverlayProgressBarViewModel": {"startPercent": percent}
        }
    return {"thumbnailBottomOverlayViewModel": bottom}


VIDEO_TILE = _lockup(
    "LOCKUP_CONTENT_TYPE_VIDEO",
    "OmmaHKzxtVw",
    {"watchEndpoint": {"videoId": "OmmaHKzxtVw"}},
    "This Is Where the Cheap Groceries Are",
    ["Internet Shaquille", "1.5M", "1d ago"],
    [_bottom([("8:31", "THUMBNAIL_OVERLAY_BADGE_STYLE_DEFAULT")], 42)],
)
LIVE_TILE = _lockup(
    "LOCKUP_CONTENT_TYPE_VIDEO",
    "liveliveliv",
    {"watchEndpoint": {"videoId": "liveliveliv"}},
    "Live now",
    ["A channel", "1.2K watching"],
    [_bottom([("LIVE", "THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE")])],
)
MIX_TILE = _lockup(
    "LOCKUP_CONTENT_TYPE_PLAYLIST",
    "RDqyUPz6_TciY",
    {"watchEndpoint": {"videoId": "qyUPz6_TciY", "playlistId": "RDqyUPz6_TciY"}},
    "Mix - Though You Slay Me",
    ["Shane & Shane, and more", "Playlist"],
)
PLAYLIST_TILE = _lockup(
    "LOCKUP_CONTENT_TYPE_PLAYLIST",
    "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
    {
        "watchEndpoint": {
            "videoId": "aaaaaaaaaaa",
            "playlistId": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
        }
    },
    "Popular Music Videos",
    ["YouTube", "Playlist"],
    image={
        "collectionThumbnailViewModel": {
            "primaryThumbnail": {
                "thumbnailViewModel": {
                    "image": {
                        "sources": [
                            {"url": "https://i.ytimg.com/a.jpg"},
                            {"url": "https://i.ytimg.com/b.jpg"},
                        ]
                    }
                }
            }
        }
    },
)
AD_TILE = {"adSlotRenderer": {"fulfillmentContent": {"x": VIDEO_TILE}}}
NO_WATCH_TILE = _lockup(None, "sIqwhrIot8s", {"urlEndpoint": {}}, "", [])
SHORT_TILE = {"shortsLockupViewModel": {"entityId": "abcdefghijk"}}


def _page(data, logged_in=True):
    cfg = {"LOGGED_IN": logged_in, "INNERTUBE_CONTEXT": {"client": {}}}
    return (
        f"<script>ytcfg.set({json.dumps(cfg)});</script>"
        f"<script>var ytInitialData = {json.dumps(data)};</script>"
    )


def _more(token):
    return {
        "continuationItemRenderer": {
            "continuationEndpoint": {"continuationCommand": {"token": token}}
        }
    }


class FakeWeb:
    """Stands in for _Web: canned pages and youtubei answers."""

    pages: ClassVar[dict[str, str]] = {}
    answers: ClassVar[list] = []
    posts: ClassVar[list] = []

    def __init__(self, cookiefile: str) -> None:
        self.cookiefile = cookiefile

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        with open(self.cookiefile, "a", encoding="utf-8") as file:
            file.write("# refreshed\n")

    def get(self, url):
        return self.pages[url]

    def post(self, cfg, endpoint, body):
        FakeWeb.posts.append((endpoint, body))
        return FakeWeb.answers.pop(0)


@pytest.fixture
def web():
    FakeWeb.pages, FakeWeb.answers, FakeWeb.posts = {}, [], []
    with patch.object(youtube, "_Web", FakeWeb):
        yield FakeWeb


def test_fetch_feed_classifies(web) -> None:
    web.pages[youtube.HOME_URL] = _page(
        {
            "contents": [
                VIDEO_TILE,
                AD_TILE,
                MIX_TILE,
                SHORT_TILE,
                NO_WATCH_TILE,
                PLAYLIST_TILE,
                LIVE_TILE,
            ]
        }
    )
    items, refreshed, shorts = youtube.fetch_feed(parse_cookies(HEADER), 30)
    assert [i.kind for i in items] == ["video", "mix", "playlist", "video"]
    video, mix, playlist, live = items
    assert video == FeedItem(
        kind="video",
        id="OmmaHKzxtVw",
        title="This Is Where the Cheap Groceries Are",
        channel="Internet Shaquille",
        duration=511,
        thumbnail="https://i.ytimg.com/vi/OmmaHKzxtVw/hqdefault.jpg",
        video_id="OmmaHKzxtVw",
        details="1.5M views \u2022 1d ago",
        percent=42,
    )
    assert mix.video_id == "qyUPz6_TciY"
    assert mix.channel == "Shane & Shane, and more"
    assert mix.thumbnail == "https://i.ytimg.com/vi/qyUPz6_TciY/hqdefault.jpg"
    assert mix.as_dict()["url"].endswith("watch?v=qyUPz6_TciY&list=RDqyUPz6_TciY")
    assert playlist.thumbnail == "https://i.ytimg.com/b.jpg"
    assert live.live and live.duration is None
    assert live.details == "1.2K watching"
    assert shorts == 1
    assert refreshed.endswith("# refreshed\n")


def test_fetch_feed_reads_more_pages_up_to_limit(web) -> None:
    web.pages[youtube.HOME_URL] = _page({"contents": [VIDEO_TILE, _more("t1")]})
    web.answers.append({"items": [VIDEO_TILE, LIVE_TILE, _more("t2")]})
    items, _, _ = youtube.fetch_feed(parse_cookies(HEADER), 2)
    assert [i.id for i in items] == ["OmmaHKzxtVw", "liveliveliv"]
    assert web.posts == [("browse", {"continuation": "t1"})]


def test_fetch_feed_empty_but_signed_in(web) -> None:
    web.pages[youtube.HOME_URL] = _page({"contents": []})
    items, _, _ = youtube.fetch_feed(parse_cookies(HEADER), 30)
    assert items == []


def test_fetch_feed_signed_out(web) -> None:
    web.pages[youtube.HOME_URL] = _page({"contents": [VIDEO_TILE]}, logged_in=False)
    with pytest.raises(SignedOut):
        youtube.fetch_feed(parse_cookies(HEADER), 30)


def test_fetch_feed_page_without_data(web) -> None:
    web.pages[youtube.HOME_URL] = "<html></html>".replace(
        "</html>", '<script>ytcfg.set({"LOGGED_IN": true});</script></html>'
    )
    with pytest.raises(YouTubeError):
        youtube.fetch_feed(parse_cookies(HEADER), 30)


def _wl_video(video_id, percent=None, set_id="s"):
    overlays = [{"thumbnailOverlayTimeStatusRenderer": {}}]
    if percent is not None:
        overlays.append(
            {
                "thumbnailOverlayResumePlaybackRenderer": {
                    "percentDurationWatched": percent
                }
            }
        )
    return {
        "playlistVideoRenderer": {
            "videoId": video_id,
            "setVideoId": set_id + video_id,
            "title": {"runs": [{"text": "T " + video_id}]},
            "shortBylineText": {"runs": [{"text": "Chan"}]},
            "lengthSeconds": "600",
            "videoInfo": {
                "runs": [{"text": "117K"}, {"text": " \u2022 "}, {"text": "3w ago"}]
            },
            "thumbnailOverlays": overlays,
        }
    }


A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


def test_fetch_watch_later(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page(
        {"contents": [_wl_video(A, 100), _wl_video(B), _more("t1")]}
    )
    web.answers.append({"onResponseReceivedActions": [{"items": [_wl_video(C, 42)]}]})
    items, refreshed = youtube.fetch_watch_later(parse_cookies(HEADER))
    assert [(i.id, i.percent) for i in items] == [(A, 100), (B, 0), (C, 42)]
    assert items[0].as_dict() == {
        "id": A,
        "title": "T " + A,
        "channel": "Chan",
        "duration": 600,
        "percent": 100,
        "details": "117K views \u2022 3w ago",
        "thumbnail": f"https://i.ytimg.com/vi/{A}/hqdefault.jpg",
        "url": f"https://www.youtube.com/watch?v={A}",
    }
    assert refreshed.endswith("# refreshed\n")


def test_fetch_watch_later_signed_out(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page({}, logged_in=False)
    with pytest.raises(SignedOut):
        youtube.fetch_watch_later(parse_cookies(HEADER))


def test_remove_from_watch_later(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page(
        {"contents": [_wl_video(A, 100), _wl_video(B, 95)]}
    )
    web.answers.append({"status": "STATUS_SUCCEEDED"})
    removed, _ = youtube.remove_from_watch_later(
        parse_cookies(HEADER), [B, "zzzzzzzzzzz", A, B]
    )
    assert removed == [B, A]
    assert web.posts == [
        (
            "browse/edit_playlist",
            {
                "playlistId": "WL",
                "actions": [
                    {"action": "ACTION_REMOVE_VIDEO", "setVideoId": "s" + B},
                    {"action": "ACTION_REMOVE_VIDEO", "setVideoId": "s" + A},
                ],
            },
        )
    ]


def test_add_to_watch_later(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page({"contents": [_wl_video(A, 100)]})
    web.answers.append({"status": "STATUS_SUCCEEDED"})
    items, _ = youtube.add_to_watch_later(parse_cookies(HEADER), B)
    assert web.posts == [
        (
            "browse/edit_playlist",
            {
                "playlistId": "WL",
                "actions": [{"action": "ACTION_ADD_VIDEO", "addedVideoId": B}],
            },
        )
    ]
    assert [i.id for i in items] == [A]  # the canned page did not change


def test_add_saved_video_sends_nothing(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page({"contents": [_wl_video(A, 100)]})
    youtube.add_to_watch_later(parse_cookies(HEADER), A)
    assert web.posts == []


def test_remove_from_watch_later_refused(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page({"contents": [_wl_video(A, 100)]})
    web.answers.append({"status": "STATUS_FAILED"})
    with pytest.raises(YouTubeError):
        youtube.remove_from_watch_later(parse_cookies(HEADER), [A])


def test_remove_nothing_listed_sends_nothing(web) -> None:
    web.pages[youtube.WATCH_LATER_URL] = _page({"contents": []})
    removed, _ = youtube.remove_from_watch_later(parse_cookies(HEADER), [A])
    assert removed == []
    assert web.posts == []


def _run_mark(warnings: list[str]) -> tuple[str, dict]:
    seen = {}

    def extract(url, path, limit, **extra):
        seen.update(url=url, **extra)
        with open(path, "a", encoding="utf-8") as file:
            file.write("# refreshed\n")
        return {"id": "OmmaHKzxtVw"}, warnings

    with patch.object(youtube, "_extract", side_effect=extract):
        return youtube.mark_watched(parse_cookies(HEADER), "OmmaHKzxtVw"), seen


def test_mark_watched() -> None:
    refreshed, seen = _run_mark(["Some formats are missing"])
    assert seen == {
        "url": "https://www.youtube.com/watch?v=OmmaHKzxtVw",
        "mark_watched": True,
        "ignore_no_formats_error": True,
    }
    assert refreshed.endswith("# refreshed\n")


def test_mark_watched_failed() -> None:
    with pytest.raises(YouTubeError, match="Unable to mark watched"):
        _run_mark(["Unable to mark watched"])


def test_mark_watched_rotated_cookies() -> None:
    with pytest.raises(SignedOut):
        _run_mark(["The provided YouTube account cookies are no longer valid."])


def test_expand_list() -> None:
    entries = [
        {"id": "qyUPz6_TciY", "title": "One", "channel": "A"},
        {"id": "RDnotavideo123", "title": "x"},
        {"id": "OmmaHKzxtVw", "title": "Two", "uploader": "B"},
    ]
    with patch.object(
        youtube, "_extract", return_value=({"entries": entries}, [])
    ) as extract:
        videos = youtube.expand_list("RDqyUPz6_TciY", None, 25)
    assert videos == [("qyUPz6_TciY", "One", "A"), ("OmmaHKzxtVw", "Two", "B")]
    assert extract.call_args.args == (
        "https://www.youtube.com/watch?v=qyUPz6_TciY&list=RDqyUPz6_TciY",
        None,
        25,
    )


def test_expand_empty_list() -> None:
    with (
        patch.object(youtube, "_extract", return_value=({"entries": []}, [])),
        pytest.raises(YouTubeError),
    ):
        youtube.expand_list("PLx", None, 25)


def test_extract_wraps_errors() -> None:
    """A yt-dlp error becomes a YouTubeError; the cookie file is removed."""

    paths = []

    class Failing:
        def __init__(self, options):
            paths.append(options.get("cookiefile"))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError("nope")

    with patch.object(yt_dlp, "YoutubeDL", Failing), pytest.raises(YouTubeError):
        youtube.expand_list("PLx", parse_cookies(HEADER), 5)
    assert paths[0] is not None
    assert not os.path.exists(paths[0])
