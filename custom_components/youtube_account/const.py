"""Constants for the YouTube Account integration."""

import logging
from typing import Final

DOMAIN: Final = "youtube_account"
LOGGER = logging.getLogger(__package__)

# The integration that plays on the TV. This integration never imports it: it
# only calls media_player.play_media on that integration's players.
TV_PLATFORM: Final = "youtube_on_tv"

# The account's cookies.txt, as YouTube last left it.
CONF_COOKIES: Final = "cookies"
# A cookies.txt on the Home Assistant host, read once by the setup form
# instead of a pasted value. Not stored.
CONF_COOKIES_FILE: Final = "cookies_file"
ACCOUNT_UNIQUE_ID: Final = "youtube_account"

# Option: the shortest time between automatic feed reads (opening the card
# or the media browser, an HA start); Refresh always reads. Up to 7 days.
CONF_MIN_REFRESH: Final = "min_refresh_minutes"
DEFAULT_MIN_REFRESH: Final = 15

# Items read from the home feed; YouTube's first page holds about 30.
FEED_LIMIT: Final = 30
# Videos taken from a Mix (endless) or a playlist when it's played.
MIX_LIMIT: Final = 25
PLAYLIST_LIMIT: Final = 50
