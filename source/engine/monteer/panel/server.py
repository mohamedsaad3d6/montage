"""The Monteer web panel (Works/output/web_panel_plan.md): phase 1, the shell and the episodes list; phase 2, New episode
(type, output, run mode, instructions, files from this Mac, your extra clips) and starting / stopping a run.

    bin/monteer panel [--port 8765] [--no-open] [--projects "<folder>"]      by hand (in a Terminal window)
    bin/monteer panel install|stop|start|restart|status|uninstall            as a background service that starts at
                                                                             login, at http://127.0.0.1:8765/ (service.py)

Private to this Mac (owner's decision 1a: no login):
  - it listens on 127.0.0.1 only, never on a network address, so no other device can reach it;
  - every request must name 127.0.0.1 or localhost (with this port) as its host: a web page elsewhere that points a
    name of its own at 127.0.0.1 is refused;
  - a secret, made once and kept in ~/.config/monteer/panel_secret (readable by this user only), is held by the page in
    a cookie (HttpOnly, SameSite=Strict), and every page and API call without it is refused. The browser gets the cookie
    when the panel's address is opened by the person: typed, a bookmark, or `open` (the browser marks such a visit
    "Sec-Fetch-Site: none", which no web page can fake); a link or a script from another site gets the locked page;
  - nothing is sent outside the computer: the design's files, the Cairo font and the data all come from this Mac;
  - keys are never read for their values: the panel only says whether each one is present in ~/.config/monteer/keys.json.
  - every request that changes something (POST, PUT) must also come from the panel's own page (its Origin header): a
    page elsewhere cannot start a run or send a file even if the browser holds the cookie.
What it changes (phase 2): it creates episodes in the projects folder (monteer/core/newproject.py), keeps your uploaded
clips there, and starts / stops `bin/monteer run` (monteer/core/runctl.py). Test episodes stay read-only. Raw files are
picked with the Mac's own file dialog and used where they are (never copied).
"""
import argparse
import getpass
import hmac
import re
import shutil
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core import summary as SUM
from ..core.newproject import Refused
from ..core.paths import ENGINE, FONTS, KEYS, MODELS

STATIC = Path(__file__).resolve().parent / "static"
PROJECTS = ENGINE.parent / "monteer_projects"          # owner's decision 5a: episodes live in one projects folder
DISK_MARGIN = 5 << 30                                  # an upload never leaves less than 5 GB free
MAX_JSON = 64 << 10
BALANCE_READING = threading.Event()                    # a page's Magnific balance reading is running
TESTS = ENGINE.parent / "monteer_tests"                # the test projects, listed read-only
COOKIE = "monteer_panel"
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; "
       "connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class Panel:
    def __init__(self, port):
        self.port = port
        self.secret = panel_secret()
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._cache = {}
        self._lock = threading.Lock()

    def cached(self, key, ttl, fn):
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
        val = fn()
        with self._lock:
            self._cache[key] = (time.time(), val)
        return val

    # ------------------------------------------------------------------------------------------------ data
    def brain(self):
        """the Claude account card (owner's answers of 18 Oct 2026, W1): installed and its version, signed in, the plan,
        the signed-in email (shown on this Mac only: the panel answers 127.0.0.1 alone; nothing is sent anywhere), and
        whether it is the subscription or paid API billing. Read with `claude --version` and `claude auth status`."""
        from ..core.claudebrain import claude_bin
        out = {"state": "missing", "plan": None, "email": None, "method": None, "subscription": None, "version": None,
               "path": None, "checked_at": time.strftime("%H:%M:%S")}
        b = claude_bin()
        if not b:
            return out
        out["path"] = b
        try:
            v = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
            out["version"] = v.split()[0] if v else None
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            r = subprocess.run([b, "auth", "status"], capture_output=True, text=True, timeout=30)
            d = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return dict(out, state="unknown")
        if not d.get("loggedIn"):
            return dict(out, state="signed_out")
        method = d.get("authMethod") or None
        return dict(out, state="ok", plan=d.get("subscriptionType") or None, email=d.get("email") or None, method=method,
                    subscription=method == "claude.ai")

    def brain_fresh(self):
        with self._lock:
            self._cache.pop("brain", None)
        return self.cached("brain", 60, self.brain)

    def state(self):
        keys = {}
        if KEYS.exists():
            try:
                k = json.loads(KEYS.read_text())
                keys = {n: bool(v) for n, v in k.items()}
            except (ValueError, OSError):
                keys = {}
        try:
            name = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=5).stdout.strip()
        except OSError:
            name = ""
        llm = MODELS / "llm"
        from ..core.apikeys import KNOWN
        return {"brain": self.cached("brain", 60, self.brain), "known_keys": {k: list(v) for k, v in KNOWN.items()},
                "local_model": llm.exists() and any(llm.glob("*.gguf")),
                "keys": keys, "user": {"name": name, "initial": (name[:1] or "م").upper(), "account": getpass.getuser()},
                "projects_folder": str(PROJECTS), "tests_folder": str(TESTS)}

    def probe(self, path):
        """what a picked or uploaded file is: name, size, length, video/audio streams (ffprobe), or why it can't be used"""
        from ..core.paths import FFPROBE
        f = Path(path)
        out = {"path": str(f), "name": f.name, "bytes": f.stat().st_size if f.exists() else 0}
        if not f.exists():
            return dict(out, ok=False, why="the file is not there")
        if f.suffix.lower() == ".docx":
            import zipfile
            ok = zipfile.is_zipfile(f)
            return dict(out, ok=ok, kind="script", why="" if ok else "not a Word .docx file")
        if f.suffix.lower() == ".txt":
            try:
                ok = bool(f.read_text(encoding="utf-8-sig").strip())
                why = "" if ok else "the text file is empty"
            except (UnicodeDecodeError, OSError):
                ok, why = False, "not a UTF-8 text file (save it from Word as .docx, or as text in UTF-8)"
            return dict(out, ok=ok, kind="script", why=why)
        r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                            "-of", "json", str(f)], capture_output=True, text=True, timeout=60)
        try:
            d = json.loads(r.stdout or "{}")
        except ValueError:
            d = {}
        st = d.get("streams", [])
        v = next((s for s in st if s.get("codec_type") == "video"), None)
        a = any(s.get("codec_type") == "audio" for s in st)
        secs = float((d.get("format") or {}).get("duration") or 0)
        ok = bool(v or a) and secs > 0
        return dict(out, ok=ok, seconds=round(secs, 1), video=bool(v), audio=a,
                    width=(v or {}).get("width"), height=(v or {}).get("height"),
                    why="" if ok else "this file has no video or sound the engine can read")

    def drafts(self, draft):
        if not re.fullmatch(r"[a-z0-9]{8,40}", draft or ""):
            return None
        return PROJECTS / ".drafts" / draft

    def scripts(self):
        """approved scripts from the script writer (script/approved.json + the recording copy script/script.docx)"""
        out = []
        for i, f in self.folders().items():
            doc, ok = f / "script" / "script.docx", f / "script" / "approved.json"
            if doc.exists() and ok.exists():
                try:
                    name = json.loads((f / "project.json").read_text()).get("name", f.name)
                except (ValueError, OSError):
                    name = f.name
                try:
                    cfg = json.loads((f / "project.json").read_text())
                except (ValueError, OSError):
                    cfg = {}
                out.append({"id": i, "name": name, "path": str(doc), "read_only": i.startswith("t:"), "profile": cfg.get("profile"),
                            "type": {"talking_head": "presenter", "voice_only": "audio"}.get(cfg.get("mode"), None)})
        return out

    def folders(self):
        """{id: folder}: the projects folder's episodes and, read-only, the test projects"""
        out = {}
        for scope, root in (("p", PROJECTS), ("t", TESTS)):
            if root.exists():
                for d in sorted(root.iterdir()):
                    if (d / "project.json").exists():
                        out[f"{scope}:{d.name}"] = d
        return out

    def episode(self, eid, folder, log_lines=0):
        try:
            s = SUM.summary(folder, log_lines=log_lines)
        except (SystemExit, ValueError, OSError) as e:     # a project.json the engine refuses: shown, not hidden
            return {"id": eid, "name": folder.name, "error": str(e), "scope": eid[0], "folder": str(folder)}
        s.update(id=eid, scope="projects" if eid.startswith("p:") else "tests", read_only=eid.startswith("t:"))
        return s

    def episodes(self):
        def build():
            eps = [self.episode(i, f) for i, f in self.folders().items()]
            for e in eps:
                e.pop("log", None)
            return eps
        return self.cached("episodes", 4, build)


