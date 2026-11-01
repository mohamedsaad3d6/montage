// Documented news as a real screenshot of its public page, cropped to the important sentence (owner's answer 11 of
// phase 2A; phase 2E of the channel profiles). Headless Chrome over the DevTools protocol, Node's own WebSocket.
//
//   node monteer/montage/news_shot.mjs <outdir> <jobs.json>
//   jobs: [{"id", "url", "passage": the sentence(s) as the page writes them}]
//   -> <outdir>/<id>.png (the crop, at 2x) and <outdir>/news_shots.json:
//      {id: {"status": "ok" | "paywall" | "login" | "blocked" | "not_found" | "covered" | "error", "why", "crop": [w, h] (png px),
//            "lines": [[x, y, w, h], ...] (the sentence's lines in the png), "rtl", "found": the text matched, "url"}}
//
// Public pages only: a fresh profile (no cookies, no saved logins), no clicks, no typing, no form, nothing hidden or
// removed from the page. A page that says it is not free (isAccessibleForFree false, a locked or metered tier), that
// lands on a sign-in or subscription address, asks for a bot check (CAPTCHA), or where the sentence is covered (a wall, a
// consent box, a banner) is NOT shot; what the page showed is kept as <id>_why.jpg for the report (never in a video).
// Never the full page: only the paragraph(s) that hold the sentence, at most MAX_H tall, never the top of the page
// (a crop that would reach into the page's header, nav or masthead is cut to the sentence's own lines).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync, rmSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const W = 1280, H = 900, SCALE = 2, MAX_H = 420, PAD = 22, PADX = 6;
const [outdir, jobsFile] = process.argv.slice(2);
const JOBS = JSON.parse(readFileSync(jobsFile, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(outdir, { recursive: true });

const profile = mkdtempSync(join(tmpdir(), "monteer-news-"));
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1", `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, "--hide-scrollbars", "--mute-audio", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--disable-sync", "about:blank"], { stdio: "ignore" });

async function connect() {
  // Chrome picks a free port and writes it to DevToolsActivePort in its profile (no clash with anything else on this Mac)
  for (let i = 0; i < 100; i++) {
    try {
      const f = join(profile, "DevToolsActivePort");
      if (!existsSync(f)) throw new Error("not yet");
      const port = readFileSync(f, "utf8").split("\n")[0].trim();
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(200);
  }
  throw new Error("chrome did not start");
}

let wsUrl;
try { wsUrl = await connect(); } catch (e) { chrome.kill(); rmSync(profile, { recursive: true, force: true }); throw e; }
const ws = new WebSocket(wsUrl);
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
await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: SCALE, mobile: false });

