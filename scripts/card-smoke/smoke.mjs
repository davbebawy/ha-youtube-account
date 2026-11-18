// Feed card smoke test in happy-dom: renders, clicks through, and checks that a
// player update redraws only the player parts (the #youtube pop-up flashed every
// 5 s when it rebuilt everything). Run: cd scripts/card-smoke && pnpm install && pnpm test
// happy-dom gotchas: ~/.claude/notes/node-tooling.md, happy-dom section.
import { Window } from "happy-dom";
import { readFileSync } from "fs";
import assert from "node:assert/strict";

const w = new Window({ width: 1200 });
for (const k of ["document", "customElements", "HTMLElement", "navigator", "localStorage"]) {
  Object.defineProperty(globalThis, k, { value: w[k], configurable: true, writable: true });
}
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.window = w;
eval(readFileSync(new URL("../../custom_components/youtube_account/frontend/youtube-feed-card.js", import.meta.url), "utf8"));

const P = "media_player.youtube_on_tv";
const st = (state, attributes, lu = "1") => ({ state, attributes, last_updated: lu });
const calls = [];
const base = {
  "sensor.youtube_account_home_feed": st("2", { updated_at: new Date().toISOString(), items: [
    { kind: "video", id: "v1", title: "Vid", channel: "Chan", details: "1.5M views", percent: 42, duration: 511, thumbnail: "t1", url: "u" },
    { kind: "mix", id: "RDx", title: "Mix", channel: "A", percent: 0, thumbnail: "t2", url: "u", video_id: "x" } ] }),
  "sensor.youtube_account_watch_later": st("3", { items: [
    { id: "a", title: "A", channel: "C", percent: 100, duration: 60, url: "u" },
    { id: "b", title: "B", channel: "C", percent: 50, duration: 60, url: "u" },
    { id: "c", title: "C", channel: "C", percent: 92, duration: 60, url: "u" } ] }),
};
const hass = (pos, lu) => ({
  callService: async (...a) => { calls.push(a); },
  entities: { [P]: { platform: "youtube_on_tv" } },
  states: { ...base, [P]: st("playing", { media_content_id: "v1", media_title: "Vid", media_position: pos, media_duration: 511, media_position_updated_at: new Date().toISOString(), friendly_name: "YouTube on TV" }, lu) },
});

const card = document.createElement("youtube-feed-card");
Object.defineProperty(card, "clientWidth", { get: () => 900 });
card.setConfig({});
document.body.appendChild(card);
card.hass = hass(10, "1");
const r = card.shadowRoot;
const click = (el) => el.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
const settle = () => new Promise((res) => setTimeout(res, 10));

const img = r.querySelector(".thumb img");
assert.match(r.querySelector(".meta .muted").innerHTML, /Chan .* 1\.5M views/);
assert.equal(r.querySelectorAll(".watched").length, 1);
card.hass = hass(15, "2");
assert.equal(r.querySelector(".thumb img"), img, "player update rebuilt the list");
assert.equal([...r.querySelectorAll("button, a")].filter((e) => !e.title && !e.dataset.tip).length, 0, "button without hover text");

click(r.querySelector('.thumb[data-id="v1"]'));
assert.equal(r.querySelector(".thumb img"), img, "pick rebuilt the list");
click(r.querySelector('[data-act="save"]'));
// Saved: off home at once, before Watch Later is read again.
assert.equal(r.querySelector('.thumb[data-id="v1"]'), null, "saved video still on home");
await settle();
assert.deepEqual(calls.at(-1), ["youtube_account", "add_to_watch_later", { video: "v1" }]);
assert.equal(r.querySelector(".chip[data-filter=later]").textContent, "Watch Later 3");