class Handler(BaseHTTPRequestHandler):
    panel = None
    server_version = "monteer-panel"
    sys_version = ""

    def log_message(self, fmt, *args):            # quiet: no request log on the terminal
        pass

    # ------------------------------------------------------------------------------------------------ guards
    def host_ok(self):
        return self.headers.get("Host", "") in self.panel.hosts

    def cookie_ok(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and hmac.compare_digest(v, self.panel.secret):
                return True
        return False

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=()):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False))

    def do_HEAD(self):
        self.do_GET()

    def origin_ok(self):
        o = self.headers.get("Origin", "")
        return o in {f"http://{h}" for h in self.panel.hosts}

    def guard_write(self):
        if not self.host_ok() or not self.cookie_ok() or not self.origin_ok():
            self.send(403, json.dumps({"error": "refused: changes come only from the panel's own page"}), "application/json")
            return False
        return True

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_JSON or "application/json" not in self.headers.get("Content-Type", ""):
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None

    def do_POST(self):
        if not self.guard_write():
            return
        u = urllib.parse.urlsplit(self.path)
        d = self.body_json()
        if d is None:
            return self.json({"error": "a JSON body is expected"}, 400)
        try:
            return self.json(actions(self.panel, u.path, d))
        except Refused as e:
            return self.json({"error": str(e)}, 400)

    def do_PUT(self):                             # an extra clip uploaded from the browser into the episode's draft folder
        if not self.guard_write():
            return
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/review_upload":            # the owner's edited Word review copy (phase 6): replaces review_vN.docx
            return self.review_upload((q.get("id") or [""])[0])
        if u.path != "/api/upload":
            return self.json({"error": "not found"}, 404)
        draft = self.panel.drafts((q.get("draft") or [""])[0])
        name = Path((q.get("name") or [""])[0]).name
        n = int(self.headers.get("Content-Length") or 0)
        from ..core.newproject import VIDEO_EXT
        if not draft or not name or Path(name).suffix.lower() not in VIDEO_EXT:
            return self.json({"error": "only video files (" + ", ".join(sorted(VIDEO_EXT)) + ")", "name": name}, 400)
        draft.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(draft).free
        if n <= 0 or free - n < DISK_MARGIN:
            return self.json({"error": f"not enough free disk space: {free >> 30} GB free, the file needs {n >> 20} MB "
                                       "and 5 GB must stay free", "name": name}, 400)
        dst = draft / re.sub(r"[^\w.\- ]+", "_", name)
        part = dst.with_name("." + dst.name + ".part")
        left = n
        with open(part, "wb") as out:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                out.write(chunk)
                left -= len(chunk)
        if left:
            part.unlink(missing_ok=True)
            return self.json({"error": "the upload was cut off", "name": name}, 400)
        part.replace(dst)
        info = self.panel.probe(dst)
        if not info["ok"] or not info.get("video"):
            dst.unlink(missing_ok=True)
            return self.json({"error": info["why"] or "this file has no video", "name": name}, 400)
        return self.json(dict(info, path=None, uploaded=dst.name))

    def review_upload(self, eid):
        f = self.panel.folders().get(eid)
        if not f or not eid.startswith("p:"):
            return self.json({"error": "no such script (test projects are read-only)"}, 400)
        from ..core.project import Project
        from ..script.common import S, latest_version
        from ..core import runctl
        p = Project(f)
        v = latest_version(p)
        n = int(self.headers.get("Content-Length") or 0)
        if not v or n <= 0 or n > 50 << 20:
            return self.json({"error": "there is no review copy to replace, or the file is empty or too big"}, 400)
        data = self.rfile.read(n)
        if data[:2] != b"PK":
            return self.json({"error": "this is not a Word file (.docx)"}, 400)
        if runctl.lock_pid(f):
            return self.json({"error": "the script is running: wait for it to finish"}, 400)
        dst = S(p, f"review_v{v}.docx")
        part = dst.with_name("." + dst.name + ".part")
        part.write_bytes(data)
        part.replace(dst)
        return self.json({"replaced": dst.name, "started": runctl.start(f, stage="script")})

    def file_out(self, path, download=False):
        """a finished video (with byte ranges, so the player can seek) or a report as text; download=True saves it"""
        size = path.stat().st_size
        ctype = "video/mp4" if path.suffix.lower() == ".mp4" else "text/plain; charset=utf-8" if path.suffix in (".md", ".txt") else \
            "application/json" if path.suffix == ".json" else "application/octet-stream"
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            from urllib.parse import quote
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def events(self, eid, folder, max_s=3600):
        """server-sent events (web panel plan 2.3): the summary as soon as the run's record, log, waiting or brain-wait
        files change; a comment every 15 s keeps the line open. Ends after max_s (the page opens a new one)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        files = [folder / "run" / n for n in ("record.json", "log.txt", "waiting.json", "brain_wait.json", "brain_wait_alongside.json", "lock",
                                                  "script_log.txt")] + \
                [folder / "decisions" / "montage" / "questions.json", folder / "decisions" / "you" / "plan_answers.json"]

        def sig():
            return tuple((f.stat().st_mtime_ns, f.stat().st_size) if f.exists() else None for f in files)
        last, quiet, t0 = None, 0, time.time()
        try:
            while time.time() - t0 < max_s:
                s = sig()
                if s != last:
                    last = s
                    body = json.dumps(self.panel.episode(eid, folder, log_lines=30), ensure_ascii=False)
                    self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    quiet = 0
                elif quiet >= 15:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    quiet = 0
                time.sleep(1)
                quiet += 1
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, "refused: this panel answers only to 127.0.0.1", "text/plain; charset=utf-8")
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/" and q.get("k"):           # the address bin/monteer panel opened: keep the secret in a cookie
            if hmac.compare_digest(q["k"][0], self.panel.secret):
                return self.send(303, "", "text/plain", [("Location", "/"),
                                                         ("Set-Cookie", f"{COOKIE}={self.panel.secret}; Path=/; HttpOnly; SameSite=Strict")])
            return self.send(403, locked_page(), "text/html; charset=utf-8")
        if u.path == "/" and not self.cookie_ok() and self.opened_by_person():
            return self.static("index.html", [("Set-Cookie", f"{COOKIE}={self.panel.secret}; Path=/; HttpOnly; SameSite=Strict")])
        if not self.cookie_ok():
            return self.send(403, locked_page(), "text/html; charset=utf-8")
        if u.path == "/":
            return self.static("index.html")
        if u.path.startswith("/static/"):
            return self.static(u.path[len("/static/"):])
        if u.path == "/fonts/cairo.ttf":
            f = FONTS / "Cairo[slnt,wght].ttf"
            return self.send(200, f.read_bytes(), "font/ttf") if f.exists() else self.send(404, "no font", "text/plain")
        if u.path == "/api/state":
            return self.json(self.panel.state())
        if u.path == "/api/brain":                      # "Check again" on the Claude account card
            return self.json(self.panel.brain_fresh())
        if u.path == "/api/episodes":
            return self.json({"episodes": self.panel.episodes()})
        if u.path == "/api/scripts":
            return self.json({"scripts": self.panel.scripts()})
        if u.path == "/api/profiles":                   # the channel profiles for the New episode screen (no default)
            from ..core.profile import available
            return self.json({"profiles": available()})
        if u.path == "/api/disk":
            return self.json({"free": shutil.disk_usage(PROJECTS).free, "projects_folder": str(PROJECTS)})
        if u.path == "/api/script":                     # the script writer (phase 6): one script project, read-only
            f = self.panel.folders().get((q.get("id") or [""])[0])
            if not f:
                return self.json({"error": "no such script"}, 404)
            from ..core.project import Project
            from ..script import view
            return self.json(view.data(Project(f)))
        if u.path == "/api/sfile":                      # a script file the owner may download (review copy, recording copy…)
            f = self.panel.folders().get((q.get("id") or [""])[0])
            name = (q.get("name") or [""])[0]
            if not f or not SCRIPT_FILES.fullmatch(name) or not (f / "script" / name).exists():
                return self.json({"error": "no such file"}, 404)
            return self.file_out(f / "script" / name, download=True)
        if u.path == "/api/trash":                      # the Trash: deleted episodes and the files from before a restart
            from ..core import trash
            return self.json({"items": trash.items(PROJECTS)})
        if u.path == "/api/channels":                   # the channels screen, and «عام»'s box
            from ..core import channels_view
            from ..montage import learning
            return self.json({"channels": channels_view.data(), "general_box": learning.box()})
        if u.path == "/api/chimg":                      # an image of a channel's profile folder (never outside it)
            from ..core import channels_view
            try:
                p = channels_view.asset_path((q.get("slug") or [""])[0], (q.get("path") or [""])[0])
            except Exception:  # noqa: BLE001
                p = None
            if not p:
                return self.json({"error": "no such image"}, 404)
            return self.send(200, p.read_bytes(), "image/png" if p.suffix.lower() == ".png" else "image/jpeg")
        if u.path == "/api/training":                   # the training library: raw + published pairs per channel
            from ..core import training
            return self.json({"channels": training.library()})
        if u.path == "/api/rules":                      # phase 9: the rulebook, from the rule files themselves
            from ..core import rulebook
            return self.json(dict(rulebook.rules(), proposals=rulebook.proposals()))
        if u.path == "/api/costs":                      # phase 8: the brain's work by month and recently, every episode
            from ..core import costs
            return self.json(dict(self.panel.cached("costs", 30, lambda: costs.summary(self.panel.folders().values())),
                                  scopes={"projects": sum(1 for k in self.panel.folders() if k.startswith("p:")),
                                          "tests": sum(1 for k in self.panel.folders() if k.startswith("t:"))}))
        if u.path == "/api/paid_status":               # are Magnific and Storyblocks connected (the «حلقة جديدة» sources card)
            from ..core import paid_status
            return self.json(self.panel.cached("paid_status", 600, paid_status.status))
        if u.path == "/api/paid_usage":                 # «استخدام الخدمات المدفوعة» (owner's (d) of 20 Oct 2026)
            from ..core import paid_usage
            from ..montage.sources import magnific as MG
            refreshing = False
            if (q.get("refresh") or [""])[0] == "1" and MG.on_any() and MG.balance_due() and not BALANCE_READING.is_set():
                BALANCE_READING.set()          # the page's balance reading runs aside (about 20 s), at most once an hour

                def _read():
                    try:
                        MG.read_balance("page", log=lambda *a: None)
                    finally:
                        BALANCE_READING.clear()
                threading.Thread(target=_read, daemon=True).start()
                refreshing = True
            return self.json(dict(paid_usage.summary(self.panel.folders().values()),
                                  refreshing=refreshing or BALANCE_READING.is_set()))
        if u.path == "/api/style":                      # a channel's style guide and source list
            return self.json(style_page((q.get("slug") or [""])[0]))
        if u.path == "/api/result":                     # the Result screen (phase 4): computed from the episode's own files
            f = self.panel.folders().get((q.get("id") or [""])[0])
            if not f:
                return self.json({"error": "no such episode"}, 404)
            from ..core.project import Project
            from ..montage import result as RES
            return self.json(RES.data(Project(f)))
        if u.path in ("/api/media", "/api/file"):       # an episode's own output file: only a name the episode lists
            f = self.panel.folders().get((q.get("id") or [""])[0])
            name = Path((q.get("name") or [""])[0]).name
            if not f or not name:
                return self.json({"error": "no such file"}, 404)
            from ..core.summary import outputs
            from ..core.project import Project
            if name not in {o["name"] for o in outputs(Project(f))}:
                return self.json({"error": "no such file"}, 404)
            return self.file_out(f / "output" / name, download=(q.get("dl") or [""])[0] == "1")
        if u.path == "/api/events":                     # live progress: the episode's summary each time its files change
            f = self.panel.folders().get((q.get("id") or [""])[0])
            if not f:
                return self.json({"error": "no such episode"}, 404)
            return self.events((q.get("id") or [""])[0], f)
        if u.path == "/api/episode":
            eid = (q.get("id") or [""])[0]
            f = self.panel.folders().get(eid)           # only a listed episode, never a path from the browser
            if not f:
                return self.json({"error": "no such episode"}, 404)
            return self.json(self.panel.episode(eid, f, log_lines=30))
        return self.send(404, "not found", "text/plain; charset=utf-8")

    def opened_by_person(self):
        """the address typed, bookmarked or opened by `open`: a top-level visit that no other site started"""
        h = self.headers
        return (h.get("Sec-Fetch-Site") == "none" and h.get("Sec-Fetch-Mode") == "navigate"
                and h.get("Sec-Fetch-Dest") == "document")

    def static(self, name, extra=()):
        f = (STATIC / name).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self.send(404, "not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        return self.send(200, f.read_bytes(), ctype, extra)


PICK = {"video": (["public.movie"], "اختار فيديو الكاميرا / Choose the camera video", False),
        "audio": (["public.audio", "public.movie"], "اختار الصوت / Choose the audio", False),
        "script": (["org.openxmlformats.wordprocessingml.document"], "اختار السكريبت (.docx) / Choose the script (.docx)", False),
        "script_audio": (["org.openxmlformats.wordprocessingml.document", "public.plain-text"],
                         "اختار السكريبت المعتمد (Word أو نص) / Choose the approved script (Word or text)", False),
        "clips": (["public.movie"], "اختار كليباتك الإضافية / Choose your extra clips", True),
        "ad": (["public.movie"], "اختار الإعلان / Choose the ad", False)}
PICKING = threading.Lock()                         # one file window at a time


def pick(kind):
    """the Mac's own file window, in front of the browser (monteer/panel/pick.swift) -> [paths], [] when cancelled.
    It used to be System Events' «choose file» through osascript: macOS asks once whether the app that started the panel
    may control System Events, and when that was refused (or the question never showed) the window never opened and the
    refusal was read as «cancelled», so nothing happened and nothing was said. The tool needs no such permission."""
    types, prompt, many = PICK[kind]
    if not PICKING.acquire(blocking=False):
        raise Refused("a file window is already open: choose there, or cancel it, first")
    try:
        from ..core.paths import PICK as TOOL
        from ..core.setup import build_swift
        try:
            build_swift("pick")                    # once, after an update that has not been through setup yet
        except (OSError, subprocess.CalledProcessError) as e:
            raise Refused(f"the file window could not be prepared ({e}): run  bin/monteer setup --only swift")
        try:
            r = subprocess.run([str(TOOL), prompt, "1" if many else "0", *types], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            raise Refused("the file window was open for 15 minutes without a choice, so it was closed")
        if r.returncode == 1:
            return []                              # cancelled
        if r.returncode:
            raise Refused(f"the file window could not open: {(r.stderr or '').strip()[-300:] or 'code ' + str(r.returncode)}")
        return [x for x in r.stdout.splitlines() if x]
    finally:
        PICKING.release()


SCRIPT_FILES = re.compile(r"(review_v\d+\.docx|script\.docx|outline\.md|drafts/v\d+\.checks\.md)")


def call_cli(argv):
    """a script command through its own code; its refusal (SystemExit) becomes the panel's refusal"""
    from ..script import cli as SC
    import contextlib
    import io as _io
    out = _io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            SC.main(argv)
    except SystemExit as e:
        if e.code not in (None, 0):
            raise Refused(str(e.code))
    return out.getvalue().strip()