// in the page: find the passage, decide if it may be shot, and where (all in CSS px of the document)
const FIND = (passage) => `(() => {
  const norm = (s) => s.normalize("NFKC").replace(/[\\u064B-\\u065F\\u0670\\u0640]/g, "").replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي")
    .replace(/ة/g, "ه").replace(/[\\u2018\\u2019\\u201C\\u201D«»"']/g, "").toLowerCase();
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "NAV", "HEADER", "FOOTER", "ASIDE", "TEMPLATE"]);
  // 1. the page's own word on access
  const lds = [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => { try { return JSON.parse(s.textContent); } catch { return null; } });
  const flat = (x) => Array.isArray(x) ? x.flatMap(flat) : x && x["@graph"] ? flat(x["@graph"]) : x ? [x] : [];
  const notFree = lds.flatMap(flat).some(d => d && (d.isAccessibleForFree === false || d.isAccessibleForFree === "False" || d.isAccessibleForFree === "false"));
  const tier = (document.querySelector('meta[property="article:content_tier"]') || {}).content || "";
  if (notFree || /locked|metered/i.test(tier)) return {status: "paywall", why: "the page says it is not free to read"};
  if (/(log-?in|sign-?in|subscribe|account|paywall)/i.test(location.pathname + location.search))
    return {status: "login", why: "the page went to a sign-in or subscription address: " + location.href};
  // a bot check stands in the way: a visible challenge box (not the invisible badge many sites carry for their forms),
  // or the page's own words saying so
  const box = [...document.querySelectorAll('iframe[src*="captcha"], iframe[src*="challenge"], .h-captcha, #challenge-form')]
    .some(e => { const q = e.getBoundingClientRect(); return q.width >= 200 && q.height >= 60 && getComputedStyle(e).visibility !== "hidden"; });
  if (box || /are you a (human|robot)|think that you are a bot|verify you are (a )?human|solve this captcha|unusual traffic/i.test(document.body.innerText.slice(0, 3000)))
    return {status: "blocked", why: "the site asks for a bot check (CAPTCHA): never answered, not shot"};
  // 2. the passage in the page's visible text, matched after the same normalisation on both sides
  const nodes = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {acceptNode(n) {
    for (let e = n.parentElement; e; e = e.parentElement) if (SKIP.has(e.tagName) || e.getAttribute("role") === "navigation") return NodeFilter.FILTER_REJECT;
    return n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; }});
  for (let n = walk.nextNode(); n; n = walk.nextNode()) nodes.push(n);
  let text = "", map = [];
  for (const n of nodes) {
    const v = n.nodeValue;
    for (let i = 0; i < v.length; i++) {
      const c = norm(v[i]);
      if (!c) continue;
      if (/\\s/.test(c)) { if (text.endsWith(" ")) continue; text += " "; map.push([n, i]); continue; }
      for (const ch of c) { text += ch; map.push([n, i]); }
    }
    if (!text.endsWith(" ")) { text += " "; map.push([n, v.length - 1]); }
  }
  const want = norm(${JSON.stringify(passage)}).replace(/\\s+/g, " ").trim();
  const sentences = want.split(/(?<=[.!?؟])\\s+/).filter(s => s.length > 20).sort((a, b) => b.length - a.length);
  let at = -1, len = 0;
  for (const s of [want, ...sentences, want.split(" ").slice(0, 14).join(" ")]) {
    const k = text.indexOf(s);
    if (k >= 0 && s.length > 25) { at = k; len = s.length; break; }
  }
  if (at < 0) return {status: "not_found", why: "the sentence is not in the page's text (changed, or only in a picture)"};
  const r = document.createRange();
  const [n0, i0] = map[at], [n1, i1] = map[at + len - 1];
  r.setStart(n0, i0); r.setEnd(n1, Math.min(n1.nodeValue.length, i1 + 1));
  const block = (n) => { let e = n.parentElement; while (e && getComputedStyle(e).display.startsWith("inline")) e = e.parentElement; return e; };
  const b0 = block(n0), b1 = block(n1);
  b0.scrollIntoView({block: "center"});
  const sy = scrollY;
  const rects = [...r.getClientRects()].filter(q => q.width > 2 && q.height > 4);
  if (!rects.length) return {status: "not_found", why: "the sentence has no visible lines"};
  // 3. nothing over it: the point at each line's middle must be inside the text's own block
  for (const q of rects) {
    const e = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
    if (!e || !(b0.contains(e) || b1.contains(e) || e.contains(b0))) {
      let c = e; while (c && c.parentElement && c.parentElement !== document.body && getComputedStyle(c).position !== "fixed") c = c.parentElement;
      const what = c ? (c.tagName + (c.id ? "#" + c.id : "") + " " + (c.className || "").toString().slice(0, 60) + " «" + (c.innerText || "").slice(0, 120).replace(/\s+/g, " ") + "»") : "?";
      return {status: "covered", why: "something covers the sentence (a wall or a banner): not shot", coverer: what};
    }
  }
  // 4. the crop: the paragraph(s), no higher than the page's header, at most MAX_H tall around the sentence
  const pr = [b0.getBoundingClientRect(), b1.getBoundingClientRect()];
  // the text's own extent (a paragraph's box can be narrower than its letters)
  const own = [b0, b1].flatMap(b => { const rr = document.createRange(); rr.selectNodeContents(b); return [...rr.getClientRects()]; }).filter(q => q.width > 1);
  let x0 = Math.min(...pr.map(q => q.left), ...own.map(q => q.left)), x1 = Math.max(...pr.map(q => q.right), ...own.map(q => q.right));
  let y0 = Math.min(...pr.map(q => q.top)), y1 = Math.max(...pr.map(q => q.bottom));
  const ly0 = Math.min(...rects.map(q => q.top)), ly1 = Math.max(...rects.map(q => q.bottom));
  if (y1 - y0 > ${MAX_H}) { const mid = (ly0 + ly1) / 2; y0 = Math.max(y0, Math.min(ly0, mid - ${MAX_H} / 2)); y1 = Math.min(y1, Math.max(ly1, y0 + ${MAX_H})); }
  const head = [...document.querySelectorAll("header, nav, [role=banner], [class*=masthead], [id*=masthead]")]
    .map(e => e.getBoundingClientRect()).filter(q => q.height > 0 && q.bottom > y0 - ${PAD} && q.top < y1);
  if (head.length) { y0 = Math.max(y0, ly0 - 6); y1 = Math.max(y1, ly1 + 6); }
  // the padding stops short of the neighbouring paragraphs (no half line of other text at the edges)
  // the nearest other text above and below in the same column (whatever the page's structure)
  let prevB = -1e9, nextT = 1e9;
  for (const n of nodes) {
    if (b0.contains(n) || b1.contains(n)) continue;
    const rr = document.createRange(); rr.selectNodeContents(n);
    for (const q of rr.getClientRects()) {
      if (q.width < 2 || q.right < x0 || q.left > x1) continue;
      if (q.bottom <= y0 + 1 && q.bottom > prevB) prevB = q.bottom;
      if (q.top >= y1 - 1 && q.top < nextT) nextT = q.top;
    }
  }
  const top = Math.max(y0 - ${PAD}, (prevB + y0) / 2), bot = Math.min(y1 + ${PAD}, (nextT + y1) / 2);
  x0 = Math.max(0, x0 - ${PADX}); x1 = Math.min(innerWidth, x1 + ${PADX}); y0 = top; y1 = bot;
  const lines = [];
  for (const q of rects) {          // one box per line
    const l = lines.find(z => Math.abs(z[1] - q.top) < q.height / 2);
    if (l) { const a = Math.min(l[0], q.left), b = Math.max(l[0] + l[2], q.right); l[0] = a; l[2] = b - a; l[3] = Math.max(l[3], q.height); }
    else lines.push([q.left, q.top, q.width, q.height]);
  }
  const rtl = getComputedStyle(b0).direction === "rtl";
  window.__mt = {r, top: rects[0].top + sy};          // to see after the shot whether the page moved under it
  return {status: "ok", rtl, found: text.slice(at, at + len),
          clip: {x: x0, y: y0 + sy, width: x1 - x0, height: y1 - y0},
          lines: lines.map(([x, y, w, h]) => [x - x0, y - y0, w, h])};
})()`;

