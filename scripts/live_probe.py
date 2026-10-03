# Body of live_probe.sh; SRC (youtube.py source) and WHAT are prepended there.
import collections
import json
import sys
import types

mod = types.ModuleType("ytmod")
sys.modules["ytmod"] = mod
exec(compile(SRC, "ytmod", "exec"), mod.__dict__)  # noqa: F821, S102
with open("/config/.storage/core.config_entries", encoding="utf-8") as file:
    entries = json.load(file)["data"]["entries"]
# The account entry; before the move to youtube_account it was a youtube_on_tv
# entry with kind "account".
cookies = next(
    e
    for e in sorted(entries, key=lambda e: e["domain"] != "youtube_account")
    if e["domain"] == "youtube_account"
    or (e["domain"] == "youtube_on_tv" and e["data"].get("kind") == "account")
)["data"]["cookies"]
if WHAT == "feed":  # noqa: F821
    items, _, shorts = mod.fetch_feed(cookies, 30)
    print(
        "items",
        len(items),
        "shorts",
        shorts,
        dict(collections.Counter(i.kind for i in items)),
    )
    for i in items[:8]:
        print(
            i.kind,
            i.id,
            (i.title or "")[:40],
            "|",
            i.channel,
            "|",
            i.details,
            "|",
            i.duration,
            i.percent,
            i.live,
        )
else:
    items, _ = mod.fetch_watch_later(cookies)
    print(
        "videos",
        len(items),
        "with bar",
        sum(i.percent > 0 for i in items),
        ">=90",
        sum(i.percent >= 90 for i in items),
    )
    for i in items[:8]:
        print(
            i.id, (i.title or "")[:40], "|", i.details, "|", i.percent, bool(i.set_id)
        )