def script_action(panel, d):
    """the script writer's actions (phase 6), each through the script tool's own code"""
    from ..core import runctl
    from ..core.project import Project
    act = d.get("action")
    if act == "new":
        folder = PROJECTS / (time.strftime("%Y-%m-%d_%H%M%S") + "_" + secrets.token_hex(3))
        topic = (d.get("topic") or "").strip()
        if not topic or not d.get("profile") or d.get("mode") not in ("talking_head", "voice_only"):
            raise Refused("اختار القناة والنوع، واكتب الموضوع")
        argv = ["new", str(folder), "--topic", topic, "--profile", d["profile"], "--mode", d["mode"], "--angle", (d.get("angle") or "").strip(),
                "--name", (d.get("name") or topic)[:120]]
        if d.get("minutes"):
            argv += ["--minutes", str(float(d["minutes"]))]
        try:
            call_cli(argv)
        except Refused as e:                         # the just-made folder is moved aside, never deleted (owner's rule)
            from ..core import trash
            trash.set_aside_refused(folder, str(e), kind="new script refused")
            raise
        if d.get("sources"):                         # the sources the owner picked for this script
            from ..core.io import load_json, save_json
            t = folder / "script" / "topic.json"
            save_json(t, dict(load_json(t), sources=[str(x) for x in d["sources"]]))
        panel._cache.clear()
        return {"id": "p:" + folder.name, "started": runctl.start(folder, stage="script")}
    f = panel.folders().get(d.get("id") or "")
    if not f or not str(d.get("id")).startswith("p:"):
        raise Refused("السكريبت ده مش موجود (مشاريع الاختبار للقراية بس)")
    if runctl.lock_pid(f) and act != "stop":
        raise Refused("كاتب السكريبت شغّال دلوقتي: استنى لما يخلص")
    name = (d.get("name") or "").strip()
    if act == "run":
        return {"started": runctl.start(f, stage="script")}
    if act == "stop":
        return runctl.stop(f)
    if act == "outline_ok":
        if not name:
            raise Refused("«أيوه» على الهيكل لازم يبقى عليها اسمك")
        call_cli(["outline-ok", str(f), "--name", name])
        return {"started": runctl.start(f, stage="script")}
    if act == "outline_edit":
        notes = (d.get("notes") or "").strip()
        if not notes:
            raise Refused("اكتب ملاحظاتك على الهيكل")
        call_cli(["outline-edit", str(f), "--notes", notes])
        return {"started": runctl.start(f, stage="script")}
    if act == "edits":
        from ..script import panel_edits
        try:
            n = panel_edits.save(Project(f), d.get("edits") or [], by=name or "owner (panel)")
        except ValueError as e:
            raise Refused(str(e))
        return {"edits": n, "started": runctl.start(f, stage="script")}
    if act == "approve":
        if not name:
            raise Refused("الاعتماد لازم يبقى عليه اسمك")
        call_cli(["approve", str(f), "--name", name] + (["--accept-local"] if d.get("accept_local") else []))
        panel._cache.clear()
        return {"approved": True}
    raise Refused("أمر مش معروف لكاتب السكريبت")