click(r.querySelector('[data-filter="later"]'));
assert.equal(r.querySelectorAll(".item").length, 3);
click(r.querySelector('[data-act="clean"]'));
assert.match(r.querySelector(".clean").textContent, /Remove 2 videos watched 90%/);
click(r.querySelector('[data-act="clean-yes"]'));
await settle();
assert.deepEqual(calls.at(-1), ["youtube_account", "remove_from_watch_later", { videos: ["a", "c"] }]);
// Play on a Watch Later video queues the videos below it, as one list.
card._pick("b");
click(r.querySelector('[data-act="play"]'));
await settle();
assert.deepEqual(calls.at(-1), ["media_player", "play_media", { entity_id: P, media_content_type: "playlist", media_content_id: "b,c", enqueue: "play" }]);
// The last video has nothing below it: a plain play.
card._pick("c");
click(r.querySelector('.thumb[data-id="c"]').closest(".item").querySelector('[data-act="play"]'));
await settle();
assert.deepEqual(calls.at(-1), ["youtube_account", "play", { entity_id: P, media: "c", enqueue: "play" }]);
// Watch Later rows drag; a drop to the top sends no after, else the one before.
assert.equal(r.querySelectorAll('.feed[data-drag-list="later"] > .item[data-drag-id] > .drag').length, 3, "Watch Later grips");
await card._drop("later", "c", "a", true);
assert.deepEqual(calls.at(-1), ["youtube_account", "move_in_watch_later", { video: "c" }]);
await card._drop("later", "a", "c", false);
assert.deepEqual(calls.at(-1), ["youtube_account", "move_in_watch_later", { video: "a", after: "c" }]);
const before = calls.length;
await card._drop("later", "b", "a", false);
assert.equal(calls.length, before, "a drop in place sent a move");
// Now playing: the player that plays is the target; a pick there wins for the visit.
const Q = "media_player.youtube_on_den";
const two = (aState, qState) => ({
  ...hass(10, "3"),
  entities: { [P]: { platform: "youtube_on_tv" }, [Q]: { platform: "youtube_on_tv" } },
  states: { ...hass(10, "3").states,
    [P]: st(aState, { media_content_id: "v1", media_title: "Vid", media_position: 10, media_duration: 511, media_position_updated_at: new Date().toISOString() }, "4"),
    [Q]: st(qState, { friendly_name: "YouTube on Den" }, "4") },
});
click(r.querySelector('[data-filter="all"]'));
card.hass = two("idle", "playing");
assert.equal(card._targetPlayer().entity, Q, "playing player is not the target");
click(r.querySelector(`.seg[data-player="${P}"]`));
assert.equal(card._targetPlayer().entity, P, "pick in Now playing ignored");
card._pick("RDx");
click(r.querySelector('[data-act="play"]'));
await settle();
// Play goes through the account, which expands lists and calls play_media.
assert.deepEqual(calls.at(-1), ["youtube_account", "play", { entity_id: P, media: "RDx", enqueue: "play" }]);
// The last watched sensor is found on the TV side.
card._hass = { ...two("idle", "idle"), entities: { [P]: { platform: "youtube_on_tv" },
  "sensor.youtube_on_tv_last_watched": { platform: "youtube_on_tv", translation_key: "last_session" } } };
assert.equal(card._sessionId(), "sensor.youtube_on_tv_last_watched");
card._hass = two("idle", "idle");
assert.equal(card._sessionId(), "sensor.youtube_account_last_watched");

// The clock: a 2x player reporting speed 1 is measured once, then runs without jumps.
const t0 = Date.parse("2026-10-02T12:00:00Z");
const rep = (pos, dt) => ({ ...hass(0, "5"), states: { ...hass(0, "5").states,
  [P]: st("playing", { media_content_id: "v1", media_position: pos, media_duration: 511, media_position_updated_at: new Date(t0 + dt * 1000).toISOString() }, String(dt)) } });
card._np = {};
card._hass = rep(100, 0); const a0 = card._anchor(P);
card._hass = rep(120, 10); const a1 = card._anchor(P);
assert.equal(a1.rate, 2, "2x not measured");
card._hass = rep(140, 20); const a2 = card._anchor(P);
assert.equal(a2.at, a1.at, "a report that agrees moved the clock");
assert.equal(Math.round(card._posAt(a2, t0 + 25000)), 150);
card._hass = rep(400, 30); const a3 = card._anchor(P);
assert.equal(a3.pos, 400, "a seek did not move the clock");
// Settings: the gear opens an editor in the card; Save runs the account's options flow.
const api = [];
const admin = { ...hass(10, "6"), user: { is_admin: true },
  callWS: async (msg) => (msg.domain === "youtube_account" ? [{ entry_id: "acct", supports_options: true }] : []),
  callApi: async (m, path, body) => { api.push([m, path, body]); return path.endsWith("/flow") ? { flow_id: "f1", type: "form" } : { type: "create_entry" }; } };
