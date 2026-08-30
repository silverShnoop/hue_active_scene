/**
 * hue-scene-rail
 *
 * A single-row scene rail for one Hue room.
 *
 *  - The adaptive "all day" smart scene is a toggle at the left.
 *  - Every other scene is a coloured icon button.
 *  - Whichever scene is live expands to show its name; the rest stay icon-only.
 *  - Dragging anywhere along the rail dims, and only touches the lights the
 *    scene actually left on — not the whole room group.
 *
 * Colours come from `schedule_sensor`'s timeslots where a name matches, so the
 * rail stays in step with whatever the bridge reports. Everything else is
 * themed with CSS custom properties, so it follows light/dark.
 */

const DRAG_THRESHOLD_PX = 8;
const THROTTLE_MS = 150;
const MIN_BRIGHTNESS_PCT = 1;

class HueSceneRail extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._drag = null;
    this._lastSent = 0;
    this._pendingPct = null;
  }

  setConfig(config) {
    if (!config || !Array.isArray(config.scenes) || config.scenes.length === 0) {
      throw new Error('hue-scene-rail: "scenes" must be a non-empty list');
    }
    if (!config.light) {
      throw new Error('hue-scene-rail: "light" (the room group entity) is required');
    }
    this._config = {
      name: "",
      auto_label: "Auto",
      auto_icon: "mdi:brightness-auto",
      dim: true,
      ...config,
    };
    this._built = false;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
  }

  getCardSize() {
    return 1;
  }

  /* ---------------------------------------------------------------- state */

  /** Scene colours keyed by scene name, taken from the schedule sensor. */
  _paletteFromSchedule() {
    const palette = {};
    const sensor = this._hass?.states?.[this._config.schedule_sensor];
    for (const slot of sensor?.attributes?.timeslots ?? []) {
      if (slot.scene && slot.color) palette[slot.scene.toLowerCase()] = slot.color;
    }
    return palette;
  }

  /** The scene name the bridge currently reports, or null. */
  _activeSceneName() {
    const sensor = this._hass?.states?.[this._config.active_scene_sensor];
    if (!sensor || ["none", "unknown", "unavailable"].includes(sensor.state)) return null;
    return sensor.state;
  }

  /** True while the adaptive smart scene is the one running. */
  _autoActive() {
    const sensor = this._hass?.states?.[this._config.active_scene_sensor];
    return Boolean(sensor?.attributes?.is_smart_scene);
  }

  /**
   * Display name for a scene entity. Core Hue sets `has_entity_name`, so the
   * friendly name is "<Room> <Scene>" while the active-scene sensor reports
   * the bare "<Scene>". Prefer an explicit config name.
   */
  _sceneName(item) {
    if (item.name) return item.name;
    const state = this._hass?.states?.[item.entity];
    const friendly = state?.attributes?.friendly_name ?? item.entity;
    const room = this._config.name;
    if (room && friendly.toLowerCase().startsWith(room.toLowerCase())) {
      return friendly.slice(room.length).trim() || friendly;
    }
    return friendly;
  }

  _isActive(item) {
    const active = this._activeSceneName();
    if (!active || this._autoActive()) return false;
    const name = this._sceneName(item).toLowerCase();
    const current = active.toLowerCase();
    return name === current || name.endsWith(current);
  }

  /* --------------------------------------------------------------- lights */

  /**
   * The individual bulbs currently on in this room.
   *
   * Dimming the room group would move every bulb, including the ones the
   * scene deliberately left off. An explicit `lights:` list wins; otherwise
   * members are resolved through the area, minus the group entity itself.
   */
  _litLights() {
    const hass = this._hass;
    if (!hass) return [];

    let candidates = this._config.lights;
    if (!candidates && this._config.area) {
      const area = this._config.area;
      candidates = Object.keys(hass.states)
        .filter((id) => id.startsWith("light."))
        .filter((id) => id !== this._config.light)
        .filter((id) => {
          const entry = hass.entities?.[id];
          if (!entry) return false;
          if (entry.area_id) return entry.area_id === area;
          const device = entry.device_id ? hass.devices?.[entry.device_id] : null;
          return device?.area_id === area;
        });
    }
    if (!candidates || candidates.length === 0) candidates = [this._config.light];

    return candidates.filter((id) => hass.states?.[id]?.state === "on");
  }

  _currentBrightnessPct() {
    const hass = this._hass;
    const lit = this._litLights();
    const values = lit
      .map((id) => hass.states[id]?.attributes?.brightness)
      .filter((b) => typeof b === "number");
    if (!values.length) return null;
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    return Math.round((mean / 255) * 100);
  }

  /* -------------------------------------------------------------- actions */

  _activateScene(entity) {
    this._hass.callService("scene", "turn_on", { entity_id: entity });
  }

  _toggleAuto() {
    if (this._autoActive()) {
      // There is no "deactivate" for a Hue smart scene; picking any other
      // scene drops out of it, and turning the room off stops it outright.
      this._hass.callService("light", "turn_off", { entity_id: this._config.light });
    } else if (this._config.smart_scene) {
      this._activateScene(this._config.smart_scene);
    }
  }

  _applyBrightness(pct) {
    const targets = this._drag?.targets ?? this._litLights();
    if (!targets.length) return;
    this._hass.callService("light", "turn_on", {
      entity_id: targets,
      brightness_pct: Math.max(MIN_BRIGHTNESS_PCT, Math.min(100, Math.round(pct))),
    });
  }

  /* ---------------------------------------------------------------- build */

  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>
        :host { display: block; }
        .rail {
          position: relative;
          display: flex;
          align-items: center;
          gap: 10px;
          min-height: 46px;
          padding: 4px 10px;
          box-sizing: border-box;
          border-radius: 24px;
          background: var(--secondary-background-color);
          overflow: hidden;
          touch-action: pan-y;
          user-select: none;
        }
        .fill {
          position: absolute;
          inset: 0 auto 0 0;
          background: var(--primary-text-color);
          opacity: 0.07;
          pointer-events: none;
          transition: width 120ms ease-out;
        }
        .rail.dragging .fill { transition: none; }
        .label {
          position: relative;
          flex: 0 0 auto;
          font-size: 14px;
          font-weight: 500;
          color: var(--primary-text-color);
          white-space: nowrap;
        }
        .chips {
          position: relative;
          display: flex;
          align-items: center;
          gap: 6px;
          margin-left: auto;
          overflow: hidden;
        }
        .chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          height: 36px;
          padding: 0 9px;
          border: 2px solid transparent;
          border-radius: 18px;
          background: var(--card-background-color);
          color: var(--secondary-text-color);
          font: inherit;
          font-size: 13px;
          cursor: pointer;
          white-space: nowrap;
          transition: border-color 120ms ease, padding 140ms ease;
        }
        .chip ha-icon { --mdc-icon-size: 20px; flex: 0 0 auto; }
        .chip .chip-name {
          max-width: 0;
          overflow: hidden;
          opacity: 0;
          transition: max-width 160ms ease, opacity 140ms ease;
        }
        .chip.expanded .chip-name { max-width: 120px; opacity: 1; }
        .chip.expanded { border-color: var(--primary-text-color); }
        .chip.auto { position: relative; }
        .chip.auto.expanded { border-color: var(--primary-text-color); }
      </style>
      <div class="rail">
        <div class="fill"></div>
        <div class="label"></div>
        <div class="chips"></div>
      </div>
    `;

    this._railEl = root.querySelector(".rail");
    this._fillEl = root.querySelector(".fill");
    this._labelEl = root.querySelector(".label");
    this._chipsEl = root.querySelector(".chips");

    this._railEl.addEventListener("pointerdown", (e) => this._onDown(e));
    this._railEl.addEventListener("pointermove", (e) => this._onMove(e));
    this._railEl.addEventListener("pointerup", (e) => this._onUp(e));
    this._railEl.addEventListener("pointercancel", () => this._endDrag());

    this._built = true;
  }

  /* -------------------------------------------------------------- pointer */

  _onDown(event) {
    if (event.button !== undefined && event.button !== 0) return;
    const startPct = this._currentBrightnessPct();
    this._drag = {
      x: event.clientX,
      chip: event.target.closest(".chip"),
      moved: false,
      startPct: startPct ?? 50,
      targets: this._litLights(),
    };
    this._railEl.setPointerCapture?.(event.pointerId);
  }

  _onMove(event) {
    const drag = this._drag;
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < DRAG_THRESHOLD_PX) return;
    if (!this._config.dim || drag.targets.length === 0) return;

    if (!drag.moved) {
      drag.moved = true;
      this._railEl.classList.add("dragging");
    }
    event.preventDefault();

    const width = this._railEl.getBoundingClientRect().width || 1;
    const pct = Math.max(MIN_BRIGHTNESS_PCT, Math.min(100, drag.startPct + (dx / width) * 100));
    drag.pct = pct;
    this._fillEl.style.width = `${pct}%`;

    const now = Date.now();
    if (now - this._lastSent > THROTTLE_MS) {
      this._lastSent = now;
      this._applyBrightness(pct);
    } else {
      this._pendingPct = pct;
    }
  }

  _onUp(event) {
    const drag = this._drag;
    if (!drag) return;

    if (drag.moved) {
      if (this._pendingPct !== null || drag.pct !== undefined) {
        this._applyBrightness(this._pendingPct ?? drag.pct);
      }
    } else if (drag.chip) {
      const kind = drag.chip.dataset.kind;
      if (kind === "auto") this._toggleAuto();
      else if (drag.chip.dataset.entity) this._activateScene(drag.chip.dataset.entity);
    }

    this._railEl.releasePointerCapture?.(event.pointerId);
    this._endDrag();
  }

  _endDrag() {
    this._pendingPct = null;
    this._drag = null;
    this._railEl.classList.remove("dragging");
    this._render();
  }

  /* --------------------------------------------------------------- render */

  _chipColours(background) {
    // Scene colours are data, not theme, so the foreground is picked for
    // contrast against the swatch rather than from a theme variable.
    const hex = background.replace("#", "");
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    return luminance > 0.45 ? "#1c1c1c" : "#ffffff";
  }

  _render() {
    if (!this._built || !this._hass) return;
    if (this._drag?.moved) return; // don't fight the drag

    this._labelEl.textContent = this._config.name ?? "";

    const palette = this._paletteFromSchedule();
    const autoOn = this._autoActive();

    const items = [];
    if (this._config.smart_scene) {
      items.push({ kind: "auto", label: this._config.auto_label, icon: this._config.auto_icon });
    }
    for (const scene of this._config.scenes) {
      const item = typeof scene === "string" ? { entity: scene } : scene;
      items.push({ kind: "scene", item });
    }

    const html = items
      .map((entry) => {
        if (entry.kind === "auto") {
          const gradient = Object.values(palette);
          const bg = gradient.length > 1
            ? `linear-gradient(90deg, ${gradient.join(", ")})`
            : "var(--card-background-color)";
          const fg = autoOn ? this._chipColours(gradient[0] ?? "#ffffff") : "var(--secondary-text-color)";
          return `
            <button class="chip auto ${autoOn ? "expanded" : ""}" data-kind="auto"
                    style="background:${bg};color:${fg}" title="${entry.label}">
              <ha-icon icon="${entry.icon}"></ha-icon>
              <span class="chip-name">${entry.label}</span>
            </button>`;
        }
        const { item } = entry;
        const name = this._sceneName(item);
        const colour = item.color ?? palette[name.toLowerCase()];
        const active = this._isActive(item);
        const bg = colour ?? "var(--card-background-color)";
        const fg = colour ? this._chipColours(colour) : "var(--secondary-text-color)";
        return `
          <button class="chip ${active ? "expanded" : ""}" data-kind="scene"
                  data-entity="${item.entity}"
                  style="background:${bg};color:${fg}" title="${name}">
            ${item.icon ? `<ha-icon icon="${item.icon}"></ha-icon>` : ""}
            <span class="chip-name">${name}</span>
          </button>`;
      })
      .join("");

    if (html !== this._lastHtml) {
      this._chipsEl.innerHTML = html;
      this._lastHtml = html;
    }

    const pct = this._currentBrightnessPct();
    this._fillEl.style.width = pct === null ? "0%" : `${pct}%`;
  }
}

customElements.define("hue-scene-rail", HueSceneRail);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "hue-scene-rail",
  name: "Hue Scene Rail",
  description: "Scene-first rail for a Hue room: auto toggle, colour-coded scene buttons, drag to dim.",
});