def style_page(slug):
    from ..core import profile as PR
    from ..script import sources as SRC, style as ST
    try:
        ch = PR.folder(slug)
    except PR.ProfileError as e:
        return {"error": str(e)}
    g = ch / "style" / "style_guide.md"
    st, ap = ST.status(ch)
    prof = ch / "style" / "style_profile.json"
    srcs = json.loads(SRC.list_path(ch).read_text(encoding="utf-8")) if SRC.list_path(ch).exists() else None
    reps = sorted(ch.glob("sources_check_*.md"))
    return {"checking": sources_checking(ch), "last_check": {"name": reps[-1].name, "text": reps[-1].read_text(encoding="utf-8")[:20000]} if reps else None,
            "slug": slug, "name": PR.load(slug).get("name", slug), "status": st, "approved": ap, "guide": g.read_text(encoding="utf-8") if g.exists() else None,
            "length": (json.loads(prof.read_text(encoding="utf-8")).get("length") if prof.exists() else None), "sources": srcs,
            "channels": [{"slug": s, "name": PR.load(s).get("name", s)} for s in PR.SLUGS]}


DELETE_WORD, RESTART_WORD = "احذف", "من الأول"


def trash_action(panel, path, d):
    """«حذف الحلقة» / «وقّف واحذف», «ابدأ من الأول», «رجّعها» (core/trash.py: nothing is ever deleted)"""
    from ..core import trash
    who = (d.get("name") or "owner").strip()
    try:
        if path == "/api/trash_restore":
            out = trash.restore(PROJECTS, d.get("folder") or "")
        else:
            f = panel.folders().get(d.get("id") or "")
            if not f or not str(d.get("id")).startswith("p:"):
                raise Refused("no such episode (test episodes are read-only)")
            word = DELETE_WORD if path == "/api/episode_trash" else RESTART_WORD
            if (d.get("confirm") or "").strip() != word:
                raise Refused(f"اكتب «{word}» عشان تأكّد")
            out = trash.trash_episode(f, who) if path == "/api/episode_trash" else trash.restart(f, who)
    except (ValueError, RuntimeError) as e:
        raise Refused(str(e))
    panel._cache.clear()
    return out