admin.states["sensor.youtube_account_home_feed"] = st("2", { ...base["sensor.youtube_account_home_feed"].attributes, min_refresh_minutes: 15 }, "6");
card.hass = admin;
click(r.querySelector('[data-act="settings"]'));
const box = r.querySelector(".settings input");
assert.equal(box.value, "15");
box.value = "abc";
click(r.querySelector('[data-act="settings-save"]'));
assert.ok(r.querySelector(".settings .warn"), "bad value accepted");
r.querySelector(".settings input").value = "120";
click(r.querySelector('[data-act="settings-save"]'));
await settle();
assert.deepEqual(api, [["POST", "config/config_entries/options/flow", { handler: "acct" }],
  ["POST", "config/config_entries/options/flow/f1", { min_refresh_minutes: 120 }]]);
assert.equal(r.querySelector(".settings"), null, "panel stayed open after save");
// The sensor still says 15 (HA has not redrawn it): the card shows the saved 120.
assert.match(r.querySelector(".head .sub").textContent, /120 min/);
click(r.querySelector('[data-act="settings"]'));
assert.equal(r.querySelector(".settings input").value, "120", "box shows the old value after a save");
click(r.querySelector('[data-act="settings-cancel"]'));

// Queue, hide on add, More videos: a fresh card with a queue list and a failing call.
const Qd = "todo.youtube_on_tv_queue";
const subs = [];
let fail = false;
const qcalls = [];
const ws = [];
const qhass = (lu = "7") => ({
  callWS: async (m) => { ws.push(m); },
  callService: async (...a) => { qcalls.push(a); if (fail) throw new Error("TV is off"); },
  connection: { subscribeMessage: async (cb, msg) => { subs.push({ cb, msg }); return () => { subs.find((x) => x.cb === cb).off = true; }; } },
  entities: { [P]: { platform: "youtube_on_tv", device_id: "d1" }, [Qd]: { platform: "youtube_on_tv", device_id: "d1" } },
  states: {
    "sensor.youtube_account_home_feed": st("3", { updated_at: new Date().toISOString(), more: true, items: [
      { kind: "video", id: "v1", title: "One", url: "u" },
      { kind: "video", id: "v2", title: "Two", url: "u" },
      { kind: "video", id: "a", title: "In Watch Later", url: "u" } ] }, lu),
    "sensor.youtube_account_watch_later": st("1", { items: [{ id: "a", title: "A", percent: 0, url: "u" }] }, lu),
    [P]: st("playing", { media_content_id: "v9", media_title: "Nine", media_position: 1, media_duration: 60, media_position_updated_at: new Date().toISOString() }, lu),
    [Qd]: st("2", {}, lu),
  },
});
const c2 = document.createElement("youtube-feed-card");
Object.defineProperty(c2, "clientWidth", { get: () => 900 });
c2.setConfig({});
document.body.appendChild(c2);
c2.hass = qhass();
const r2 = c2.shadowRoot;
const ids = () => [...r2.querySelectorAll(".feed .thumb")].map((t) => t.dataset.id);
assert.deepEqual(ids(), ["v1", "v2"], "a Watch Later video shows on home");
await settle();
assert.deepEqual(subs[0]?.msg, { type: "todo/item/subscribe", entity_id: Qd }, "queue list not followed");
subs[0].cb({ items: [
  { uid: "v8", summary: "Eight", description: "Chan", status: "completed" },
  { uid: "v9", summary: "Nine", description: "Now playing - Chan", status: "needs_action" },
  { uid: "v2", summary: "Two", description: "Chan2", status: "needs_action" } ] });
