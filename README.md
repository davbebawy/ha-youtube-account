# YouTube Account

A Home Assistant integration for a signed-in YouTube account: the home feed, Watch Later, mark watched, and a dashboard card to browse them and play on a TV.

It plays nothing by itself. Playback goes through [YouTube on TV](https://github.com/jorgediez/ha-youtube-on-tv), which controls the YouTube app on a TV over the Lounge protocol. This integration only calls `media_player.play_media` on a YouTube on TV player, so the two have separate release cycles: when YouTube reshapes a page, only this one needs an update.

## Features

- `sensor.youtube_account_home_feed`: your personal home feed (videos, Mixes and playlists), with views, age and the watched bar, as youtube.com shows them. Shorts and ads are left out.
- `sensor.youtube_account_watch_later`: Watch Later with the watched percent of each video.
- Actions: play a video, Mix or playlist on a TV; mark watched; save to and remove from Watch Later; refresh.
- A media source: the feed and Watch Later under **Media** in Home Assistant.
- The feed card, `custom:youtube-feed-card`, loaded on every dashboard with no resource to add.

## Installation

HACS: *HACS > Custom repositories*, add `https://github.com/davbebawy/ha-youtube-account` as an integration, install **YouTube Account**, and restart Home Assistant. Install YouTube on TV as well, for playback.

Manual: copy `custom_components/youtube_account` to your `config/custom_components/` folder and restart.

## Setup

**Settings > Devices & services > Add integration > YouTube Account.** The dialog lists the steps: in a private browser window, sign in to youtube.com, copy the `cookie` request header of a `browse` request (DevTools > Network), paste it, then close the window without signing out. A whole `cookies.txt` export works too, pasted or as a file on the Home Assistant host (give its path; it is read once and not kept, so delete it afterwards). YouTube's Data API has no home feed and yt-dlp's OAuth login no longer works, so cookies are the only way in.

There is one account. **Reconfigure** takes new cookies. When YouTube stops accepting the sign-in, Home Assistant asks for new cookies with the same dialog.

The **YouTube account** device has:

| Entity | Description |
|---|---|
| `sensor.youtube_account_home_feed` | Number of feed items; `items` attribute with each video, Mix or playlist (id, title, channel, duration, thumbnail, url, `details`: views and age, such as 1.5M views and 1d ago, `percent` watched). `updated_at`, `shorts_hidden`, `min_refresh_minutes` |
| `sensor.youtube_account_watch_later` | Number of Watch Later videos; `items` attribute in list order (id, title, channel, duration, `percent` watched, `details`, thumbnail, url). Read with the feed |
| `binary_sensor.youtube_account_signed_in` | Turns off when YouTube stops accepting the sign-in |
| `button.youtube_account_refresh_home_feed` | Reads the feed and Watch Later again |

The feed and Watch Later are read when asked (the button, `youtube_account.refresh_feed`, opening the media browser or the feed card, Home Assistant starting), never on a timer. The account's **Configure** option *Minimum time between feed reads* (default 15 minutes, up to 7 days) holds off every automatic read: a start or an open reads YouTube only when the last read is older. The last read is kept on disk (`.storage/youtube_account.feed_cache.<entry id>`), so a restart shows it at once. The Refresh button and `refresh_feed` without `max_age` always read. YouTube refreshes some cookies on each read; they are saved, which keeps the sign-in alive.

## Actions

| Action | Effect |
|---|---|
| `youtube_account.play` | Plays `media` (a video, Mix or playlist id or link: `RD...`, `PL...`, `WL`, `LL`, `youtube.com/playlist?list=...`) on `entity_id`, a YouTube on TV player, with `enqueue` `play` (default), `next`, `add` or `replace`. A Mix sends its first 25 videos and a playlist its first 50, read signed in so a Mix is your own and Watch Later opens. A link to a video inside a list (`watch?v=...&list=...`) plays the video |
| `youtube_account.refresh_feed` | Reads the feed again; with `max_age` only if the last read is older (seconds; raised to the minimum time between reads) |
| `youtube_account.mark_watched` | Marks `video` (id or link) fully watched on the account and drops it from the feed |
| `youtube_account.add_to_watch_later` | Saves `video` (id or link) to Watch Later; one already there stays |
| `youtube_account.remove_from_watch_later` | Removes `videos` (ids or links) from Watch Later, or with `min_percent` every video in the last read list watched that far. Returns `removed`. This changes the account; it is not a hide |

`youtube_account.play` calls `media_player.play_media` on the player:

| What | `media_content_type` | `media_content_id` | `extra` |
|---|---|---|---|
| A video | `video` | the 11-character id | |
| A Mix | `playlist` | its first 25 video ids, comma separated | `list_id`: the Mix id, so the TV keeps the Mix going |
| A playlist | `playlist` | its first 50 video ids, comma separated | |

`enqueue` is passed as given. Resume and moving a video between TVs are YouTube on TV actions (`youtube_on_tv.resume`, `youtube_on_tv.transfer`), as is the last watched sensor.

## Media source

The feed and Watch Later show under **Media > YouTube** and in a player's media browser. For a YouTube on TV player an item resolves to what its `play_media` takes: a video id (type `video`), or a Mix or playlist as comma separated video ids (type `playlist`). Any other player gets the youtube.com link (type `video/youtube`); only players that open YouTube links can use it. Opening the browser reads the feed again when the last read is older than 15 minutes (or the minimum time between reads).

## Feed card

The integration loads the card on every dashboard; no resource is needed:

```yaml
type: custom:youtube-feed-card
layout: auto        # list on a phone, grid with a Now playing panel when wide
players:            # default: every YouTube on TV player
  - entity: media_player.youtube_on_living_room
    name: Living room
    open:           # optional: opens YouTube when it's closed
      action: script.open_youtube
      data: {}
```

Other options: `player_options` (name and `open` per found player, keyed by entity), `exclude`, `ios_browser: brave` ("Here" links open in Brave on an iPhone or iPad), `max_age` (seconds; read the feed again on open when older), `clean_percent` (Watch Later "Clean up" removes videos watched this far), `session` (the last watched sensor; default: the one YouTube on TV has).

Every action goes to the player in **Now playing**: the one playing (the latest to start), else the one last picked there. With more than one player, Now playing has a switch between them and **Move to** for each other player. Its clock runs on its own and moves only when a report differs by 1.5 s or more; the rate is the player's speed, measured from two reports when the TV plays faster than it tells the remote protocol (TizenTube at 2x reports speed 1). With a mouse, a video's actions show on hover, each icon with its name. The gear (admins only) edits the minimum time between feed reads in the card: it saves the account's Configure option; **All settings** opens the integration page.

Play, Next and Queue call `youtube_account.play`; Watched, Save and Remove call the account actions; Resume and Move to call `youtube_on_tv.resume` and `youtube_on_tv.transfer`.

## Where the parsing comes from

YouTube changes its pages without notice. When a read breaks, start from the source each part copies. Function names are from yt-dlp 2026.07.04; on a newer yt-dlp, search its `extractor/youtube/` folder for the renderer name instead:

| Part | Reads | Source to compare with |
|---|---|---|
| Home feed (`youtube.fetch_feed`) | `https://www.youtube.com/` page, `var ytInitialData`: `lockupViewModel` tiles (`contentType` VIDEO or PLAYLIST, Mix ids start `RD`), `shortsLockupViewModel` (counted, left out), `adSlotRenderer` (left out). Views and age from `metadata.lockupMetadataViewModel...metadataRows[].metadataParts[]` after the channel; duration and LIVE from `thumbnailBottomOverlayViewModel.badges`; watched bar from `progressBar.thumbnailOverlayProgressBarViewModel.startPercent`. More tiles: `continuationItemRenderer` token to `youtubei/v1/browse` | yt-dlp's `:ytrec` feed (`yt_dlp/extractor/youtube/_tab.py`, `YoutubeTabBaseInfoExtractor._rich_entries` and `_extract_lockup_view_model`), which this replaced because its entries drop views, age and progress. TizenTube reads the same progress fields on the TV (`mods/utils/watched.js`) |
| Watch Later (`youtube.fetch_watch_later`) | `https://www.youtube.com/playlist?list=WL` page, `playlistVideoRenderer` (`videoId`, `setVideoId`, `lengthSeconds`, `videoInfo` runs, `thumbnailOverlayResumePlaybackRenderer.percentDurationWatched`); 100 per page, more through `continuationItemRenderer` | yt-dlp's playlist parsing (`_tab.py`, `YoutubeTabBaseInfoExtractor._playlist_entries`); measured on a signed-in account 2026-10-02 (31 videos, 24 with a bar) |
| Save to and remove from Watch Later | `youtubei/v1/browse/edit_playlist`, `playlistId: WL`: `ACTION_ADD_VIDEO` with `addedVideoId`, `ACTION_REMOVE_VIDEO` with `setVideoId` | what youtube.com sends from a playlist's "Remove from Watch Later" (DevTools, Network); TizenTube's long-press menu sends `ACTION_REMOVE_VIDEO_BY_VIDEO_ID` (`mods/ui/ytUI.js`, `longPressData`) |
| Signed requests (`youtube._Web`) | `ytcfg.set({...})` blocks for `INNERTUBE_CONTEXT`, `INNERTUBE_CLIENT_VERSION`, `VISITOR_DATA`, `SESSION_INDEX`, `DELEGATED_SESSION_ID`, `LOGGED_IN`; `Authorization: SAPISIDHASH <ts>_<sha1(ts SAPISID origin)>` plus the 1P and 3P forms | yt-dlp `yt_dlp/extractor/youtube/_base.py` (`_make_sid_authorization`, `_get_sid_authorization_header`, `generate_api_headers`, `extract_ytcfg`) |
| Mixes, playlists, mark watched | yt-dlp `extract_info` (flat) and `mark_watched` | yt-dlp; the version Home Assistant core pins for `media_extractor` (2026.07.04 on HA 2026.9) |

## Moving from the account inside YouTube on TV

Earlier builds of a YouTube on TV fork held this account as a second kind of entry. To move:

1. Remove the old "YouTube account" entry under YouTube on TV, so its entity ids are free.
2. Add **YouTube Account** with the same cookies. The entities come back with the same ids.
3. Change callers of `youtube_on_tv.refresh_feed`, `.mark_watched`, `.add_to_watch_later` and `.remove_from_watch_later` to `youtube_account.*`. `play_media` with a Mix or playlist id becomes `youtube_account.play`.

## Privacy

- The account's cookies are stored in Home Assistant's config entry (and so in its backups). They are a signed-in Google session: they are redacted from diagnostics and never shown in an entity. Remove the session any time under Google Account > Security > Your devices.
- The integration talks to `www.youtube.com` (pages, `youtubei` calls and yt-dlp) and links thumbnails on `i.ytimg.com`.

## Development

```bash
uv venv --python 3.14 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python -m pytest
cd scripts/card-smoke && pnpm install && pnpm test
```

`scripts/live_probe.sh feed|watch_later` runs this checkout's `youtube.py` on a Home Assistant box (over `ssh home-assistant`) against the stored account cookies, read only, and prints a summary with no cookies. Use it before and after a parser change.

## License

[GPL-3.0](LICENSE). Parts of this code started in [YouTube on TV](https://github.com/jorgediez/ha-youtube-on-tv), also GPL-3.0.