def spawn(cmd, out):
    """a detached engine command (closing the panel does not stop it)"""
    from ..core.paths import ENGINE
    return subprocess.Popen(cmd, cwd=str(ENGINE), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


def sources_checking(ch):
    """a sources check of this channel is running (its process is alive)"""
    f = ch / ".sources_check.pid"
    if not f.exists():
        return False
    from ..core.runctl import alive
    try:
        return alive(int(f.read_text().strip()))
    except (ValueError, OSError):
        return False


def style_action(d):
    from ..core import profile as PR
    from ..core.io import write_text
    from ..script import sources as SRC, style as ST
    try:
        ch = PR.folder(d.get("slug") or "")
    except PR.ProfileError as e:
        raise Refused(str(e))
    act = d.get("action")
    g = ch / "style" / "style_guide.md"
    if act == "save":                                 # the owner's edit: the approval then shows «edited after approval»
        text = d.get("text") or ""
        if len(text.strip()) < 20:
            raise Refused("دليل الأسلوب فاضي")
        g.parent.mkdir(parents=True, exist_ok=True)
        write_text(g, text if text.endswith("\n") else text + "\n")
        return style_page(d["slug"])
    if act == "approve":
        if not g.exists():
            raise Refused("القناة دي مالهاش دليل أسلوب لسه")
        if not (d.get("name") or "").strip():
            raise Refused("الاعتماد لازم يبقى عليه اسمك")
        ST.approve(ch, d["name"].strip())
        return style_page(d["slug"])
    if act == "check":                                # owner's answer 2 of phases 5-6: bin/monteer sources check, in the background
        if sources_checking(ch):
            raise Refused("المصادر بتتفحص دلوقتي بالفعل")
        if not SRC.list_path(ch).exists():
            raise Refused("القناة دي مالهاش قايمة مصادر لسه")
        from ..core.paths import ENGINE
        with open(ch / "sources_check.log", "a", encoding="utf-8") as out:
            out.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] sources check (panel)\n")
            out.flush()
            pr = spawn([str(ENGINE / "bin" / "monteer"), "sources", "check", str(ch)], out)
        (ch / ".sources_check.pid").write_text(str(pr.pid))
        threading.Thread(target=pr.wait, daemon=True).start()
        return style_page(d["slug"])
    if act in ("on", "off", "add", "init"):           # the channel's source list (bin/monteer sources …)
        if act == "init":
            SRC.init(ch)
            return style_page(d["slug"])
        srcs = SRC.load(ch)
        if act == "add":
            new = d.get("source") or {}
            miss = [k for k in ("id", "name", "kind", "lang", "access", "url") if not str(new.get(k, "")).strip()]
            if miss:
                raise Refused("المصدر ناقصه: " + "، ".join(miss))
            new = dict(new, on=True)
            srcs = [s for s in srcs if s["id"] != new["id"]] + [new]
        else:
            hit = [s for s in srcs if s["id"] == d.get("id")]
            if not hit:
                raise Refused("المصدر ده مش موجود")
            hit[0]["on"] = act == "on"
        SRC.save(ch, srcs)
        return style_page(d["slug"])
    raise Refused("أمر مش معروف لصفحة القناة")


