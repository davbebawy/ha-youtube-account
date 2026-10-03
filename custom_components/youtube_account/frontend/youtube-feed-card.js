/*
 * YouTube feed card, shipped with the YouTube Account integration.
 *
 * Shows the signed-in home feed and Watch Later, "Continue watching", and
 * Now playing for one player at a time. Each video shows its views, age and
 * watched bar as youtube.com does. Tapping a thumbnail shows its actions as
 * icons on top of it; with a mouse, hovering does. Every action goes to the
 * player in Now playing: the one playing, else the last one picked there.
 * Account buttons call youtube_account.refresh_feed, .mark_watched,
 * .add_to_watch_later and .remove_from_watch_later. Play, Next and Queue
 * call youtube_account.play, which expands a Mix or playlist and calls
 * media_player.play_media on the YouTube on TV player. Resume and Move to
 * belong to the TV side: youtube_on_tv.resume and youtube_on_tv.transfer.
 *
 *   type: custom:youtube-feed-card
 *   players:                     # optional fixed list; default: every YouTube on TV
 *     - entity: media_player.youtube_on_tv   # player, found again on each update
 *       name: Apple TV
 *       open:                    # optional: how to open YouTube when it's off
 *         action: script.apple_tv_launch_app
 *         data: { source: YouTube }
 *   player_options:              # with no players list: name/open per found player
 *     media_player.youtube_on_tv: { name: Apple TV, open: { ... } }
 *   exclude: [media_player.x]    # with no players list: players to leave out
 *   layout: auto                 # auto | list | grid (auto: grid from 520 px)
 *   ios_browser: brave           # optional: "Here" links open in Brave on iPhone/iPad
 *   max_age: 900                 # read the feed again on open when older (s)
 *   clean_percent: 90            # Watch Later "Clean up" removes videos watched this far
 *   session: sensor.x            # last watched sensor; default: YouTube on TV's
 */