assert.deepEqual(ids(), ["v1"], "a queued video shows on home");
assert.match(r2.querySelector(".live-queue").textContent, /Queue on .* 1 up next/);
assert.equal(r2.querySelectorAll(".q-row").length, 2, "played video shown in the queue");
assert.equal(r2.querySelectorAll(".q-row [data-act=unqueue]").length, 1, "Remove on the playing video");
click(r2.querySelector(".q-row [data-act=unqueue]"));
await settle();
assert.deepEqual(qcalls.at(-1), ["todo", "remove_item", { entity_id: Qd, item: "v2" }]);
// Add to queue that fails: the tile leaves at once and comes back.
fail = true;
c2._pick("v1");
click(r2.querySelector('[data-act="add"]'));
assert.deepEqual(ids(), [], "queued tile still on home");
await settle();
assert.deepEqual(ids(), ["v1"], "tile not back after a failed add");
fail = false;
c2._pick("v1");
click(r2.querySelector('[data-act="add"]'));
await settle();
assert.deepEqual(qcalls.at(-1), ["youtube_account", "play", { entity_id: P, media: "v1", enqueue: "add" }]);
assert.deepEqual(ids(), [], "queued tile back on home");
click(r2.querySelector('[data-act="more"]'));
await settle();
assert.deepEqual(qcalls.at(-1), ["youtube_account", "load_more", {}]);
c2.hass = { ...qhass("8"), states: { ...qhass("8").states, "sensor.youtube_account_home_feed": st("3", { updated_at: new Date().toISOString(), more: false, items: [] }, "8") } };
assert.equal(r2.querySelector('[data-act="more"]'), null, "More shown at the end of the feed");
// Queue rows drag (not the playing one); never before the playing video.
subs[0].cb({ items: [
  { uid: "v8", summary: "Eight", description: "Chan", status: "completed" },
  { uid: "v9", summary: "Nine", description: "Now playing - Chan", status: "needs_action" },
  { uid: "v2", summary: "Two", description: "Chan2", status: "needs_action" },
  { uid: "v3", summary: "Three", description: "Chan3", status: "needs_action" } ] });
assert.equal(r2.querySelectorAll('.queue[data-drag-list="queue"] > .q-row[data-drag-id] .drag').length, 2, "queue grips");
await c2._drop("queue", "v3", "v2", true);
assert.deepEqual(ws.at(-1), { type: "todo/item/move", entity_id: Qd, uid: "v3", previous_uid: "v9" });
assert.deepEqual([...r2.querySelectorAll(".q-row")].map((e) => e.dataset.dragId), ["v9", "v3", "v2"], "new order not shown");
await c2._drop("queue", "v2", "v9", true);
assert.deepEqual(ws.at(-1), { type: "todo/item/move", entity_id: Qd, uid: "v2", previous_uid: "v9" });
c2.remove();
await settle();
assert.ok(subs[0].off, "queue subscription left open");
// YouTube closed on a player with an open action: open it, wait, then play.
const oc = [];
let tvState = "off";
const ohass = () => ({
  callService: async (...a) => { oc.push(a); },
  entities: { [P]: { platform: "youtube_on_tv" } },
  states: { ...base, [P]: st(tvState, { friendly_name: "YouTube on TV" }, tvState) },
});
const c3 = document.createElement("youtube-feed-card");
Object.defineProperty(c3, "clientWidth", { get: () => 900 });
c3.setConfig({ player_options: { [P]: { name: "Apple TV", open: { action: "script.apple_tv_launch_app", data: { source: "YouTube" } } } } });
document.body.appendChild(c3);
c3.hass = ohass();
c3._pick("v1");
click(c3.shadowRoot.querySelector('[data-act="play"]'));
await settle();
assert.deepEqual(oc.at(-1), ["script", "apple_tv_launch_app", { source: "YouTube" }], "YouTube not opened first");
assert.equal(oc.filter((c) => c[1] === "play").length, 0, "played before YouTube opened");
tvState = "idle";
c3.hass = ohass();
await new Promise((res) => setTimeout(res, 3000));
assert.deepEqual(oc.at(-1), ["youtube_account", "play", { entity_id: P, media: "v1", enqueue: "play" }]);
// Idle (screensaver or background) also opens YouTube first.
oc.length = 0;
c3._pick("v1");
click(c3.shadowRoot.querySelector('[data-act="play"]'));
await settle();
assert.deepEqual(oc[0], ["script", "apple_tv_launch_app", { source: "YouTube" }], "idle player not opened first");
await new Promise((res) => setTimeout(res, 2500));
assert.deepEqual(oc.at(-1), ["youtube_account", "play", { entity_id: P, media: "v1", enqueue: "play" }]);
c3.remove();
console.log("card smoke: ok");
process.exit(0);