def edit_prepare_detached(folder, n):
    """bin/monteer edit "<project>" prepare N, detached (closing the panel does not stop it); its words go to run/edit_log.txt"""
    from ..core.paths import ENGINE
    (folder / "run").mkdir(parents=True, exist_ok=True)
    with open(folder / "run" / "edit_log.txt", "a", encoding="utf-8") as out:
        out.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] prepare edit round {n}\n")
        out.flush()
        p = subprocess.Popen([str(ENGINE / "bin" / "monteer"), "edit", str(folder), "prepare", str(n)], cwd=str(ENGINE),
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    threading.Thread(target=p.wait, daemon=True).start()


def running_episodes(panel):
    """the panel's episodes whose run is going on now"""
    from ..core.runctl import lock_pid
    return [f.name for f in panel.folders().values() if lock_pid(f)]


def claude_signout(panel, d):
    """sign the Mac user out of Claude Code (owner's answer 1: offered, after a strong warning and a typed confirmation).
    It signs this macOS user out of Claude Code EVERYWHERE (the engine's brain and their own Claude Code sessions).
    Refused while not signed in, while an episode is running, or unless the person typed the signed-in email (or SIGN
    OUT when the account has no email)."""
    from ..core.claudebrain import claude_bin
    now = panel.brain_fresh()
    if now["state"] != "ok":
        raise Refused("Claude Code is not signed in on this Mac: nothing to sign out")
    busy = running_episodes(panel)
    if busy:
        raise Refused("an episode is running (" + ", ".join(busy[:3]) + "): stop it first; its brain needs the sign-in")
    want = now.get("email") or "SIGN OUT"
    if (d.get("confirm") or "").strip().lower() != want.lower():
        raise Refused(f"اكتب {'الإيميل المسجّل دخول بيه' if now.get('email') else 'SIGN OUT'} بالظبط عشان تأكّد")
    r = subprocess.run([claude_bin(), "auth", "logout"], capture_output=True, text=True, timeout=60)
    after = panel.brain_fresh()
    if after["state"] == "ok":
        raise Refused(f"Claude Code is still signed in (exit {r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
    return {"signed_out": True, "brain": after}


def actions(panel, path, d):
    """the panel's changes, each through the engine's own code"""
    from ..core import runctl
    from ..core.newproject import create
    if path == "/api/pick":
        kind = d.get("kind")
        if kind not in PICK:
            raise Refused("unknown kind of file")
        return {"files": [panel.probe(f) for f in pick(kind)]}
    if path == "/api/upload_remove":
        draft = panel.drafts(d.get("draft"))
        f = draft / Path(d.get("name") or "").name if draft else None
        if f and f.exists() and f.parent == draft:
            f.unlink()
        return {"removed": True}
    if path == "/api/new":
        title = (d.get("title") or "").strip()
        if not title:
            raise Refused("write the episode's title")
        folder = PROJECTS / (time.strftime("%Y-%m-%d_%H%M%S") + "_" + secrets.token_hex(3))
        clips = list(d.get("clips") or [])            # picked from this Mac: used where they are
        draft = panel.drafts(d.get("draft") or "")
        moved = []
        if draft and draft.exists():                  # uploaded from the browser: kept with the episode
            dst = folder / "input" / "clips"
            for f in sorted(draft.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    dst.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), dst / f.name)
                    moved.append(str(dst / f.name))
        src = panel.folders().get(d.get("script_from") or "") if d.get("script_from") else None
        try:
            p = create(folder, d.get("type"), title, d.get("video"), d.get("audio"), d.get("script"), d.get("profile"),
                       d.get("output") or "montage", d.get("run_mode") or "auto", d.get("instructions") or "", clips + moved,
                       ad=d.get("ad") or None, series_tag=bool(d.get("series_tag")), opening=d.get("opening") or None,
                       sources=d.get("sources") or None)
        except Exception as e:
            for m in moved:                           # nothing is lost: the uploads go back to the draft
                draft.mkdir(parents=True, exist_ok=True)
                shutil.move(m, draft / Path(m).name)
            if folder.exists() and not (folder / "project.json").exists():   # moved aside, never deleted (owner's rule)
                from ..core import trash
                trash.set_aside_refused(folder, str(e) or type(e).__name__, kind="new episode refused")
            raise
        if draft and draft.exists():                  # its files are in the episode now; the folder is moved aside
            from ..core import trash
            trash.set_aside_used_draft(draft)
        if src and (src / "script" / "approved.json").exists():   # an approved script: its lines, news items and cards come too
            shutil.copytree(src / "script", folder / "script", dirs_exist_ok=True)
            from ..core.io import load_json as _lj, save_json as _sj
            cfg = _lj(folder / "project.json")
            cfg.setdefault("inputs", {})["script"] = str(folder / "script" / "script.docx")
            cfg["script_from"] = src.name
            _sj(folder / "project.json", cfg)
        panel._cache.clear()
        started = runctl.start(p.folder) if d.get("start", True) else {}
        return {"id": "p:" + p.folder.name, "started": started}
    if path == "/api/answers":                    # step by step: the approval card's answers, then the run goes on
        f = panel.folders().get(d.get("id") or "")
        if not f or not str(d.get("id")).startswith("p:"):
            raise Refused("no such episode (test episodes are read-only)")
        from ..core.project import Project
        from ..montage import questions
        try:
            rows = questions.store(Project(f), d.get("mode") or "answers", d.get("answers") or {}, by="owner (panel)")
        except ValueError as e:
            raise Refused(str(e))
        panel._cache.clear()
        return {"kept": len(rows), "started": runctl.start(f)}
    if path in ("/api/episode_trash", "/api/episode_restart", "/api/trash_restore"):
        return trash_action(panel, path, d)
    if path == "/api/learn":                      # the box to tell «عام» things (montage/learning.py)
        from ..montage import learning
        try:
            if d.get("action") == "tell":
                learning.tell(d.get("text") or "", by=(d.get("name") or "owner").strip())
            elif d.get("action") == "forget":
                learning.forget(int(d.get("n") or 0))
            else:
                raise ValueError("unknown action")
        except ValueError as e:
            raise Refused(str(e))
        return {"general_box": learning.box()}
    if path == "/api/training":
        from ..core import training
        try:
            if d.get("action") == "add":
                training.add(d.get("slug") or "", d.get("pair") or {}, d.get("name"))
            elif d.get("action") == "remove":
                training.remove(d.get("slug") or "", d.get("id") or "")
            else:
                raise ValueError("unknown training action")
        except (ValueError, Exception) as e:  # noqa: BLE001  (an unknown channel or a bad pair: said as it is)
            raise Refused(str(e))
        return {"channels": training.library()}
    if path == "/api/rules":                      # editing a rule, with the owner's review
        from ..core import rulebook
        act = d.get("action")
        try:
            if act == "propose":
                rulebook.propose(d.get("n"), d.get("text"), d.get("name"))
            elif act == "approve":
                rulebook.approve(d.get("id") or "", d.get("name"))
            elif act == "reject":
                rulebook.reject(d.get("id") or "", d.get("name"), d.get("why"))
            else:
                raise ValueError("unknown rulebook action")
        except ValueError as e:
            raise Refused(str(e))
        return dict(rulebook.rules(), proposals=rulebook.proposals())
    if path == "/api/keys":                       # phase 8: add or remove a key (its value never comes back)
        from ..core import apikeys
        try:
            if d.get("remove"):
                apikeys.remove_key(d.get("name") or "")
            else:
                apikeys.set_key(d.get("name") or "", d.get("value") or "")
        except ValueError as e:
            raise Refused(str(e))
        panel._cache.clear()
        return {"keys": {n: bool(apikeys.get(n)) for n in apikeys.KNOWN}}
    if path == "/api/script":
        return script_action(panel, d)
    if path == "/api/style":
        return style_action(d)
    if path == "/api/edits":                      # edit until satisfied (phase 5): new round, apply, cancel
        f = panel.folders().get(d.get("id") or "")
        if not f or not str(d.get("id")).startswith("p:"):
            raise Refused("no such episode (test episodes are read-only)")
        from ..core.project import Project
        from ..montage import edits as ED
        p = Project(f)
        act = d.get("action")
        try:
            if act == "new":
                n = ED.new_round(p, d.get("requests") or [], by="owner (panel)")
                rd = ED.load(p)["rounds"][-1]
                if any(not (x.get("alt") or {}).get("kind") == "pick" for x in rd["requests"]):
                    edit_prepare_detached(f, n)      # the brain's part takes minutes: in the background
                    return {"round": n, "status": "preparing"}
                return {"round": n, "status": ED.prepare(p, n)["status"]}
            if act == "apply":
                panel._cache.clear()
                return ED.apply(p, int(d.get("n")))
            if act == "cancel":
                ED.cancel(p, int(d.get("n")))
                return {"cancelled": True}
            if act == "retry":                      # a failed round: the brain's part again
                rd = ED.rnd(ED.load(p), int(d.get("n")))
                if rd["status"] != "failed":
                    raise ValueError(f"round {rd['n']} is {rd['status']}")
                edit_prepare_detached(f, rd["n"])
                return {"round": rd["n"], "status": "preparing"}
        except ValueError as e:
            raise Refused(str(e))
        raise Refused("unknown edit action")
    if path == "/api/approve":                    # «موافقة نهائية»: the owner's final approval of one version
        f = panel.folders().get(d.get("id") or "")
        if not f or not str(d.get("id")).startswith("p:"):
            raise Refused("no such episode (test episodes are read-only)")
        from ..core.project import Project
        from ..montage import result as RES
        try:
            rec = RES.approve(Project(f), d.get("video") or "", d.get("by") or "")
        except ValueError as e:
            raise Refused(str(e))
        panel._cache.clear()
        return {"approved": rec}
    if path == "/api/claude_signout":
        return claude_signout(panel, d)
    if path in ("/api/run", "/api/stop"):
        eid = d.get("id") or ""
        f = panel.folders().get(eid)
        if not f:
            raise Refused("no such episode")
        if not eid.startswith("p:"):
            raise Refused("test episodes are read-only")
        panel._cache.clear()
        return runctl.start(f) if path == "/api/run" else runctl.stop(f)
    raise Refused("not found")


def locked_page():
    return ("<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><title>Monteer</title>"
            "<body style='font-family:system-ui;background:#0E0C0A;color:#F4EDDC;padding:48px;line-height:1.8'>"
            "<h2>مونتير</h2><p>اللوحة دي بتتفتح من الجهاز ده بس. اكتب العنوان ده بنفسك في المتصفح، أو افتحه من العلامة المحفوظة:</p>"
            "<pre style='background:#1B1713;padding:12px;border-radius:10px' dir='ltr'>http://127.0.0.1:8765/</pre>"
            "<p dir='ltr'>This panel opens on this Mac only. Type the address above yourself, or open your bookmark of it "
            "(a link from another page is not let in).</p></body></html>")


def panel_secret():
    """the page's secret, made once and kept for this user only (so a restart of the panel does not lock an open tab)"""
    f = KEYS.parent / "panel_secret"
    try:
        v = f.read_text().strip()
        if len(v) >= 32:
            return v
    except OSError:
        pass
    f.parent.mkdir(parents=True, exist_ok=True)
    f.parent.chmod(0o700)
    v = secrets.token_urlsafe(32)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(v)
    return v


def main(argv):
    from . import service
    if argv[:1] and argv[0] in ("install", "uninstall", "start", "stop", "restart", "status"):
        return service.main(argv[0])
    ap = argparse.ArgumentParser(prog="monteer panel")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="print the address but do not open the browser")
    ap.add_argument("--projects", help="the episodes folder (default: AI agent/monteer_projects)")
    a = ap.parse_args(argv)
    global PROJECTS
    if a.projects:
        PROJECTS = Path(a.projects).expanduser().resolve()
    PROJECTS.mkdir(parents=True, exist_ok=True)
    panel = Panel(a.port)
    Handler.panel = panel
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)     # this Mac only: never 0.0.0.0
    except OSError as e:
        by_hand = os.environ.get("XPC_SERVICE_NAME") != service.LABEL      # the service itself retries later instead
        if by_hand and a.port == service.PORT and service.loaded() and service.answering(wait=2):
            print(f"the panel is already running in the background: {service.URL}")
            if not a.no_open:
                subprocess.run(["open", service.URL], check=False)
            return 0
        print(f"the port {a.port} is busy ({e}): is the panel already open? Close it, or start with --port 8766")
        return 1
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Monteer panel: {url}  ({time.strftime('%Y-%m-%d %H:%M:%S')})\n(only on this Mac; Ctrl+C closes a panel started "
          "by hand; the background service: bin/monteer panel status)", flush=True)
    if not a.no_open:
        subprocess.run(["open", url], check=False)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\npanel closed")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