const DEFAULT_FEED = "sensor.youtube_account_home_feed";
// Used when no YouTube on TV last watched sensor is found.
const DEFAULT_SESSION = "sensor.youtube_account_last_watched";
const DEFAULT_WATCH_LATER = "sensor.youtube_account_watch_later";
// Card widths: the feed turns into a grid, then gains a side column.
// A landscape phone (about 750 px inside a pop-up) gets both.
const GRID_MIN_WIDTH = 520;
const SIDE_MIN_WIDTH = 720;
const FILTERS = [
  ["all", "All"],
  ["video", "Videos"],
  ["mix", "Mixes"],
  ["playlist", "Playlists"],
  ["later", "Watch Later"],
];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const clock = (seconds) => {
  if (seconds == null || isNaN(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
};

const ago = (iso) => {
  if (!iso) return "";
  const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
};

// iOS apps that open a link given to them; the link is percent-encoded.
const IOS_BROWSERS = {
  brave: "brave://open-url?url=",
  firefox: "firefox://open-url?url=",
};

const isIOS = () =>
  /iPhone|iPad|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

const ICON = {
  play: '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="M7 4v16l13-8z"/></svg>',
  next: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 5l9 7-9 7z"/><path d="M19 5v14"/></svg>',
  add: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  here: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>',
  later: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  remove: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  watched: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
  settings: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h9M19 6h1M4 12h3M13 12h7M4 18h11M21 18h-1"/><circle cx="16" cy="6" r="2.5"/><circle cx="10" cy="12" r="2.5"/><circle cx="18" cy="18" r="2.5"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
};

class YouTubeFeedCard extends HTMLElement {
  setConfig(config) {
    this._config = { layout: "auto", max_age: 900, clean_percent: 90, ...config };
    this._filter = "all";
    this._picked = null;
    this._busy = null;
    this._toast = null;
    this._confirm = false;
    this._settings = null; // the open settings panel: { value, saving, error }
    this._savedMins = null; // a saved minimum the feed sensor does not show yet
    this._refreshed = false;
    this._target = this._load("target");
    this._choice = null; // the player picked in Now playing on this visit
    this._np = {}; // Now playing clock per player: see _anchor
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // The feed redraws whole; players and the session change every few
    // seconds and redraw only their own parts, so thumbnails don't reload.
    const feedKey = this._feedKey();
    const liveKey = this._liveKey();
    if (feedKey !== this._lastFeedKey) {
      this._lastFeedKey = feedKey;
      this._lastLiveKey = liveKey;
      this._render();
    } else if (liveKey !== this._lastLiveKey) {
      this._lastLiveKey = liveKey;
      this._renderLive();
    }
    if (first) this._maybeRefresh();
  }

  connectedCallback() {
    this._observer = new ResizeObserver(() => {
      if (this._mode() !== this._shown) this._render();
    });
    this._observer.observe(this);
    // The Now playing clock runs here, in place; HA's reports only correct it.
    this._tick = setInterval(() => this._tickNp(), 1000);
    // A pop-up re-attaches the card each time it opens: read the feed again if it's old.
    this._refreshed = false;
    this._maybeRefresh();
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    clearInterval(this._tick);
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  static getStubConfig() {
    return {};
  }

  // Data

  _load(key) {
    try {
      return localStorage.getItem(`youtube-feed-card:${key}`);
    } catch (e) {
      return null;
    }
  }

  _save(key, value) {
    try {
      localStorage.setItem(`youtube-feed-card:${key}`, value);
    } catch (e) {
      /* private window: the choice lasts this visit only */
    }
  }

  _state(entityId) {
    return this._hass?.states?.[entityId];
  }

  _players() {
    if (this._config.players?.length) {
      return this._config.players.map((p) => (typeof p === "string" ? { entity: p } : p));
    }
    // Found again on every update, so an added or removed player shows at once.
    const entities = this._hass?.entities || {};
    const options = this._config.player_options || {};
    const exclude = this._config.exclude || [];
    return Object.keys(entities)
      .filter((id) => id.startsWith("media_player.") && entities[id].platform === "youtube_on_tv")
      .filter((id) => !entities[id].hidden && !exclude.includes(id) && this._state(id))
      .sort()
      .map((entity) => ({ ...options[entity], entity }));
  }

  // The last watched sensor belongs to YouTube on TV (resume is a TV action).
  _sessionId() {
    if (this._config.session) return this._config.session;
    const entities = this._hass?.entities || {};
    const found = Object.keys(entities).find(
      (id) =>
        id.startsWith("sensor.") &&
        entities[id].platform === "youtube_on_tv" &&
        (entities[id].translation_key === "last_session" || id.endsWith("_last_watched")),
    );
    return found || DEFAULT_SESSION;
  }

  _playerName(p) {
    return p.name || this._state(p.entity)?.attributes?.friendly_name?.replace(/^YouTube on /, "") || p.entity;
  }

  // The player every action goes to: picked on this visit, else the one
  // playing (the latest to start), else the last pick, else the first.
  _targetPlayer() {
    const players = this._players();
    const find = (id) => id && players.find((p) => p.entity === id);
    const playing = players
      .filter((p) => this._state(p.entity)?.state === "playing")
      .sort((a, b) => (this._state(a.entity).last_changed < this._state(b.entity).last_changed ? 1 : -1))[0];
    return find(this._choice) || playing || find(this._target) || players[0];
  }

  _keyOf(ids) {
    return ids.map((id) => {
      const s = this._state(id);
      return s ? `${s.state}|${s.last_updated}` : "-";
    }).join(";");
  }

  // What the feed list and header show. The player list itself is here too:
  // a player added or removed changes the layout.
  _feedKey() {
    const ids = [this._config.feed || DEFAULT_FEED, this._watchLaterId(), "binary_sensor.youtube_account_signed_in"];
    return `${this._keyOf(ids)}#${this._players().map((p) => p.entity).join(",")}`;
  }

  _liveKey() {
    return this._keyOf([this._sessionId(), ...this._players().map((p) => p.entity)]);
  }

  _isGrid() {
    if (this._config.layout === "grid") return true;
    if (this._config.layout === "list") return false;
    return this.clientWidth >= GRID_MIN_WIDTH;
  }

  // Continue watching and Now playing move to a side column on a wide grid.
  _hasSide() {
    return this._isGrid() && this.clientWidth >= SIDE_MIN_WIDTH;
  }

  _mode() {
    return `${this._isGrid()}|${this._hasSide()}`;
  }

  _maybeRefresh() {
    if (!this._hass || this._refreshed || !this.isConnected) return;
    this._refreshed = true;
    this._hass
      .callService("youtube_account", "refresh_feed", { max_age: this._config.max_age })
      .catch((err) => this._showToast(err.message || "Could not read the feed"));
  }

  // Actions

  async _call(domain, service, data, done) {
    this._busy = `${domain}.${service}`;
    this._applyBusy();
    try {
      await this._hass.callService(domain, service, data);
      if (done) this._showToast(done);
    } catch (err) {
      this._showToast(err.message || String(err));
    } finally {
      this._busy = null;
      this._applyBusy();
    }
  }

  // The minimum goes through the account's own options flow, the same form
  // as Settings > Devices & services > YouTube Account > gear.
  async _saveSettings() {
    const input = this.shadowRoot.querySelector(".settings input");
    const text = (input?.value ?? "").trim();
    const value = Number(text);
    if (!/^\d+$/.test(text) || value > 10080) {
      this._settings = { ...this._settings, value: input?.value, error: "Enter whole minutes from 0 to 10080." };
      return this._renderSettings();
    }
    this._settings = { value, saving: true, error: null };
    this._renderSettings();
    let flow;
    try {
      const entries = await this._hass.callWS({ type: "config_entries/get", domain: "youtube_account" });
      const account = entries[0];
      if (!account) throw new Error("No YouTube account entry found");
      flow = await this._hass.callApi("POST", "config/config_entries/options/flow", { handler: account.entry_id });
      const result = await this._hass.callApi("POST", `config/config_entries/options/flow/${flow.flow_id}`, { min_refresh_minutes: value });
      if (result.type !== "create_entry") throw new Error("The settings form did not accept the value");
      this._settings = null;
      this._savedMins = value;
      this._render();
      this._showToast(value ? `Reads again at most every ${value} min` : "Reads every time the feed opens");
    } catch (err) {
      if (flow?.flow_id) this._hass.callApi("DELETE", `config/config_entries/options/flow/${flow.flow_id}`).catch(() => {});
      this._settings = { value, saving: false, error: err.body?.message || err.message || String(err) };
      this._renderSettings();
    }
  }

  // Buttons marked data-busy wait while a call runs; set in place, no redraw.
  _applyBusy() {
    this.shadowRoot?.querySelectorAll("[data-busy]").forEach((el) => {
      el.disabled = !!this._busy;
    });
  }

  // Through the account, which turns a Mix or playlist into its videos.
  _playMedia(mediaId, enqueue, label) {
    const target = this._targetPlayer();
    if (!target) return this._showToast("No YouTube on TV player found");
    this._picked = null;
    this._call(
      "youtube_account",
      "play",
      { entity_id: target.entity, media: mediaId, enqueue },
      `${label} on ${this._playerName(target)}`,
    );
  }

  _open(player) {
    const open = player.open;
    if (!open) return;
    const [domain, service] = open.action.split(".");
    this._call(domain, service, open.data || {}, `Opening YouTube on ${this._playerName(player)}`);
  }

  _showToast(text) {
    this._toast = text;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toast = null;
      this._renderToast();
    }, 3500);
    this._renderToast();
  }

  _renderToast() {
    const slot = this.shadowRoot?.querySelector(".toast-slot");
    if (slot) slot.innerHTML = this._toast ? `<div class="toast" role="status">${esc(this._toast)}</div>` : "";
  }

  // Show or hide one item's action icons without redrawing the list.
  _pick(id) {
    const root = this.shadowRoot;
    const old = this._picked;
    this._picked = id;
    for (const itemId of [old, id]) {
      if (!itemId) continue;
      const thumb = [...root.querySelectorAll(".thumb[data-id]")].find((t) => t.dataset.id === itemId);
      const el = thumb?.closest(".item");
      if (!el) continue;
      el.querySelector(".ov")?.remove();
      const on = itemId === id;
      el.classList.toggle("picked", on);
      thumb.setAttribute("aria-expanded", String(on));
      if (on) {
        const item = this._items().find((i) => i.id === itemId);
        if (item) el.insertAdjacentHTML("beforeend", this._overlay(item));
      }
    }
    this._titles(root);
  }

  // Every button and link gets hover text: its label, else its words. Icon
  // buttons carry data-tip instead, shown at once by CSS.
  _titles(root) {
    root.querySelectorAll("button, a").forEach((el) => {
      if (!el.title && !el.dataset.tip) el.title = el.getAttribute("aria-label") || el.textContent.trim();
    });
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    const id = el.dataset.id;
    const items = this._items();
    const item = items.find((i) => i.id === id);
    const player = this._players().find((p) => p.entity === el.dataset.player);
    switch (act) {
      case "target":
        this._choice = this._target = el.dataset.player;
        this._save("target", this._target);
        this._renderLive();
        break;
      case "settings": {
        const mins = this._minRefresh(this._state(this._config.feed || DEFAULT_FEED));
        this._settings = this._settings ? null : { value: mins ?? 15, saving: false, error: null };
        this._renderSettings();
        this.shadowRoot.querySelector(".settings input")?.focus();
        break;
      }
      case "settings-save":
        this._saveSettings();
        break;
      case "settings-cancel":
        this._settings = null;
        this._renderSettings();
        break;
      case "settings-all":
        history.pushState(null, "", "/config/integrations/integration/youtube_account");
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
        break;
      case "filter":
        this._filter = el.dataset.filter;
        this._confirm = false;
        this._picked = null;
        this._render();
        break;
      case "remove":
        this._pick(null);
        this._call("youtube_account", "remove_from_watch_later", { videos: [id] }, "Removed from Watch Later");
        break;
      case "clean":
        this._confirm = true;
        this._renderClean();
        break;
      case "clean-cancel":
        this._confirm = false;
        this._renderClean();
        break;
      case "clean-yes": {
        // Exactly the videos the question counted, not a fresh pick on the server.
        const ids = this._finished().map((i) => i.id);
        this._confirm = false;
        this._call("youtube_account", "remove_from_watch_later", { videos: ids }, `Removed ${ids.length} from Watch Later`);
        break;
      }
      case "refresh":
        this._call("youtube_account", "refresh_feed", {}, "Feed updated");
        break;
      case "play":
        this._playMedia(id, "play", "Playing");
        break;
      case "next":
        this._playMedia(id, "next", "Playing next");
        break;
      case "add":
        this._playMedia(id, "add", "Added to the queue");
        break;
      case "first":
        this._playMedia(item?.video_id, "next", "First video plays next");
        break;
      case "watched":
        this._picked = null;
        this._call("youtube_account", "mark_watched", { video: id }, "Marked watched");
        break;
      case "pick":
        this._pick(this._picked === id ? null : id);
        break;
      case "unpick":
        if (!this._hover()) this._pick(null);
        break;
      case "save":
        this._pick(null);
        this._call("youtube_account", "add_to_watch_later", { video: id }, "Saved to Watch Later");
        break;
      case "resume":
        this._call("youtube_on_tv", "resume", { entity_id: player.entity }, `Resuming on ${this._playerName(player)}`);
        break;
      case "move":
        this._call(
          "youtube_on_tv",
          "transfer",
          { entity_id: el.dataset.from, target: player.entity },
          `Moved to ${this._playerName(player)}`,
        );
        break;
      case "open":
        this._open(player);
        break;
      default:
    }
  }

  // A youtube.com link for this device: through the configured iOS browser
  // on an iPhone or iPad, as is elsewhere.
  _hereUrl(url) {
    const prefix = IOS_BROWSERS[this._config.ios_browser];
    return prefix && isIOS() ? prefix + encodeURIComponent(url) : url;
  }

  _hereLink(url, label = "Open here") {
    return `<a class="act" href="${esc(this._hereUrl(url))}" target="_blank" rel="noopener">${label}</a>`;
  }

  _watchLaterId() {
    return this._config.watch_later || DEFAULT_WATCH_LATER;
  }

  // The items on show: the feed, or Watch Later (its videos have no kind).
  _items() {
    if (this._filter === "later") {
      return (this._state(this._watchLaterId())?.attributes?.items || []).map((i) => ({ ...i, kind: "video", later: true }));
    }
    return this._state(this._config.feed || DEFAULT_FEED)?.attributes?.items || [];
  }

  _inWatchLater(id) {
    return (this._state(this._watchLaterId())?.attributes?.items || []).some((i) => i.id === id);
  }

  _finished() {
    return this._items().filter((i) => i.later && i.percent >= this._config.clean_percent);
  }

  // Rendering

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    this._grid = this._isGrid();
    this._side = this._hasSide();
    this._shown = this._mode();
    const feed = this._state(this._config.feed || DEFAULT_FEED);
    const root = this.shadowRoot;
    if (!feed) {
      root.innerHTML = `${this._style()}<ha-card><div class="empty">No YouTube account yet. Add one: Settings &gt; Devices &amp; services &gt; Add integration &gt; YouTube Account.</div></ha-card>`;
      return;
    }
    const scroll = root.querySelector(".feed")?.scrollTop;
    root.innerHTML = `${this._style()}<ha-card class="${this._side ? "wide" : "narrow"}">
      <div class="layout">
        <div class="main">
          ${this._header(feed)}
          <div class="settings-slot">${this._settingsPanel()}</div>
          ${this._side ? "" : `<div class="live-continue">${this._continue()}</div><div class="live-np">${this._nowPlaying()}</div>`}
          ${this._filters(feed)}
          <div class="feed ${this._grid ? "grid" : "list"}">${this._feedItems()}</div>
        </div>
        ${this._side ? `<aside class="side"><div class="live-continue">${this._continue()}</div><div class="live-np">${this._nowPlaying()}</div></aside>` : ""}
      </div>
      <div class="toast-slot">${this._toast ? `<div class="toast" role="status">${esc(this._toast)}</div>` : ""}</div>
    </ha-card>`;
    this._titles(root);
    const card = root.querySelector("ha-card");
    card.addEventListener("click", (ev) => this._onClick(ev));
    card.addEventListener("input", (ev) => {
      if (this._settings && ev.target.matches?.(".settings input")) this._settings.value = ev.target.value;
    });
    // With a mouse, a video's actions show while the pointer is on it.
    card.addEventListener("mouseover", (ev) => {
      if (!this._hover()) return;
      const id = ev.target.closest?.(".item")?.querySelector(".thumb")?.dataset.id ?? null;
      if (id !== this._picked) this._pick(id);
    });
    card.addEventListener("mouseleave", () => {
      if (this._hover() && this._picked) this._pick(null);
    });
    root.querySelector("ha-card").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && ev.target.matches?.(".settings input")) {
        ev.preventDefault();
        this._saveSettings();
        return;
      }
      if ((ev.key === "Enter" || ev.key === " ") && ev.target.matches?.(".thumb")) {
        ev.preventDefault();
        this._onClick(ev);
      }
    });
    if (scroll) root.querySelector(".feed").scrollTop = scroll;
    this._tickNp();
  }

  _hover() {
    return window.matchMedia?.("(hover: hover) and (pointer: fine)").matches;
  }

  _renderSettings() {
    const el = this.shadowRoot?.querySelector(".settings-slot");
    if (!el) return this._render();
    el.innerHTML = this._settingsPanel();
    this._titles(this.shadowRoot);
  }

  _settingsPanel() {
    const st = this._settings;
    if (!st) return "";
    const off = st.saving ? "disabled" : "";
    return `<div class="hint settings">
      <label class="field"><span>Minimum time between automatic reads</span>
        <span class="input"><input type="number" min="0" max="10080" step="5" inputmode="numeric" value="${esc(st.value)}" ${off}> min</span></label>
      <div class="muted">Opening the card, a media browser or a restart reads YouTube again only after this long. Refresh always reads. 0 reads every time; most 10080 (7 days).</div>
      ${st.error ? `<div class="warn">${esc(st.error)}</div>` : ""}
      <span class="acts"><button class="act primary" data-act="settings-save" ${off}>${st.saving ? "Saving" : "Save"}</button><button class="act" data-act="settings-cancel" ${off}>Cancel</button><button class="link" data-act="settings-all">All settings</button></span>
    </div>`;
  }

  _renderClean() {
    const el = this.shadowRoot?.querySelector(".clean");
    if (!el) return this._render();
    el.outerHTML = this._cleanBar();
    this._titles(this.shadowRoot);
  }

  // Redraw only the parts that follow the players and the last session.
  _renderLive() {
    const root = this.shadowRoot;
    if (!root?.querySelector("ha-card")) return this._render();
    const parts = [
      [".live-continue", () => this._continue()],
      [".live-np", () => this._nowPlaying()],
    ];
    for (const [sel, html] of parts) {
      const el = root.querySelector(sel);
      if (!el) continue;
      const next = html();
      if (el._html !== next) {
        el.innerHTML = next;
        el._html = next;
      }
    }
    this._titles(root);
    this._applyBusy();
    this._tickNp();
  }

  // The option as saved here wins until the sensor reports the same number.
  _minRefresh(feed) {
    const mins = feed?.attributes?.min_refresh_minutes;
    if (this._savedMins !== null && mins === this._savedMins) this._savedMins = null;
    return this._savedMins ?? mins;
  }

  _header(feed) {
    const signedIn = this._state("binary_sensor.youtube_account_signed_in")?.state !== "off";
    const mins = this._minRefresh(feed);
    const status = feed.state === "unavailable"
      ? "Could not read the feed. Try Refresh."
      : `Updated ${ago(feed.attributes.updated_at)}${mins ? `. Reads again when opened ${mins} min after that, or on Refresh.` : ""}`;
    const settings = this._hass.user?.is_admin
      ? `<button class="icon" data-act="settings" aria-label="Feed settings" aria-expanded="${!!this._settings}" data-tip="Feed settings: minimum time between reads">${ICON.settings}</button>`
      : "";
    return `<div class="head">
      <div class="titles">
        <div class="title">Home feed</div>
        <div class="sub">${signedIn ? esc(status) : '<span class="warn">Signed out. Settings &gt; Repairs &gt; sign in again.</span>'}</div>
      </div>
      ${settings}
      <button class="icon" data-act="refresh" aria-label="Refresh feed" data-tip="Read the feed now" data-busy ${this._busy ? "disabled" : ""}>${ICON.refresh}</button>
    </div>`;
  }

  _offHint(player) {
    const name = esc(this._playerName(player));
    if (player.open) {
      return `<div class="hint">YouTube is closed on ${name}. <button class="link" data-act="open" data-player="${esc(player.entity)}">Open YouTube</button> first, then pick a video.</div>`;
    }
    return `<div class="hint">YouTube is closed on ${name}. Open it on the TV first.</div>`;
  }

  _filters(feed) {
    const shorts = feed.attributes.shorts_hidden;
    const later = this._filter === "later";
    return `<div class="chips">${FILTERS.map(([key, label]) => `<button class="chip ${this._filter === key ? "on" : ""}" data-act="filter" data-filter="${key}">${label}</button>`).join("")}
      ${shorts && !later ? `<span class="muted">${shorts} Shorts hidden</span>` : ""}</div>
      ${later ? this._cleanBar() : ""}`;
  }

  // Watch Later clean-up: the count first, then Remove or Cancel. YouTube's own
  // "Remove watched videos" drops every video with any progress.
  _cleanBar() {
    const all = this._items().length;
    const done = this._finished().length;
    const pct = this._config.clean_percent;
    const busy = `data-busy ${this._busy ? "disabled" : ""}`;
    if (this._confirm && done) {
      return `<div class="hint row clean">
        <span>Remove ${done} ${done === 1 ? "video" : "videos"} watched ${pct}% or more from Watch Later?</span>
        <span class="acts"><button class="act primary" data-act="clean-yes" ${busy}>Remove ${done}</button><button class="act" data-act="clean-cancel">Cancel</button></span>
      </div>`;
    }
    return `<div class="row clean">
      <span class="muted">${all} ${all === 1 ? "video" : "videos"}, ${done} watched ${pct}% or more</span>
      ${done ? `<button class="act fit" data-act="clean" ${busy}>Clean up ${pct}%</button>` : ""}
    </div>`;
  }

  _feedItems() {
    const later = this._filter === "later";
    const items = this._items().filter((i) => later || this._filter === "all" || i.kind === this._filter);
    if (!items.length) {
      const unread = later && this._state(this._watchLaterId())?.state === "unknown";
      return `<div class="empty">${unread ? "Watch Later is not read yet. Try Refresh." : "Nothing here. Try Refresh."}</div>`;
    }
    return items.map((i) => {
      const list = i.kind !== "video";
      const badge = i.kind === "mix" ? "MIX" : i.kind === "playlist" ? "PLAYLIST" : i.live ? "LIVE" : clock(i.duration);
      const sub = i.kind === "mix" ? "YouTube Mix" : [i.channel, i.details].filter(Boolean).map(esc).join(" &middot; ");
      const watched = i.percent > 0 ? `<div class="watched" aria-label="${i.percent}% watched"><span style="width:${Math.min(100, i.percent)}%"></span></div>` : "";
      const picked = this._picked === i.id;
      return `<div class="item ${esc(i.kind)} ${picked ? "picked" : ""}">
        <div class="thumb ${list ? "stack" : ""}" data-act="pick" data-id="${esc(i.id)}" role="button" tabindex="0" aria-expanded="${picked}" aria-label="Actions for ${esc(i.title || i.id)}">
          ${i.thumbnail ? `<img src="${esc(i.thumbnail)}" alt="" loading="lazy">` : ""}
          ${badge ? `<span class="badge ${esc(i.kind)} ${i.live ? "live" : ""}">${esc(badge)}</span>` : ""}
          ${watched}
        </div>
        <div class="meta">
          <div class="name" title="${esc(i.title)}">${esc(i.title || i.id)}</div>
          <div class="muted">${sub}</div>
        </div>
        ${picked ? this._overlay(i) : ""}
      </div>`;
    }).join("");
  }

  // The actions of one feed item, as icons on top of its thumbnail (the
  // whole row on a phone). Each icon's label says what it does.
  _overlay(i) {
    const btn = (act, icon, label, primary = false, id = i.id) =>
      `<button class="ov-btn ${primary ? "primary" : ""}" data-act="${act}" data-id="${esc(id)}" aria-label="${label}" data-tip="${label}" data-busy ${this._busy ? "disabled" : ""}>${icon}</button>`;
    const here = `<a class="ov-btn" href="${esc(this._hereUrl(i.url))}" target="_blank" rel="noopener" aria-label="Play on this device" data-tip="Play on this device">${ICON.here}</a>`;
    let buttons;
    if (i.kind === "video") {
      buttons = [
        btn("play", ICON.play, "Play now", true),
        btn("next", ICON.next, "Play next"),
        btn("add", ICON.add, "Add to queue"),
        here,
        i.later || this._inWatchLater(i.id)
          ? btn("remove", ICON.remove, "Remove from Watch Later")
          : btn("save", ICON.later, "Save to Watch Later"),
        i.later ? "" : btn("watched", ICON.watched, "Mark watched"),
      ];
    } else {
      const mix = i.kind === "mix";
      buttons = [
        btn("play", ICON.play, mix ? "Play mix now" : "Play all now", true),
        btn("add", ICON.add, mix ? "Add its first 25 videos to the queue" : "Add up to 50 videos to the queue"),
        i.video_id ? btn("first", ICON.next, "Play next: first video only") : "",
        here,
      ];
    }
    buttons = buttons.filter(Boolean);
    // One row when the tile is wide enough, else two even rows (CSS).
    return `<div class="ov ${buttons.length <= 4 ? "few" : ""}" data-act="unpick" style="--n:${buttons.length};--half:${Math.ceil(buttons.length / 2)}">${buttons.join("")}</div>`;
  }

  _continue() {
    const s = this._state(this._sessionId());
    const a = s?.attributes;
    if (!a?.video_id || a.playing) return "";
    const pct = a.duration ? Math.min(100, (a.position / a.duration) * 100) : 0;
    const left = a.queue_left ? ` ${a.queue_left} more in its queue.` : "";
    const target = this._targetPlayer();
    const buttons = target ? `<button class="act primary" data-act="resume" data-player="${esc(target.entity)}">Resume on ${esc(this._playerName(target))}</button>` : "";
    return `<div class="panel">
      <div class="cap">Continue watching</div>
      <div class="name">${esc(s.state)}</div>
      ${this._bar(pct)}
      <div class="muted">${clock(a.position)}${a.duration ? ` of ${clock(a.duration)}` : ""}. Stopped on ${esc(a.device || "a TV")}, ${esc(ago(a.stopped_at))}.${left}</div>
      <div class="acts wrap">${buttons}${this._hereLink(a.url)}</div>
    </div>`;
  }

  _bar(pct) {
    return `<div class="bar"><span style="width:${pct.toFixed(1)}%"></span><span></span></div>`;
  }

  // Now playing: the target player only, a switch to the others, and Move to.
  // Position, bar and link are left empty here and filled each second by _tickNp,
  // so this HTML changes only when something real changes.
  _nowPlaying() {
    const players = this._players();
    const p = this._targetPlayer();
    if (!p) return "";
    const segs = players.length > 1
      ? `<div class="segs">${players.map((o) => `<button class="seg ${o.entity === p.entity ? "on" : ""}" data-act="target" data-player="${esc(o.entity)}">${esc(this._playerName(o))}</button>`).join("")}</div>`
      : "";
    const s = this._state(p.entity);
    const a = s?.attributes || {};
    const name = esc(this._playerName(p));
    let panel;
    if (!s || ["off", "unavailable", "unknown"].includes(s.state)) {
      panel = this._offHint(p);
    } else if (s.state === "idle" || !a.media_content_id) {
      panel = `<div class="panel row"><span class="strong">${name}</span><span class="muted">Nothing playing</span></div>`;
    } else {
      const others = players.filter((o) => o.entity !== p.entity);
      panel = `<div class="panel" data-np="${esc(p.entity)}">
        <div class="row"><span class="strong">${name}</span><span class="state">${esc(s.state)}</span></div>
        <div class="name">${esc(a.media_title || a.media_content_id)}</div>
        <div class="bar"><span class="np-fill"></span><span></span></div>
        <div class="muted mono np-time"></div>
        <div class="acts wrap">${others.map((o) => `<button class="act primary" data-act="move" data-from="${esc(p.entity)}" data-player="${esc(o.entity)}">Move to ${esc(this._playerName(o))}</button>`).join("")}
          <a class="act np-here" href="#" target="_blank" rel="noopener">Open here</a></div>
      </div>`;
    }
    return `<div class="block"><div class="cap np">Now playing</div>${segs}${panel}</div>`;
  }

  // The Now playing clock of one player: position and rate at a time. It runs
  // on its own and moves only when a report from HA disagrees by 1.5 s or more.
  // The rate is the player's speed attribute when it has one, else measured
  // from two reports (the TV's own app can play at 2x without telling the
  // YouTube remote protocol, which then reports speed 1).
  _anchor(entity) {
    const s = this._state(entity);
    const a = s?.attributes || {};
    if (!a.media_content_id) return null;
    const at = a.media_position_updated_at ? new Date(a.media_position_updated_at).getTime() : Date.now();
    const pos = Number(a.media_position) || 0;
    const playing = s.state === "playing";
    const key = `${a.media_content_id}|${s.state}`;
    const old = this._np[entity];
    if (old && old.key === key && old.reportAt === at) return old;
    const same = old && old.key === key;
    const report = { reportAt: at, reportPos: pos, dur: a.media_duration };
    const given = Number(a.speed ?? a.playback_speed) || 0;
    if (same && (!given || given === old.rate) && Math.abs(pos - this._posAt(old, at)) < 1.5) {
      return (this._np[entity] = { ...old, ...report });
    }
    let rate = given;
    if (!rate && same && playing && at - old.reportAt >= 3000) {
      const r = (pos - old.reportPos) / ((at - old.reportAt) / 1000);
      if (r >= 0.2 && r <= 4.5) rate = Math.round(r * 4) / 4;
    }
    if (!rate) rate = old && old.vid === a.media_content_id ? old.rate : 1;
    return (this._np[entity] = { key, vid: a.media_content_id, pos, at, rate, playing, ...report });
  }

  _posAt(n, t = Date.now()) {
    const p = n.pos + (n.playing ? ((t - n.at) / 1000) * n.rate : 0);
    return n.dur ? Math.min(p, n.dur) : p;
  }

  _tickNp() {
    const panel = this.shadowRoot?.querySelector("[data-np]");
    if (!panel) return;
    const n = this._anchor(panel.dataset.np);
    if (!n) return;
    const pos = this._posAt(n);
    panel.querySelector(".np-fill").style.width = `${n.dur ? Math.min(100, (pos / n.dur) * 100).toFixed(2) : 0}%`;
    panel.querySelector(".np-time").textContent = `${clock(pos)} / ${clock(n.dur)}${n.rate !== 1 ? `  ${n.rate}x` : ""}`;
    const here = panel.querySelector(".np-here");
    if (here) here.href = this._hereUrl(`https://www.youtube.com/watch?v=${encodeURIComponent(n.vid)}&t=${Math.floor(pos)}s`);
  }

  _style() {
    return `<style>
      :host { display: block; --yt-accent: var(--primary-color, #2563eb); --yt-surface: var(--secondary-background-color, #141414); --yt-muted: var(--secondary-text-color, #a8a8a8); }
      ha-card { position: relative; padding: 16px; overflow: hidden; }
      button, a.act { font: inherit; }
      .layout { display: flex; gap: 20px; }
      .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
      .side { width: clamp(260px, 32%, 340px); flex-shrink: 0; display: flex; flex-direction: column; gap: 12px; }
      .head { display: flex; align-items: center; gap: 12px; }
      .titles { flex: 1; min-width: 0; }
      .title { font-size: 20px; font-weight: 600; }
      .sub, .muted { font-size: 12px; color: var(--yt-muted); }
      .warn { color: var(--warning-color, #f59e0b); }
      .cap { font-size: 12px; color: var(--yt-muted); letter-spacing: .04em; text-transform: uppercase; }
      .cap.np { margin-top: 4px; }
      .block { display: flex; flex-direction: column; gap: 6px; }
      button.icon { width: 44px; height: 44px; border: 0; border-radius: 22px; background: var(--yt-surface); color: var(--primary-text-color); display: flex; align-items: center; justify-content: center; cursor: pointer; }
      button:disabled { opacity: .5; }
      .segs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--yt-surface); border-radius: 12px; }
      .seg { flex: 1 1 auto; min-height: 40px; padding: 0 10px; border: 0; border-radius: 9px; background: transparent; color: var(--yt-muted); font-weight: 500; cursor: pointer; }
      .seg.on { background: var(--primary-text-color); color: var(--card-background-color, #000); }
      .hint { font-size: 13px; line-height: 1.4; color: var(--primary-text-color); background: var(--yt-surface); border-radius: 10px; padding: 10px 12px; }
      .settings-slot:empty { display: none; }
      .settings { display: flex; flex-direction: column; gap: 8px; }
      .settings .field { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; font-weight: 500; }
      .settings .input { display: inline-flex; align-items: center; gap: 6px; }
      .settings input { width: 90px; min-height: 36px; padding: 0 8px; border: 1px solid var(--divider-color, #444); border-radius: 8px; background: var(--card-background-color, #1f1f1f); color: var(--primary-text-color); font: inherit; }
      .settings .acts { display: flex; gap: 8px; align-items: center; }
      .settings .acts .act { flex: 0 0 auto; padding: 0 16px; }
      .link { border: 0; background: none; color: var(--yt-accent); font-weight: 600; padding: 0; cursor: pointer; text-decoration: underline; }
      .chips { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      .chip { min-height: 36px; padding: 0 14px; border-radius: 18px; border: 1px solid var(--divider-color, #2e2e2e); background: var(--yt-surface); color: var(--primary-text-color); cursor: pointer; }
      .chip.on { background: var(--yt-accent); border-color: var(--yt-accent); color: var(--text-primary-color, #fff); }
      .feed.list { display: flex; flex-direction: column; gap: 12px; }
      .feed.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 18px; }
      .item { position: relative; container-type: inline-size; background: var(--yt-surface); border-radius: 16px; padding: 10px; display: grid; grid-template-columns: 136px minmax(0, 1fr); grid-template-areas: "thumb meta"; gap: 10px 12px; }
      .grid .item { background: none; padding: 0; grid-template-columns: minmax(0, 1fr); grid-template-areas: "thumb" "meta"; gap: 8px; }
      .thumb { grid-area: thumb; position: relative; min-width: 0; aspect-ratio: 16 / 9; border-radius: 10px; background: #2b3a4a; cursor: pointer; -webkit-tap-highlight-color: transparent; }
      .thumb:focus-visible { outline: 2px solid var(--yt-accent); outline-offset: 2px; }
      .ov { --cols: var(--half); position: absolute; z-index: 2; inset: 0; border-radius: 16px; background: rgba(0,0,0,.72); -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px); display: grid; grid-template-columns: repeat(var(--cols), auto); align-content: center; justify-content: center; gap: 10px; padding: 6px; animation: ov-in .12s ease-out; }
      .grid .ov { bottom: auto; aspect-ratio: 16 / 9; border-radius: 10px; gap: 6px; }
      .ov.few { --cols: var(--n); }
      @container (min-width: 270px) { .ov { --cols: var(--n); } }
      [data-tip] { position: relative; }
      [data-tip]:hover::after, [data-tip]:focus-visible::after { content: attr(data-tip); position: absolute; z-index: 5; bottom: calc(100% + 6px); left: 50%; transform: translateX(-50%); padding: 4px 8px; border-radius: 6px; background: rgba(0,0,0,.92); color: #fff; font-size: 12px; font-weight: 500; line-height: 1.3; white-space: nowrap; pointer-events: none; }
      .head [data-tip]:hover::after, .head [data-tip]:focus-visible::after { bottom: auto; top: calc(100% + 6px); left: auto; right: 0; transform: none; }
      @keyframes ov-in { from { opacity: 0; } }
      .ov-btn { flex: 0 0 auto; width: 48px; height: 48px; padding: 0; border: 0; border-radius: 24px; background: rgba(255,255,255,.16); color: #fff; display: flex; align-items: center; justify-content: center; cursor: pointer; text-decoration: none; }
      .grid .ov-btn { width: 38px; height: 38px; border-radius: 19px; }
      .ov-btn svg { width: 22px; height: 22px; }
      .grid .ov-btn svg { width: 19px; height: 19px; }
      .ov-btn.primary { background: var(--yt-accent); color: var(--text-primary-color, #fff); }
      .ov-btn:disabled { opacity: .5; }
      .thumb img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }
      .thumb.stack::before { content: ""; position: absolute; left: 8px; right: 8px; top: -5px; height: 10px; border-radius: 8px 8px 0 0; background: #555; }
      .badge { position: absolute; right: 6px; bottom: 6px; padding: 2px 6px; border-radius: 6px; font-size: 11px; font-weight: 600; font-family: ui-monospace, monospace; color: #fff; background: rgba(0,0,0,.8); }
      .badge.mix { background: #c2410c; } .badge.playlist { background: #1d4ed8; } .badge.live { background: #dc2626; }
      .watched { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: rgba(255,255,255,.35); border-radius: 0 0 10px 10px; overflow: hidden; }
      .watched span { display: block; height: 100%; background: #f00; }
      .clean { gap: 10px; flex-wrap: wrap; }
      .act.fit { flex: 0 0 auto; padding: 0 14px; background: var(--yt-surface); }
      .meta { grid-area: meta; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
      .name { font-size: 15px; font-weight: 500; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
      .acts { grid-area: acts; display: flex; gap: 8px; }
      .acts.wrap { flex-wrap: wrap; }
      .act { flex: 1 1 0; min-height: 44px; padding: 0 8px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 12px; background: var(--card-background-color, #1f1f1f); color: var(--primary-text-color); font-size: 13px; font-weight: 500; cursor: pointer; text-decoration: none; white-space: nowrap; }
      .act.primary { background: var(--yt-accent) !important; color: var(--text-primary-color, #fff); }
      .panel { background: var(--yt-surface); border: 1px solid var(--divider-color, #2a2a2a); border-radius: 16px; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
      .panel.row, .row { display: flex; justify-content: space-between; align-items: center; flex-direction: row; }
      .strong { font-size: 13px; font-weight: 600; }
      .state { font-size: 12px; color: var(--success-color, #86efac); }
      .mono { font-family: ui-monospace, monospace; }
      .bar { display: flex; gap: 3px; height: 4px; }
      .bar span:first-child { background: var(--yt-accent); border-radius: 2px; }
      .np-fill { transition: width 1s linear; }
      .bar span:last-child { flex: 1; background: var(--divider-color, #3a3a3a); border-radius: 2px; }
      .empty { padding: 16px; color: var(--yt-muted); font-size: 14px; }
      .toast { position: fixed; z-index: 12; left: 50%; bottom: 16px; transform: translateX(-50%); max-width: calc(100% - 32px); background: var(--primary-text-color); color: var(--card-background-color, #000); padding: 10px 14px; border-radius: 10px; font-size: 13px; box-shadow: 0 4px 16px rgba(0,0,0,.4); }
      .narrow .layout { display: block; }
    </style>`;
  }
}

const defineCard = () => {
  if (customElements.get("youtube-feed-card")) return;
  try {
    customElements.define("youtube-feed-card", YouTubeFeedCard);
  } catch (e) {
    return;
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "youtube-feed-card")) {
    window.customCards.push({
      type: "youtube-feed-card",
      name: "YouTube feed",
      description: "Home feed, Watch Later, continue watching and now playing, from YouTube Account.",
    });
  }
};

// Home Assistant imports this file before its app.js, and app.js (frontend
// 2026.9) installs a scoped custom element registry polyfill. A card defined
// before that is invisible to the polyfill, so dashboards show "Configuration
// error". Define now, then again whenever the polyfill cannot see the card,
// until the page has settled.
defineCard();
customElements.whenDefined("home-assistant").then(defineCard);
let checks = 0;
const recheck = setInterval(() => {
  defineCard();
  if (++checks >= 40) clearInterval(recheck);
}, 250);
