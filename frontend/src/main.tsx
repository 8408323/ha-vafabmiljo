import { createRoot, Root } from "react-dom/client";
import App from "./App";
import css from "./styles.css?inline";

// The panel's own typeface. @font-face doesn't work inside a shadow root, so the stylesheet goes into the
// document once; without internet the panel just falls back to the system font.
function loadFont() {
  if (document.getElementById("vafabmiljo-font")) return;
  const link = document.createElement("link");
  link.id = "vafabmiljo-font";
  link.rel = "stylesheet";
  link.href = "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap";
  document.head.append(link);
}

class VafabmiljoPanel extends HTMLElement {
  private root?: Root;
  private _hass: any;
  private _narrow = false;
  set hass(h: any) { this._hass = h; this.render(); }
  set narrow(n: boolean) { this._narrow = n; this.render(); }
  connectedCallback() {
    if (this.root) return;
    loadFont();
    // a re-attached element keeps its shadow root; attachShadow() would throw a second time
    const shadow = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    shadow.replaceChildren();
    const style = document.createElement("style");
    style.textContent = css;
    const mount = document.createElement("div");
    shadow.append(style, mount);
    this.root = createRoot(mount);
    this.render();
  }
  disconnectedCallback() { this.root?.unmount(); this.root = undefined; }
  private render() { if (this.root && this._hass) this.root.render(<App hass={this._hass} narrow={this._narrow} />); }
}

if (!customElements.get("vafabmiljo-panel")) customElements.define("vafabmiljo-panel", VafabmiljoPanel);