const out = {};
try {
  for (const job of JOBS) {
    try {
      events.length = 0;
      await send("Page.navigate", { url: job.url });
      for (let i = 0; i < 200 && !events.includes("Page.loadEventFired"); i++) await sleep(100);
      await sleep(2500);                                   // fonts, late text
      // pass over the page once (scrolling only), so late images and boxes are in place before anything is measured
      const PH = await evalJs("document.documentElement.scrollHeight");
      for (let y = 0; y < Math.min(PH, 20000); y += 800) { await evalJs(`window.scrollTo(0, ${y})`); await sleep(120); }
      await evalJs("window.scrollTo(0, 0)");
      await sleep(1200);
      let r = await evalJs(FIND(job.passage));
      if (!r || r.status !== "ok") {
        out[job.id] = { status: r ? r.status : "error", why: r ? r.why : "no answer from the page", coverer: r && r.coverer, url: job.url };
        // what the page showed, for the report only (never used in a video)
        const v = await send("Page.captureScreenshot", { format: "jpeg", quality: 70 });
        writeFileSync(join(outdir, `${job.id}_why.jpg`), Buffer.from(v.data, "base64"));
        continue;
      }
      let shot;
      for (let tries = 0; ; tries++) {            // shoot, then check the sentence did not move; else measure and shoot again
        await sleep(tries ? 1600 : 700);
        shot = await send("Page.captureScreenshot", { format: "png", clip: { ...r.clip, scale: 1 }, captureBeyondViewport: true });
        const moved = await evalJs("(() => { const q = window.__mt.r.getClientRects()[0]; return q ? Math.abs(q.top + scrollY - window.__mt.top) : 999; })()");
        if (moved < 2) break;
        if (tries >= 4) throw new Error("the page kept moving under the sentence");
        r = await evalJs(FIND(job.passage));
        if (!r || r.status !== "ok") throw new Error("the sentence was lost while the page moved");
      }
      writeFileSync(join(outdir, `${job.id}.png`), Buffer.from(shot.data, "base64"));
      out[job.id] = { status: "ok", url: job.url, rtl: r.rtl, found: r.found,
                      crop: [Math.round(r.clip.width * SCALE), Math.round(r.clip.height * SCALE)],
                      lines: r.lines.map(l => l.map(v => Math.round(v * SCALE))) };
    } catch (e) {
      out[job.id] = { status: "error", why: String(e).slice(0, 300), url: job.url };
    }
  }
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  rmSync(profile, { recursive: true, force: true });
}
writeFileSync(join(outdir, "news_shots.json"), JSON.stringify(out, null, 1));
console.log(JSON.stringify(Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.status]))));
