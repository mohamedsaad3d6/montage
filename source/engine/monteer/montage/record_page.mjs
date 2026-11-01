// Screen recording of public web pages (e.g. the channel's own site) with headless Chrome.
// No sign-in, no clicks, no form submissions: it only opens the given public pages and scrolls them.
// The pages come from a JSON file: {"name": {"url": ..., "hold": s, "secs": s, "dist": px}, ...}
// Talks to Chrome over the DevTools protocol with Node's built-in WebSocket (nothing installed).
//
//   node monteer/montage/record_page.mjs recon <outdir> <pages.json>     full-page screenshots (to plan the scroll)
//   node monteer/montage/record_page.mjs record <outdir> <pages.json>    1920x1080 frames, 24 fps: <outdir>/<name>/%05d.jpg
//
// Each frame is a screenshot taken after scrolling to that frame's position (smooth ease in/out), so the scroll is
// exactly 24 fps whatever the capture speed. Videos on the page are paused at their first frame so they don't
// run fast between frames. A fresh temporary Chrome profile is used (no cookies, no saved logins).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9337;
const [mode, outdir, pagesFile] = process.argv.slice(2);
const PAGES = JSON.parse(readFileSync(pagesFile, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "monteer-chrome-"));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1920,1080", "--hide-scrollbars", "--mute-audio", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--disable-sync", "--lang=ar", "about:blank"], { stdio: "ignore" });

async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(200);
  }
  throw new Error("chrome did not start");
}

const ws = new WebSocket(await connect());
await new Promise((r) => ws.addEventListener("open", r));
let nextId = 1;
const waiting = new Map();
const events = [];
ws.addEventListener("message", (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); } else if (msg.method) events.push(msg.method);
});
function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => waiting.set(id, (m) => (m.error ? rej(new Error(method + ": " + m.error.message)) : res(m.result))));
}
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });

async function open(url) {
  events.length = 0;
  await send("Page.navigate", { url });
  for (let i = 0; i < 150 && !events.includes("Page.loadEventFired"); i++) await sleep(100);
  await sleep(2500);   // fonts, images, entry animations
  // load lazy images by passing over the page once, then back to the top
  const H = await evalJs("document.documentElement.scrollHeight");
  for (let y = 0; y < H; y += 900) { await evalJs(`window.scrollTo(0, ${y})`); await sleep(150); }
  await evalJs("window.scrollTo(0, 0)");
  // the analytics consent bar is hidden with CSS, not answered: no consent signal is sent either way
  await evalJs(`for (const el of document.querySelectorAll('body *')) {
      const cs = getComputedStyle(el);
      if ((cs.position === 'fixed' || cs.position === 'sticky') && /لا شكراً|موافق/.test(el.innerText || '') && el.innerText.length < 600) el.style.display = 'none';
    }`);
  await evalJs("document.querySelectorAll('video').forEach(v => { v.pause(); v.currentTime = 0; })");
  await sleep(1200);
  return H;
}

async function shot(path, clip) {
  const p = { format: "jpeg", quality: 92 };
  if (clip) { p.clip = clip; p.captureBeyondViewport = true; }
  const r = await send("Page.captureScreenshot", p);
  writeFileSync(path, Buffer.from(r.data, "base64"));
}

const ease = (p) => { const q = Math.min(Math.max(p, 0), 1); return q * q * (3 - 2 * q); };
const log = { mode, pages: {} };
try {
  for (const [name, pg] of Object.entries(PAGES)) {
    const H = await open(pg.url);
    if (mode === "recon") {
      mkdirSync(outdir, { recursive: true });
      await shot(join(outdir, `${name}_full.jpg`), { x: 0, y: 0, width: 1920, height: Math.min(H, 12000), scale: 0.5 });
      log.pages[name] = { url: pg.url, height: H, title: await evalJs("document.title"),
        images: await evalJs("[...document.images].map(i => [i.currentSrc, i.naturalWidth, i.naturalHeight, i.alt, Math.round(i.getBoundingClientRect().top + scrollY)])") };
      continue;
    }
    // record: scroll from the top to `dist` px (2.2 screens, or less if the page is shorter)
    const dir = join(outdir, name);
    mkdirSync(dir, { recursive: true });
    const dist = Math.min(H - 1080, pg.dist ?? 2400);
    const n = Math.round(pg.secs * 24);
    const t0 = Date.now();
    for (let f = 0; f < n; f++) {
      const t = f / 24;
      const y = Math.round(dist * ease((t - pg.hold) / (pg.secs - pg.hold - 0.6)));
      await evalJs(`window.scrollTo(0, ${y})`);
      await sleep(30);
      await shot(join(dir, String(f).padStart(5, "0") + ".jpg"));
    }
    log.pages[name] = { url: pg.url, height: H, frames: n, scroll_px: dist, capture_s: (Date.now() - t0) / 1000, title: await evalJs("document.title") };
  }
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  rmSync(profile, { recursive: true, force: true });
}
writeFileSync(join(outdir, "record_log.json"), JSON.stringify(log, null, 1));
console.log(JSON.stringify(log));
