/* Monteer panel (Works/output/web_panel_plan.md): 1 the shell and the episodes list; 2 New episode, start and stop;
   3 live progress, the paused-by-the-limit card, failures, the approval card; 4 the Result screen; 5 edit until
   satisfied; 6 the script writer and the style guides; 8 Integrations (the Claude account card, keys) and Costs;
   9 the rulebook with edits for review; the training library; the channels screen and «عام»'s box.
   Every figure on screen comes from the engine through /api (monteer/core/summary.py). A screen with no engine data yet
   says so plainly (owner's decision 2a: never fake data). */
(function () {
  "use strict";
  var M = window.Monteer;
  var S = { state: null, episodes: [], detail: null, route: "progress", sel: null, logOpen: false };

  /* ---------------------------------------------------------------- small helpers */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function en() { return document.documentElement.lang === "en"; }
  function t(ar, eng, tag, cls) {
    tag = tag || "span";
    return "<" + tag + (cls ? ' class="' + cls + '"' : "") + ' data-ar="' + esc(ar) + '" data-en="' + esc(eng) + '">' +
      esc(en() ? eng : ar) + "</" + tag + ">";
  }
  function ic(name, cls) { return '<i data-ic="' + name + '"' + (cls ? ' class="' + cls + '"' : "") + "></i>"; }
  function icons(root) {
    (root || document).querySelectorAll("i[data-ic]").forEach(function (n) {
      n.outerHTML = M.icon(n.getAttribute("data-ic"), n.className);
    });
  }
  function dur(s) {
    s = Math.round(s || 0);
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (r < 10 ? "0" : "") + r;
  }
  function tok(n, ar) {           /* 938056 -> "938K" / "938 ألف"; 2103562 -> "2.1M" / "2.1 مليون" */
    n = n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + (ar ? " مليون" : "M");
    if (n >= 1e3) return Math.round(n / 1e3) + (ar ? " ألف" : "K");
    return String(n);
  }
  function tokLine(b) {           /* "1.7M tokens (1.7M read · 64K written)" */
    if (!b.tokens) return null;
    return { ar: tok(b.tokens, true) + " توكن (" + tok(b.tokens_in, true) + " قراية · " + tok(b.tokens_out, true) + " كتابة)",
             en: tok(b.tokens) + " tokens (" + tok(b.tokens_in) + " read · " + tok(b.tokens_out) + " written)" };
  }
  function size(b) {
    if (b >= 1 << 30) return (b / (1 << 30)).toFixed(1) + " GB";
    if (b >= 1 << 20) return (b / (1 << 20)).toFixed(0) + " MB";
    return Math.max(1, Math.round(b / 1024)) + " KB";
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function api(path) {
    return fetch(path, { credentials: "same-origin", cache: "no-store" }).then(function (r) {
      if (r.status === 403) { location.reload(); throw new Error("locked"); }
      return r.json();
    });
  }
  function post(path, body) {
    return fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                         body: JSON.stringify(body || {}) }).then(function (r) { return r.json(); });
  }

  /* ---------------------------------------------------------------- the shell */
  var CRUMB = {
    progress: ["الحلقات / المتابعة", "Episodes / Progress"], "new": ["حلقة جديدة", "New episode"],
    result: ["الحلقات / النتيجة", "Episodes / Result"], script: ["كتابة السكريبت", "Script writer"],
    training: ["التعلّم / مكتبة التدريب", "Learning / Training library"], rules: ["التعلّم / الدستور", "Learning / Rulebook"],
    style: ["التعلّم / دليل أسلوب القناة", "Learning / Channel style guide"], costs: ["الحساب / التكاليف", "Account / Costs"],
    channels: ["التعلّم / القنوات", "Learning / Channels"], paid: ["الحساب / استخدام الخدمات المدفوعة", "Account / Paid services use"],
    integrations: ["الحساب / الربط بالخدمات", "Account / Integrations"]
  };
  function setNav() {
    document.querySelectorAll("a[data-nav]").forEach(function (a) { a.classList.toggle("on", a.getAttribute("data-nav") === S.route); });
    var c = document.querySelector(".crumb"), k = CRUMB[S.route] || CRUMB.progress;
    if (c) { c.setAttribute("data-ar", k[0]); c.setAttribute("data-en", k[1]); c.textContent = en() ? k[1] : k[0]; }
    var waiting = S.episodes.filter(function (e) { return e.scope === "projects" && ["waiting", "waiting_you", "script_gate"].indexOf(e.state) >= 0; }).length;
    var a = document.querySelector('a[data-nav="progress"]'), b = a && a.querySelector(".badge");
    if (a && waiting && !b) { a.insertAdjacentHTML("beforeend", '<span class="badge num">' + waiting + "</span>"); }
    else if (b) { if (waiting) b.textContent = waiting; else b.remove(); }
  }
  function setBrain() {
    var box = document.querySelector(".brain-mini");
    if (!box || !S.state) return;
    var b = S.state.brain, plan = b.plan ? " (" + b.plan.charAt(0).toUpperCase() + b.plan.slice(1) + ")" : "", h;
    var pz = (S.episodes || []).filter(function (e) { return e.state === "paused_limit"; })[0];
    if (b.state === "ok" && pz) {                  /* a run waits out the subscription's limit (run/brain_wait.json) */
      h = '<div class="row" style="gap:6px"><span class="dot" style="color:var(--warning)"></span>' + t("وصلت لحد الاشتراك", "Subscription limit reached", "b") + "</div>" +
        '<div class="ink2" style="margin-top:4px">' + t(pz.state_label.ar, pz.state_label.en) + "</div>";
    } else if (b.state === "ok") {
      h = '<div class="row" style="gap:6px"><span class="dot" style="color:var(--' + (b.subscription === false ? "warning" : "success") + ')"></span>' + t("العقل: Claude بتاعك", "Brain: your Claude", "b") + "</div>" +
        '<div class="ink2" style="margin-top:4px">' + (b.subscription === false
          ? t("حساب API مدفوع (Console): العقل هيتكلّف فلوس", "Paid API account (Console): the brain will cost money")
          : t("ضمن اشتراكك" + plan + " · من غير مفتاح API", "Included in your subscription" + plan + " · no API key")) + "</div>";
    } else if (b.state === "signed_out") {         /* the runs stop at their first step: not "local model only" */
      h = '<div class="row" style="gap:6px"><span class="dot" style="color:var(--danger)"></span>' + t("Claude مش مسجّل دخول", "Claude is not signed in", "b") + "</div>" +
        '<div class="ink2" style="margin-top:4px">' + t("الحلقات هتقف في أول خطوة لحد ما تسجّل دخول · ", "Episodes stop at their first step until you sign in · ") +
        '<a href="#/integrations">' + t("حساب Claude", "Claude account") + "</a></div>";
    } else if (b.state === "missing") {
      h = '<div class="row" style="gap:6px"><span class="dot" style="color:var(--danger)"></span>' + t("Claude Code مش متثبت", "Claude Code is not installed", "b") + "</div>" +
        '<div class="ink2" style="margin-top:4px"><a href="#/integrations">' + t("حساب Claude", "Claude account") + "</a></div>";
    } else {
      h = '<div class="row" style="gap:6px"><span class="dot" style="color:var(--warning)"></span>' + t("مش عارف أوصل لـClaude Code", "Can't reach Claude Code", "b") + "</div>" +
        '<div class="ink2" style="margin-top:4px">' + t("اتأكد إنه متثبت ومسجّل دخول", "Check that it is installed and logged in") + "</div>";
    }
    box.innerHTML = h;
    var av = document.querySelector(".avatar");
    if (av) { av.textContent = S.state.user.initial; av.title = S.state.user.name; }
  }

  /* ---------------------------------------------------------------- the episodes list */
  var STATE_CLS = { running: "infoc", waiting: "goldc", waiting_you: "goldc", paused_limit: "warnc", script_gate: "goldc", failed: "errc", start_failed: "errc", stopped: "warnc", stopped_by_you: "warnc", done: "okc",
                    approved: "ink2", script_done: "okc", script: "infoc", "new": "ink2" };
  function epItem(e) {
    var on = S.sel === e.id ? " on" : "";
    var thumb = e.error ? ic("alert") : ic(e.type === "voice_only" ? "wave" : "film");
    var lab = e.error ? t("مش قادر أقرا المشروع ده", "Can't read this project", "span", "micro errc")
      : t(e.state_label.ar, e.state_label.en, "span", "micro " + (STATE_CLS[e.state] || "ink2"));
    return '<a class="ep' + on + '" href="#/progress/' + encodeURIComponent(e.id) + '"><div class="thumb">' + thumb + "</div>" +
      '<div class="grow"><b class="small" style="font-weight:700;display:block">' + esc(e.name) + "</b>" + lab + "</div></a>";
  }
  function sideList() {
    var p = S.episodes.filter(function (e) { return e.scope === "projects"; });
    var tests = S.episodes.filter(function (e) { return e.scope === "tests"; })
      .sort(function (a, b) { return String(b.updated || "").localeCompare(String(a.updated || "")); });
    var h = '<div class="card" style="padding:16px"><div class="card-h" style="margin-bottom:6px">' + t("الحلقات", "Episodes", "b", "label") +
      '<a class="btn btn-ghost btn-sm" href="#/new">' + ic("plus", "sm") + t("جديدة", "New") + "</a></div>";
    h += '<div class="side-list">' + (p.length ? p.map(epItem).join("") :
      '<p class="small ink2">' + t("فولدر الحلقات لسه فاضي. أول حلقة بتتعمل من «حلقة جديدة».", "The episodes folder is still empty. The first episode starts from «New episode».") + "</p>") + "</div>";
    var tr = S.trash || [];
    if (tr.length) h += '<details class="pv-sec"><summary class="micro ink2">' + t("سلة المحذوفات", "Trash") + ' (<span class="num">' + tr.length + "</span>)</summary>" +
      tr.map(function (x) { return '<div class="row" style="gap:8px;padding:6px 0;border-bottom:1px solid var(--line)"><div class="grow"><b class="small" style="display:block" dir="auto">' + esc(x.name || x.folder) + "</b>" +
        '<span class="micro ink2">' + (x.kind === "restart" ? t("شغل قبل «ابدأ من الأول»", "work from before «start from zero»") : t("حلقة محذوفة", "deleted episode")) + " · " + esc(x.at || "") + "</span></div>" +
        '<button class="btn btn-ghost btn-sm" data-restore="' + esc(x.folder) + '">' + t("رجّعها", "Restore") + "</button></div>"; }).join("") +
      t("مفيش حاجة بتتمسح نهائي من هنا. تفريغ السلة بإيدك: فولدر monteer_projects/.trash.", "Nothing is erased from here. Emptying the Trash is yours to do: the folder monteer_projects/.trash.", "p", "micro ink2 pv-note") + "</details>";
    if (tests.length) {                          /* folded; open when a test episode is the one shown */
      var open = S.testsOpen || tests.some(function (e) { return e.id === S.sel; });
      h += '<details class="pv-sec" id="pv-tests"' + (open ? " open" : "") + '><summary class="micro ink2">' +
        t("حلقات الاختبار · للقراءة بس", "Test episodes · read-only") + ' (<span class="num">' + tests.length + "</span>)</summary>" +
        '<div class="side-list" style="margin-top:8px">' + tests.map(epItem).join("") + "</div></details>";
    }
    return h + "</div>";
  }

  /* ---------------------------------------------------------------- one episode */
  var CHIP = {
    done: ["ok", "خلصت", "Done"], running: ["gold", "شغّالة", "Running"], waiting: ["gold", "مستنية قرار", "Waiting for a decision"],
    queued: ["", "في الطابور", "Queued"], failed: ["err", "فشلت", "Failed"], not_needed: ["line", "مش مطلوبة", "Not needed"]
  };
  var STEP_CLS = { done: "done", running: "run", waiting: "wait", queued: "todo", failed: "fail", not_needed: "todo" };
  function stepRow(s, e) {
    var c = CHIP[s.state] || CHIP.queued, sn;
    if (s.state === "done") sn = ic("check", "sm");
    else if (s.state === "failed") sn = ic("alert", "sm");
    else sn = '<span class="num">' + s.n + "</span>";
    var line = en() ? s.detail : (s.detail_ar || s.detail);    /* the engine's line, in Egyptian Arabic (20 Oct 2026) */
    var detail = "", said = line ? '<span dir="auto" class="ink2"> · ' + esc(line) + "</span>" : "";
    if (s.state === "running" && e.state === "paused_limit") {
      var bw = e.brain_wait || {};
      return '<div class="step wait"><span class="sn"><span class="num">' + s.n + "</span></span><div>" + t(s.ar, s.en, "div", "st") +
        '<div class="sd">' + t("وصلت لحد الاشتراك — هتكمل لوحدها الساعة " + (bw.until_hm || "؟") + "، من نفس المكان، ومفيش حاجة بتضيع",
                              "The subscription limit was reached — it resumes by itself at " + (bw.until_hm || "?") + ", from the same place; nothing is lost") + "</div></div>" +
        '<span class="chip warn">' + t("متوقفة مؤقتًا", "Paused") + "</span></div>";
    }
    if (s.state === "done" && s.seconds >= 1) detail = t("خلصت في ", "Done in ") + '<span class="num tc">' + dur(s.seconds) + "</span>" + said;
    else if (s.state === "not_needed") detail = t(e.type === "voice_only" ? "مش مطلوبة لحلقة صوت بس" : "مش مطلوبة للناتج اللي اخترته",
                                                   e.type === "voice_only" ? "Not needed for an audio-only episode" : "Not needed for the chosen output");
    else if (s.state === "running" || s.state === "failed") detail = '<span dir="auto">' + esc(line || (en() ? e.last_log : "") || "") + "</span>";
    else if (s.state === "waiting") detail = e.state === "waiting_you" ? t("مستنية إجاباتك على أسئلة الخطة (تحت)", "Waiting for your answers on the plan (below)")
      : t("مستنية قرار من العقل (جلسة Claude Code)", "Waiting for a decision from the brain (a Claude Code session)");
    if (s.state === "waiting" && e.state === "waiting_you") c = ["gold", "مستنية إجاباتك", "Waiting for your answers"];
    var chip = s.state === "running" ? '<span class="chip gold"><span class="dot pulse"></span>' + t(c[1], c[2]) + "</span>"
      : '<span class="chip ' + c[0] + '">' + t(c[1], c[2]) + "</span>";
    return '<div class="step ' + STEP_CLS[s.state] + (s.state === "not_needed" ? " mutedc" : "") + '"><span class="sn">' + sn + "</span><div>" +
      t(s.ar, s.en, "div", "st") + (detail ? '<div class="sd">' + detail + "</div>" : "") + "</div>" + chip + "</div>";
  }
  var SCRIPT_STAGES = [["الموضوع", "Topic"], ["البحث وبطاقات الحقائق", "Research and fact cards"], ["الهيكل", "Outline"],
                       ["المسودة", "Draft"], ["المراجعة", "Review"], ["الاعتماد", "Approval"]];
  function scriptCard(sc) {
    var at = sc.approved ? 6 : /المسودة/.test(sc.stage) ? 4 : /الهيكل/.test(sc.stage) ? 3 : /البحث/.test(sc.stage) ? 2 : 1;
    var hs = SCRIPT_STAGES.map(function (x, i) {
      var n = i + 1, cls = n < at || (sc.approved && n === 6) ? "done" : n === at ? "on" : (n === 3 ? "gate" : "");
      return '<div class="hstep ' + cls + '"><span class="n">' + (cls === "done" ? ic("check", "sm") : n) + "</span>" + t(x[0], x[1]) + "</div>";
    }).join("");
    var gate = sc.waiting_for_you ? '<div class="banner gold pv-note">' + ic("alert") + "<div>" +
      t("الهيكل جاهز ومستني «أيوه» منك: ", "The outline is ready and waiting for your yes: ") + '<a href="#/script/' + encodeURIComponent(S.sel || "") + '">' + t("افتح السكريبت", "open the script") + "</a></div></div>" : "";
    return '<div class="card"><div class="card-h"><h2 class="h3">' + t("كتابة السكريبت", "Script writer") + "</h2>" +
      '<span class="small ink2">' + esc(sc.topic) + "</span></div><div class=\"hsteps\">" + hs + "</div>" + gate + "</div>";
  }
  function outputsCard(e) {
    if (!e.outputs || !e.outputs.length) return "";
    var K = { video: ["فيديو", "Video"], cut: ["التقطيع", "Cut"], report: ["تقرير", "Report"], credits: ["المصادر والرخص", "Credits"],
              data: ["بيانات", "Data"], other: ["ملف", "File"] };
    var rows = e.outputs.map(function (o) {
      var k = K[o.kind] || K.other;
      return '<div class="pv-out"><span class="chip ' + (o.kind === "video" || o.kind === "cut" ? "gold" : "line") + '">' + t(k[0], k[1]) + "</span>" +
        '<span class="name small" title="' + esc(o.name) + '">' + esc(o.name) + "</span>" +
        '<span class="micro ink2 num" dir="ltr">' + size(o.bytes) + " · " + esc(o.modified) + "</span></div>";
    }).join("");
    return '<div class="card"><div class="card-h"><h2 class="h3">' + t("الملفات اللي طلعت", "Outputs") + "</h2>" +
      '<span class="small ink2 num">' + e.outputs.length + "</span></div>" + rows +
      (e.outputs.some(function (o) { return o.kind === "video" || o.kind === "cut"; }) ? '<a class="btn btn-secondary btn-sm pv-note" href="#/result/' + encodeURIComponent(e.id) + '">' + ic("play", "sm flip") +
        t("افتح النتيجة", "Open the result") + "</a>" : "") + "</div>";
  }
  function detail(e) {
    if (!e) return emptyState();
    if (e.error) {
      return '<div class="card"><h2 class="h2">' + esc(e.name) + '</h2><p class="pv-err small" dir="ltr">' + esc(e.error) + "</p></div>";
    }
    var typeChip = e.type === "voice_only" ? '<span class="chip">' + ic("wave") + t("صوت بس", "Audio only") + "</span>"
      : '<span class="chip">' + ic("mic") + t("بمذيع", "With presenter") + "</span>";
    var outChip = e.output === "cut" ? '<span class="chip">' + t("بعد التقطيع بس", "Cut only") + "</span>"
      : '<span class="chip">' + t("المونتاج الكامل", "Full montage") + "</span>";
    var modeChip = e.run_mode === "step" ? '<span class="chip gold">' + t("خطوة بخطوة", "Step by step") + "</span>"
      : '<span class="chip">' + t("تلقائي", "Automatic") + "</span>";
    var ro = e.read_only ? '<span class="chip line">' + t("اختبار · للقراءة بس", "Test · read-only") + "</span>" : "";
    var pct = Math.round((e.progress || 0) * 100);
    var b = e.brain || {};
    var tl = tokLine(b) || { ar: "التوكنز مش متسجلة للقرارات دي", en: "tokens not recorded for these decisions" };
    var brainLine = b.decisions_by_brain ? '<div class="small ink2 pv-note">' +
      t("العقل: " + b.decisions_by_brain + " قرار · وقت العقل " + dur(b.brain_seconds) + " · " + tl.ar + " · ضمن اشتراكك (مكافئ API $" + b.api_equivalent_usd.toFixed(2) + "، للعرض بس، مش مدفوع)",
        "Brain: " + b.decisions_by_brain + " decisions · brain time " + dur(b.brain_seconds) + " · " + tl.en + " · within your subscription (API equivalent $" + b.api_equivalent_usd.toFixed(2) + ", shown only, not charged)") + "</div>" : "";
    var act = "";
    if (e.scope === "projects") {
      if (e.running) act = '<button class="btn btn-secondary btn-sm" data-stop="' + esc(e.id) + '">' + ic("pause", "sm") +
        t(S.stopArm === e.id ? "اضغط تاني عشان توقّف" : "وقّف الشغل", S.stopArm === e.id ? "Click again to stop" : "Stop the run") + "</button>";
      else if (["stopped", "stopped_by_you", "failed", "new", "waiting", "start_failed"].indexOf(e.state) >= 0) act = '<button class="btn btn-primary btn-sm" data-run="' + esc(e.id) + '">' +
        ic("play", "sm flip") + (e.state === "start_failed" ? t("حاول تاني", "Try again") : t(e.state === "new" ? "ابدأ الشغل" : "كمّل الشغل", e.state === "new" ? "Start" : "Resume")) + "</button>";
    }
    var head = '<div class="card em lg"><div class="row between top"><div><div class="row wrap" style="gap:8px;margin-bottom:8px">' +
      typeChip + outChip + modeChip + ro + "</div><h1 class=\"h1\">" + esc(e.name) + "</h1>" +
      t(e.state_label.ar, e.state_label.en, "div", "small " + (STATE_CLS[e.state] || "ink2")) + "</div>" +
      '<div style="text-align:end">' + t("آخر تحديث", "Last update", "div", "micro ink2") + '<div class="h3 num" dir="ltr" style="white-space:nowrap">' + esc(e.updated || "—") + "</div>" +
      (e.running && e.eta ? t(e.eta.ar, e.eta.en, "div", "small ink2") : "") +   /* from the steps' measured times, live */
      (act ? '<div style="margin-top:10px">' + act + "</div>" : "") + "</div></div>" +
      (e.start_error && !S.actMsg ? '<div class="banner err pv-note">' + ic("alert") + "<div>" + t("المحرك رفض يبدأ، وده اللي قاله:", "The engine refused to start; this is what it said:") +
        '<pre class="pv-log" dir="ltr" style="margin-top:6px;white-space:pre-wrap">' + esc(e.start_error) + "</pre></div></div>" : "") +
      (S.actMsg ? '<div class="banner ' + (S.actMsg.err ? "err" : "info") + ' pv-note">' + ic("alert") + "<div>" + t(S.actMsg.ar, S.actMsg.en) + "</div></div>" : "") +
      '<div class="row" style="gap:14px;margin-top:16px"><div class="bar grow" style="height:10px"><i style="width:' + pct + '%"></i></div><b class="num">' + pct + "%</b></div>" +
      brainLine + "</div>";
    var hasRun = e.steps.some(function (s) { return s.state !== "queued" && s.state !== "not_needed"; });
    var steps = (hasRun || !e.script) ? '<div class="card"><div class="card-h"><h2 class="h3">' + t("الخطوات التسعة", "The 9 steps") + "</h2>" +
      (e.current_step ? '<span class="small ink2">' + t("خطوة " + e.current_step + " من ٩", "Step " + e.current_step + " of 9") + "</span>" : "") +
      '</div><div class="steps">' + e.steps.map(function (s) { return stepRow(s, e); }).join("") + "</div></div>" : "";
    var brainWaits = (e.waiting || []).filter(function (w) { return w.kind !== "owner"; });
    var waits = brainWaits.length ? '<div class="card"><div class="card-h"><h2 class="h3">' + t("قرارات مستنية العقل", "Decisions waiting for the brain") + "</h2></div>" +
      brainWaits.map(function (w) { return '<div class="small" dir="ltr">' + esc(w.step + "/" + w.key) + " — " + esc(w.why) + "</div>"; }).join("") +
      '<p class="micro ink2 pv-note">' + t("الحلقة دي شغّالة بعقل جلسة Claude Code: القرارات دي بتتجاوب في الجلسة (bin/monteer brain answer …)، وبعدين «كمّل الشغل».",
        "This episode runs with a Claude Code session as its brain: these are answered in the session (bin/monteer brain answer …), then «Resume».") + "</p></div>" : "";
    var log = e.log && e.log.length ? '<div class="card"><details' + (S.logOpen ? " open" : "") + ' id="pv-log"><summary class="label">' +
      t("آخر سطور السجل (الأحدث فوق)", "Last lines of the run log (newest first)") + '</summary><pre class="pv-log">' + esc(e.log.slice().reverse().join("\n")) + "</pre></details></div>" : "";
    return head + dangerZone(e) + pausedCard(e) + failCard(e) + approvalCard(e) + (e.script ? scriptCard(e.script) : "") + steps + waits + outputsCard(e) + log;
  }
  /* ---------------------------------------------------------------- phase 3: paused by the limit, a failed step, the approval card */
  /* delete (to the Trash) and start from zero: a running episode is stopped safely first; nothing is ever deleted */
  function dangerZone(e) {
    if (e.scope !== "projects") return "";
    var z = S.dz && S.dz.id === e.id ? S.dz : null, run = e.running;
    var h = '<div class="row wrap" style="gap:8px;justify-content:flex-end">' +
      '<button class="btn btn-ghost btn-sm" data-dz="restart" data-dzid="' + esc(e.id) + '">' + ic("retry", "sm") + t(run ? "وقّف وابدأ من الأول" : "ابدأ من الأول", run ? "Stop and start from zero" : "Start from zero") + "</button>" +
      '<button class="btn btn-ghost btn-sm" data-dz="trash" data-dzid="' + esc(e.id) + '" style="color:var(--danger)">' + ic("x", "sm") + t(run ? "وقّف واحذف" : "حذف الحلقة", run ? "Stop and delete" : "Delete the episode") + "</button></div>";
    if (!z) return h;
    var del = z.kind === "trash", word = del ? "احذف" : "من الأول";
    return h + '<div class="card" style="border-color:var(--danger)">' + '<div class="small"><b>' +
      (del ? t("الحلقة هتروح سلة المحذوفات (مش هتتمسح).", "The episode goes to the Trash (it is not erased).") : t("الحلقة هتبدأ من الصفر بنفس الملفات والإعدادات.", "The episode starts again from zero with the same files and settings.")) + "</b> " +
      (run ? t("الشغل اللي شغّال هيتوقف بأمان الأول. ", "The running work is stopped safely first. ") : "") +
      (del ? t("تقدر ترجّعها من «سلة المحذوفات» تحت قايمة الحلقات.", "You can bring it back from «Trash» under the episodes list.")
        : t("شغل المرة اللي فاتت (القرارات والملفات والفيديوهات) بيروح سلة المحذوفات، والسكريبت وملفاتك بيفضلوا.", "The last run's work (decisions, files, videos) goes to the Trash; the script and your files stay.")) + "</div>" +
      '<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center">' + t("للتأكيد اكتب: ", "To confirm, type: ", "span", "small") + '<b class="small">«' + word + '»</b>' +
      '<input class="input" id="del-word" dir="auto" style="height:34px;width:160px" autocomplete="off" value="' + esc(z.text || "") + '">' +
      '<button class="btn btn-primary btn-sm" data-dzgo' + ((z.text || "").trim() === word && !z.busy ? "" : " disabled") + ">" +
      t(z.busy ? "لحظة…" : (del ? (run ? "وقّف واحذف" : "احذف") : (run ? "وقّف وابدأ من الأول" : "ابدأ من الأول")), z.busy ? "One moment…" : (del ? (run ? "Stop and delete" : "Delete") : (run ? "Stop and start from zero" : "Start from zero"))) + "</button>" +
      '<button class="btn btn-ghost btn-sm" data-dzno>' + t("إلغي", "Cancel") + "</button></div></div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-dz],[data-dzgo],[data-dzno],[data-restore]") : null;
    if (!el || el.disabled) return;
    if (el.hasAttribute("data-dz")) { S.dz = { id: el.getAttribute("data-dzid"), kind: el.getAttribute("data-dz"), text: "" }; render(); var i = document.getElementById("del-word"); if (i) i.focus(); return; }
    if (el.hasAttribute("data-dzno")) { S.dz = null; render(); return; }
    if (el.hasAttribute("data-restore")) {
      post("/api/trash_restore", { folder: el.getAttribute("data-restore") }).then(function (d) {
        S.actMsg = d.error ? { ar: "مارجعتش: " + d.error, en: "Not restored: " + d.error, err: true } : { ar: "رجعت لقايمة الحلقات.", en: "It is back in the episodes list." }; loadTrash(); refresh(); });
      return;
    }
    var z = S.dz, del = z.kind === "trash";
    z.busy = true; render();
    post(del ? "/api/episode_trash" : "/api/episode_restart", { id: z.id, confirm: z.text, name: who() }).then(function (d) {
      S.dz = null;
      if (d.error) S.actMsg = { ar: "ماتنفذش: " + d.error, en: "Not done: " + d.error, err: true };
      else if (del) { S.actMsg = { ar: "الحلقة راحت سلة المحذوفات.", en: "The episode went to the Trash." }; S.sel = null; location.hash = "#/progress"; }
      else S.actMsg = { ar: "الحلقة بدأت من الأول؛ الشغل القديم في سلة المحذوفات.", en: "The episode started from zero; the old work is in the Trash." };
      loadTrash(); refresh();
    });
  });
  document.addEventListener("input", function (ev) {
    if (ev.target.id !== "del-word" || !S.dz) return;
    S.dz.text = ev.target.value;
    var b = document.querySelector("[data-dzgo]"); if (b) b.disabled = S.dz.text.trim() !== (S.dz.kind === "trash" ? "احذف" : "من الأول");
  });
  function loadTrash() { api("/api/trash").then(function (d) { var was = JSON.stringify(S.trash || []); S.trash = d.items || []; if (was !== JSON.stringify(S.trash) && S.route === "progress" && !typing()) render(); }); }
  function pausedCard(e) {
    if (e.state !== "paused_limit" || !e.brain_wait) return "";
    var left = Math.max(0, Math.round((e.brain_wait.until * 1000 - Date.now()) / 60000));
    return '<div class="banner warn pv-note">' + ic("clock") + '<div class="grow">' +
      t("وصلت لحد اشتراك Claude", "The Claude subscription's limit was reached", "b") + '<div class="small" style="margin-top:4px">' +
      t("الشغل مستني لوحده ويكمّل الساعة " + e.brain_wait.until_hm + " (بعد حوالي " + left + " دقيقة)" + (e.brain_wait.reset_known ? "" : " — الميعاد ده تقدير، بيجرّب كل ١٠ دقايق") +
        ". مش مطلوب منك حاجة: مفيش حاجة بتضيع، والماك بيفضل صاحي.",
        "The run waits by itself and resumes at " + e.brain_wait.until_hm + " (in about " + left + " min)" + (e.brain_wait.reset_known ? "" : " — an estimate; it tries every 10 minutes") +
        ". Nothing is asked of you: nothing is lost, and the Mac stays awake.") + "</div></div></div>";
  }
  function failCard(e) {
    var f = e.failure;
    if (!f) return "";
    return '<div class="card" style="border-color:var(--danger)"><div class="row" style="gap:8px">' + ic("alert") + t("وقفت ليه: ", "Why it stopped: ", "b") + t(f.reason_ar, f.reason_en, "b", "errc") + "</div>" +
      (f.why ? '<div class="small pv-note" dir="auto">' + esc(f.why) + "</div>" : "") +
      t(f.saved_ar, f.saved_en, "p", "small ink2 pv-note") +
      '<details class="pv-note"><summary class="micro ink2">' + t("التفاصيل (آخر سطور الخطوة " + (f.step || "") + ")", "Details (the last lines of step " + (f.step || "") + ")") + '</summary><pre class="pv-log" dir="ltr">' + esc((f.details || []).join("\n")) + "</pre></details></div>";
  }
  function ansOf(e) {
    var A = S.ans || (S.ans = {});
    if (!A[e.id]) { A[e.id] = {}; (e.approval.questions || []).forEach(function (q) { A[e.id][q.n] = { choice: q.pick, text: "" }; }); }
    return A[e.id];
  }
  function approvalCard(e) {
    var ap = e.approval;
    if (!ap || !ap.questions) return "";
    if (ap.answered && e.state !== "waiting_you") {
      var M2 = { answers: ["إجاباتك", "your answers"], accept_all: ["وافقت على كل التوصيات", "you accepted every recommendation"], let_it_decide: ["سبته يقرر ويكمّل", "you let it decide and go on"] }[ap.answered.mode] || ["", ""];
      return '<div class="banner info pv-note">' + ic("check") + '<div class="small">' + t("أسئلة الخطة اتجاوبت (" + M2[0] + ") الساعة " + esc(ap.answered.at), "The plan's questions were answered (" + M2[1] + ") at " + esc(ap.answered.at)) + "</div></div>";
    }
    var a = ansOf(e), ro = e.read_only, mix = Object.keys(ap.mix || {}).map(function (k) { return esc(k) + " " + Math.round((+ap.mix[k] || 0) * 100) + "%"; }).join(" · ");
    var h = '<div class="card em" id="pv-approval" style="border-color:var(--gold)"><div class="card-h"><h2 class="h3">' + t("الوكيل محتاج رأيك قبل ما يجمع الماتيريال", "The agent needs your view before it gathers the material") + "</h2>" +
      '<span class="chip gold">' + t(ap.questions.length + " أسئلة", ap.questions.length + " questions") + "</span></div>" +
      t("الخطة جاهزة. دي الاختيارات اللي كان فيها بدائل حقيقية؛ توصيته متعلّم عليها ومختارة من الأول. غيّر اللي عايزه وابعت كله مرة واحدة.",
        "The plan is ready. These are the choices that had real alternatives; its recommendation is marked and chosen to start with. Change what you want and send all at once.", "p", "small ink2");
    ap.questions.forEach(function (q) {
      var cur = a[q.n] || {};
      h += '<div class="pv-q" style="margin-top:16px"><div class="row" style="gap:8px;align-items:baseline"><b class="num">' + q.n + ".</b><b dir=\"auto\">" + esc(q.question) + "</b></div>" +
        '<div class="col" style="gap:6px;margin-top:8px">' + q.options.map(function (o) {
          var on = cur.choice === o.key;
          return '<button class="opt' + (on ? " on" : "") + '" data-ans="' + q.n + '" data-key="' + esc(o.key) + '"' + (ro ? " disabled" : "") + ' style="padding:10px 14px"><span class="radio"></span><span class="col" style="gap:2px"><span dir="auto">' + esc(o.label) + "</span>" +
            (o.key === q.pick ? '<span class="small goldc">' + t("توصيتي: ", "My recommendation: ") + '<span dir="auto">' + esc(q.why) + "</span></span>" : "") + "</span></button>";
        }).join("") +
        '<button class="opt' + (cur.choice === "other" ? " on" : "") + '" data-ans="' + q.n + '" data-key="other"' + (ro ? " disabled" : "") + ' style="padding:10px 14px"><span class="radio"></span><span>' + t("إجابة تانية", "Another answer") + "</span></button>" +
        (cur.choice === "other" ? '<input class="input" data-anstext="' + q.n + '" dir="auto" maxlength="1000" style="height:38px" value="' + esc(cur.text || "") + '" placeholder="' + esc(en() ? "Your answer" : "إجابتك") + '">' : "") +
        "</div></div>";
    });
    if (mix) h += '<p class="micro ink2 pv-note">' + t("مزيج الماتيريال في الخطة: ", "The plan's material mix: ") + '<span dir="ltr">' + mix + "</span></p>";
    var missing = ap.questions.filter(function (q) { var c = a[q.n] || {}; return !c.choice || (c.choice === "other" && !(c.text || "").trim()); }).length;
    if (!ro) h += '<div class="row wrap" style="gap:8px;margin-top:16px"><button class="btn btn-primary" data-send="answers"' + (missing || S.ansBusy ? " disabled" : "") + ">" + t("ابعت الإجابات", "Send the answers") + "</button>" +
      '<button class="btn btn-secondary" data-send="accept_all"' + (S.ansBusy ? " disabled" : "") + ">" + t("وافق على كل التوصيات", "Accept every recommendation") + "</button>" +
      '<button class="btn btn-ghost" data-send="let_it_decide"' + (S.ansBusy ? " disabled" : "") + ">" + ic("moon", "sm") + t("سيبه يقرر ويكمّل طول الليل", "Let it decide and go on overnight") + "</button></div>" +
      (missing ? t("لسه " + missing + " سؤال من غير إجابة.", missing + " question(s) still without an answer.", "p", "micro warnc pv-note") : "") +
      t("الإجابات اللي بتختلف عن توصيته بتخلي الخطة تتعمل تاني على أساسها (من غير ما تتخطى القواعد الثابتة)، وبعدها الشغل يكمّل لوحده.",
        "Answers that differ from its recommendation make the plan again on them (never over the standing rules); then the run goes on by itself.", "p", "micro ink2 pv-note");
    return h + "</div>";
  }
  function emptyState() {
    return '<div class="card"><div class="empty"><div class="ico">' + ic("film", "xl") + "</div>" +
      t("أول حلقة ليك تبدأ من هنا", "Your first episode starts here", "h2", "h2") +
      t("ارفع الكاميرا والمايك والسكريبت — أو ملف صوت بس — والوكيل يرجّعلك فيديو خلصان.",
        "Upload the raw camera, mic and script — or just an audio file — and the agent returns a finished video.", "p", "ink2 small") +
      '<div class="row"><a class="btn btn-primary" href="#/new">' + ic("plus", "sm") + t("حلقة جديدة", "New episode") + "</a>" +
      '<a class="btn btn-secondary" href="#/script">' + t("اكتب سكريبت الأول", "Write a script first") + "</a></div></div></div>";
  }

  /* ---------------------------------------------------------------- screens with no engine data yet (decision 2a) */
  var LATER = {
    result: ["play", "النتيجة", "Result", 4,
      "المشغّل بعلامات «اتفرّج على دول الأول»، أرقام الحلقة، مزيج الماتيريال، المصادر والرخص — وبعدها (المرحلة ٥) طلبات التعديل بالتوقيت لحد ما توافق موافقة نهائية.",
      "The player with its «watch these first» marks, the episode's figures, the material mix, credits — then (phase 5) timecoded edit requests until your final approval."],
    script: ["pen", "كتابة السكريبت", "Script writer", 6,
      "الموضوع والمصادر، بطاقات الحقائق، الهيكل وموافقتك، المسودة وفحوصها، المراجعة والاعتماد. المحرك نفسه بيعمل كل ده من دلوقتي بالأمر bin/monteer script.",
      "Topic and sources, fact cards, the outline and your yes, the draft and its checks, review and approval. The engine already does all of this with bin/monteer script."],
    training: ["book", "مكتبة التدريب", "Training library", 0,
      "أزواج الخام والمنشور وإيه اللي الوكيل اتعلمه منها. قرارك: بعدين، كمشروع لوحده.",
      "Raw and published pairs and what the agent learnt from each. Your decision: later, as its own project."],
    rules: ["rules", "الدستور", "Rulebook", 9,
      "القواعد ١–٢٤ وقراراتك الثابتة كجداول، وكل قاعدة فين بتتطبّق في الكود. أول نسخة للقراءة بس.",
      "Rules 1–24 and your standing decisions as tables, with where each is applied in code. The first version is read-only."],
    style: ["doc", "دليل أسلوب القناة", "Channel style guide", 6,
      "أقسام الدليل وأمثلته واعتماده. المحرك عنده الدليل من دلوقتي (channel/style/style_guide.md).",
      "The guide's sections, examples and approval. The engine already has the guide (channel/style/style_guide.md)."],
    costs: ["coins", "التكاليف", "Costs", 8,
      "لكل حلقة: وقت العقل ومكافئ الـAPI (حقيقي، من سجلات القرارات — بيظهر من دلوقتي في صفحة الحلقة)، الخدمات المدفوعة (صفر)، والأدوات المحلية (صفر).",
      "Per episode: brain time and the API equivalent (real, from the decision records — already shown on each episode), paid services (zero) and local tools (zero)."],
    channels: ["list", "القنوات", "Channels", 10,
      "القنوات الخمسة: إعدادات المونتاج لكل قناة، اللوجو والفواصل، الفيديوهات المرجعية، ودليل الأسلوب — ومربع تقول فيه حاجة لـ«عام».",
      "The five channels: each one's montage settings, logo and stings, reference videos and style guide — and a box to tell «عام» things."],
    integrations: ["plug", "الربط بالخدمات", "Integrations", 8,
      "العقل وتسجيل دخوله، النموذج المحلي، والمفاتيح (موجود / مش موجود بس — القيم مابتطلعش من الجهاز).",
      "The brain and its login, the local model, and the keys (present / missing only — values never leave the Mac)."]
  };
  /* ---------------------------------------------------------------- Costs (the design's 07-costs, with real figures only) */
  function costs() {
    var eps = (S.episodes || []).filter(function (e) { return e.brain && (e.brain.decisions_by_brain || e.scope === "projects"); })
      .sort(function (a, b) { return (b.scope === "projects") - (a.scope === "projects") || String(b.updated || "").localeCompare(String(a.updated || "")); });
    var sum = { tokens: 0, tokens_in: 0, tokens_out: 0, s: 0, usd: 0, n: 0 };
    eps.forEach(function (e) { var b = e.brain; sum.tokens += b.tokens; sum.tokens_in += b.tokens_in; sum.tokens_out += b.tokens_out; sum.s += b.brain_seconds; sum.usd += b.api_equivalent_usd; sum.n += b.decisions_by_brain; });
    var withTok = eps.filter(function (e) { return e.brain.tokens; });
    var h = '<div class="page-h"><div>' + t("التكاليف", "Costs", "h1", "h1") +
      t("التشغيل المجاني تكلفته ٠. شغل العقل على اشتراك Claude بتاعك. الخدمات المدفوعة مابتشتغلش غير بموافقتك.",
        "Free runs cost 0. Brain work runs on your own Claude subscription. Paid services only run after your approval.", "p") + "</div></div>";
    h += '<div class="grid g3" style="gap:24px">' +
      paidStat() +
      '<div class="stat" style="padding:20px">' + t("توكنز العقل (كل الحلقات)", "Brain tokens (all episodes)") + '<b class="num" dir="ltr">' + tok(sum.tokens) + "</b>" +
        t(tok(sum.tokens_in, true) + " قراية · " + tok(sum.tokens_out, true) + " كتابة", tok(sum.tokens_in) + " read · " + tok(sum.tokens_out) + " written", "span", "small mutedc") + "</div>" +
      '<div class="stat" style="padding:20px">' + t("وقت العقل (كل الحلقات)", "Brain time (all episodes)") + '<b class="num" dir="ltr">' + dur(sum.s) + "</b>" +
        t(sum.n + " قرار · ضمن اشتراكك", sum.n + " decisions · within your subscription", "span", "small mutedc") + "</div></div>";
    h += '<div class="banner info pv-note">' + ic("spark") + '<div class="grow small">' + t("العقل مابيكلّفكش حاجة زيادة. ", "The brain costs you nothing extra. ", "b") +
      t("بيشغّل Claude Code على اشتراكك. التوكنز هي كمية الكلام اللي العقل قراه (الطلب والملفات وكلامه اللي قبل كده) وكتبه، من سجل كل قرار. «المكافئ بالـAPI» بيوريك بس الشغل ده كان هيتكلف كام على API مدفوع — مش بيتدفع.",
        "It runs Claude Code on your own subscription. Tokens are how much text the brain read (the request, the files and its own earlier turns) and wrote, from each decision's record. “API equivalent” only shows what the same work would cost on a paid API — it is not charged.") + "</div></div>";
    var rows = eps.map(function (e) {
      var b = e.brain, tl = tokLine(b);
      return "<tr><td><b style=\"font-weight:700\">" + esc(e.name) + "</b>" + (e.scope !== "projects" ? ' <span class="chip line">' + t("اختبار", "test") + "</span>" : "") +
        '<div class="small ink2 num" dir="ltr">' + esc(e.updated || "—") + "</div></td>" +
        '<td><span class="chip gold">' + t("ضمن الاشتراك", "Within subscription") + '</span><div class="small ink2" style="margin-top:4px">' + ic("clock", "sm") + ' <span class="num">' + dur(b.brain_seconds) + "</span> · " +
          '<span class="num">' + b.decisions_by_brain + "</span> " + t("قرار", "decisions") + "</div></td>" +
        "<td>" + (tl ? '<b class="num" dir="ltr">' + tok(b.tokens) + '</b><div class="small ink2">' + t(tok(b.tokens_in, true) + " قراية · " + tok(b.tokens_out, true) + " كتابة", tok(b.tokens_in) + " read · " + tok(b.tokens_out) + " written") + "</div>"
          : '<span class="small mutedc">' + (b.decisions_by_brain ? t("مش متسجلة", "not recorded") : "0") + "</span>") +
          (b.without_tokens ? '<div class="micro mutedc">' + t(b.without_tokens + " قرار من غير تسجيل توكنز", b.without_tokens + " decisions without a token record") + "</div>" : "") + "</td>" +
        '<td class="small ink2"><span class="num" dir="ltr">$' + b.api_equivalent_usd.toFixed(2) + "</span> " + t("(مش بتتدفع)", "(not charged)", "span", "mutedc") + "</td>" +
        '<td><span class="num">0</span></td><td><span class="num">0</span> ' + t("محلي", "local", "span", "small ink2") + "</td>" +
        '<td><span class="chip ok num">0</span></td></tr>';
    }).join("");
    h += '<div class="card" style="padding:8px 8px 4px;overflow-x:auto"><table class="tbl"><thead><tr><th>' + t("الحلقة", "Episode") + "</th><th>" + t("العقل (Claude)", "Brain (Claude)") + "</th><th>" +
      t("التوكنز", "Tokens") + "</th><th>" + t("المكافئ بالـAPI", "API equivalent") + "</th><th>" + t("خدمات مدفوعة", "Paid services") + "</th><th>" + t("أدوات محلية مجانية", "Free local tools") + "</th><th>" +
      t("الإجمالي", "Total") + "</th></tr></thead><tbody>" + (rows || '<tr><td colspan="7" class="small ink2">' + t("لسه مفيش حلقة اشتغل عليها العقل.", "No episode has used the brain yet.") + "</td></tr>") + "</tbody></table></div>";
    h += t("الأرقام من سجلات القرارات اللي العقل اللي في الخلفية أخدها. القرارات اللي اتاخدت يدوي من جلسة Claude Code مالهاش سجل توكنز. الشهر والسقف تحت.",
           "Figures come from the decisions the background brain made. Decisions made by hand in a Claude Code session have no token record. The month view and the cap are below.", "p", "small mutedc pv-note");
    return h;
  }
  /* ---------------------------------------------------------------- Integrations: the Claude account card (W1) and sign-out */
  function row(ar, eng, val) {
    return '<div class="row between" style="gap:16px;padding:8px 0;border-bottom:1px solid var(--line)">' + t(ar, eng, "span", "ink2") + "<span>" + val + "</span></div>";
  }
  function integrations() {
    var b = (S.state && S.state.brain) || {}, so = S.so || (S.so = { open: false, text: "", busy: false, msg: null });
    var yes = function (ar, eng) { return t(ar, eng, "b", "okc"); }, no = function (ar, eng) { return t(ar, eng, "b", "warnc"); };
    var h = '<div class="col" style="gap:24px;max-width:760px">';
    h += '<div class="card"><div class="row between"><h2 class="h3">' + t("حساب Claude (العقل)", "Claude account (the brain)") + "</h2>" +
      '<button class="btn btn-secondary btn-sm" data-brain-check>' + ic("retry", "sm") + " " + t("اتأكد تاني", "Check again") + "</button></div>" +
      '<div class="small" style="margin-top:12px">';
    var u = (S.state && S.state.user) || {}, who = (u.name ? u.name + " " : "") + "(" + (u.account || "?") + ")";
    h += row("مستخدم الماك", "macOS user", '<span dir="auto">' + esc(who) + "</span>");
    h += row("Claude Code متثبت", "Claude Code installed", b.state === "missing" ? no("لأ", "No") :
      yes("أيوه", "Yes") + (b.version ? ' <span class="num ink2" dir="ltr">' + esc(b.version) + "</span>" : ""));
    if (b.state !== "missing") {
      h += row("مسجّل دخول", "Signed in", b.state === "ok" ? yes("أيوه", "Yes") : b.state === "signed_out" ? no("لأ", "No") : no("مش عارف أقرا الحالة", "Can't read the status"));
    }
    if (b.state === "ok") {
      h += row("الإيميل", "Email", '<span dir="ltr">' + esc(b.email || "—") + "</span>");
      h += row("الخطة", "Plan", esc(b.plan ? b.plan.charAt(0).toUpperCase() + b.plan.slice(1) : "—"));
      h += row("نوع الحساب", "Account type", b.subscription ? yes("اشتراك Claude (من غير تكلفة زيادة)", "Claude subscription (no extra cost)")
        : no("API مدفوع (" + esc(b.method || "?") + ")", "Paid API (" + esc(b.method || "?") + ")"));
    }
    h += '<div class="small mutedc" style="margin-top:8px">' + t("آخر مرة اتأكدت: ", "Last checked: ") + '<span class="num">' + esc(b.checked_at || "—") + "</span>" +
      t(" · الإيميل بيظهر على الماك ده بس، ومابيتبعتش لأي حتة.", " · The email is shown on this Mac only and is never sent anywhere.") + "</div></div></div>";
    if (b.state === "ok" && b.subscription === false) {
      h += '<div class="banner warn pv-note">' + ic("alert") + '<div class="grow small">' + t("الحساب ده بيدفع بالـAPI (Console)، مش اشتراك Claude: كل قرار للعقل هيتكلّف فلوس. سجّل خروج وادخل باشتراكك.",
        "This account is billed through the API (Console), not a Claude subscription: every brain decision will cost money. Sign out and sign in with your subscription.") + "</div></div>";
    }
    if (b.state === "missing") {
      h += '<div class="banner warn pv-note">' + ic("alert") + '<div class="grow small">' + t("Claude Code مش متثبت، فالحلقات هتقف في أول خطوة. زرار التثبيت من اللوحة جاي بعدين؛ لحد دلوقتي ثبّته من الـTerminal بالمثبّت الرسمي:",
        "Claude Code is not installed, so episodes stop at their first step. Installing from the panel comes later; for now install it in Terminal with the official installer:") +
        '<pre dir="ltr" style="margin-top:8px">curl -fsSL https://claude.ai/install.sh | bash</pre></div></div>';
    } else if (b.state === "signed_out") {
      h += '<div class="banner warn pv-note">' + ic("alert") + '<div class="grow small">' + t("Claude Code مش مسجّل دخول، فالحلقات هتقف في أول خطوة. تسجيل الدخول من اللوحة جاي بعدين؛ لحد دلوقتي اكتب في الـTerminal (بحسابك إنت):",
        "Claude Code is not signed in, so episodes stop at their first step. Signing in from the panel comes later; for now type in Terminal (with your own account):") +
        '<pre dir="ltr" style="margin-top:8px">claude auth login</pre></div></div>';
    }
    h += '<div class="card"><h2 class="h3">' + t("شخصين على نفس الماك", "Two people on one Mac") + "</h2>" +
      t("تسجيل دخول Claude بيتحفظ لمستخدم الماك (في الـKeychain بتاعه). عشان كل واحد يشتغل باشتراكه، كل شخص يدخل الماك بمستخدم macOS خاص بيه (إعدادات النظام ← المستخدمين والمجموعات)، ويسجّل دخول Claude هناك. ماتسجّلش خروج حد عشان تدخل بحسابك.",
        "The Claude sign-in is kept for the Mac user (in that user's Keychain). For each person to work on their own subscription, each person uses their own macOS user (System Settings → Users & Groups) and signs in to Claude there. Don't sign someone else out to use your account.",
        "p", "small ink2") + "</div>";
    if (b.state === "ok") {
      var want = b.email || "SIGN OUT", match = so.text.trim().toLowerCase() === want.toLowerCase();
      h += '<div class="card" style="border-color:var(--danger)"><h2 class="h3">' + t("تسجيل الخروج من Claude Code", "Sign out of Claude Code") + "</h2>";
      if (!so.open) {
        h += t("بيسجّل خروج مستخدم الماك ده من Claude Code في كل حتة، مش في اللوحة بس.", "Signs this Mac user out of Claude Code everywhere, not only in the panel.", "p", "small ink2") +
          '<button class="btn btn-secondary btn-sm" style="margin-top:8px" data-so-open>' + t("تسجيل خروج…", "Sign out…") + "</button>";
      } else {
        h += '<div class="banner err pv-note" style="margin-top:8px">' + ic("alert") + '<div class="grow small">' +
          t("إنت على مستخدم الماك «" + who + "». ", "You are on the macOS user «" + who + "». ", "b") +
          t("تحذير: ده بيسجّل خروج مستخدم الماك ده من Claude Code في كل حتة: عقل مونتير، وكمان أي جلسة Claude Code بيستخدمها في الـTerminal أو المحرر. الحلقات هتقف في أول خطوة لحد ما حد يسجّل دخول تاني. مفيش تراجع غير إنك تسجّل دخول من جديد.",
            "Warning: this signs this Mac user out of Claude Code EVERYWHERE: Monteer's brain, and any Claude Code session they use in Terminal or an editor. Episodes stop at their first step until someone signs in again. The only way back is to sign in again.", "b") +
          "<div style=\"margin-top:8px\">" + (b.email ? t("للتأكيد اكتب الإيميل اللي مسجّل دخول: ", "To confirm, type the signed-in email: ") + '<b dir="ltr">' + esc(b.email) + "</b>"
            : t("للتأكيد اكتب: ", "To confirm, type: ") + '<b dir="ltr">SIGN OUT</b>') + "</div>" +
          '<input class="input" id="so-text" dir="ltr" autocomplete="off" spellcheck="false" style="margin-top:8px;width:100%;max-width:420px;height:38px" value="' + esc(so.text) + '">' +
          '<div class="row" style="gap:8px;margin-top:12px"><button class="btn btn-primary btn-sm" id="so-go"' + (match && !so.busy ? "" : " disabled") + ">" +
          t(so.busy ? "بسجّل خروج…" : "سجّل خروج من Claude Code", so.busy ? "Signing out…" : "Sign out of Claude Code") + "</button>" +
          '<button class="btn btn-ghost btn-sm" data-so-cancel>' + t("إلغاء", "Cancel") + "</button></div></div></div>";
      }
      h += "</div>";
    }
    if (so.msg) {
      h += '<div class="banner ' + (so.msg.err ? "err" : "info") + ' pv-note">' + ic(so.msg.err ? "alert" : "check") + '<div class="grow small">' + t(so.msg.ar, so.msg.en) + "</div></div>";
    }
    var k = (S.state && S.state.keys) || {}, known = (S.state && S.state.known_keys) || {};
    h += '<div class="card"><h2 class="h3">' + t("النموذج المحلي والمفاتيح", "Local model and keys") + "</h2>" +
      '<div class="small" style="margin-top:8px">' + t("النموذج المحلي: ", "Local model: ") + (S.state && S.state.local_model ? t("موجود", "present", "b", "okc") : t("مش موجود", "missing", "b", "warnc")) + "</div>" +
      Object.keys(known).map(function (n) { var on = !!k[n];
        return '<div class="row wrap" style="gap:8px;padding:8px 0;border-bottom:1px solid var(--line);align-items:center"><b class="small" style="min-width:90px">' + esc(known[n][0]) + "</b>" +
          '<span class="chip ' + (on ? "ok" : "line") + '">' + (on ? t("موجود", "present") : t("مش موجود", "missing")) + "</span>" +
          '<span class="micro ink2 grow" dir="ltr">' + esc(known[n][1]) + "</span>" +
          '<input class="input" type="password" autocomplete="off" id="key-' + esc(n) + '" style="height:32px;width:220px" dir="ltr" placeholder="' + esc(on ? (en() ? "replace the key" : "غيّر المفتاح") : (en() ? "paste the key" : "حط المفتاح")) + '">' +
          '<button class="btn btn-secondary btn-sm" data-key="' + esc(n) + '">' + t("احفظ", "Save") + "</button>" +
          (on ? '<button class="btn btn-ghost btn-sm" data-keyrm="' + esc(n) + '">' + t("امسح", "Remove") + "</button>" : "") + "</div>"; }).join("") +
      t("المفتاح بيتحفظ في ملف المفاتيح بتاعك على الماك ده بس (~/.config/monteer/keys.json، ليك إنت بس)، وقيمته مابتظهرش تاني ولا بتطلع من الماك.",
        "A key is kept in your own keys file on this Mac only (~/.config/monteer/keys.json, readable by you alone); its value is never shown again and never leaves the Mac.", "p", "small mutedc") +
      (S.keyMsg ? '<div class="banner ' + (S.keyMsg.err ? "err" : "info") + ' pv-note"><div class="small">' + t(S.keyMsg.ar, S.keyMsg.en) + "</div></div>" : "") + "</div>";
    return h + "</div>";
  }
  /* the approval card's clicks and words (phase 3) */
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-ans],[data-send]") : null;
    if (!el || el.disabled || !S.detail || !S.detail.approval) return;
    var e = S.detail, a = ansOf(e);
    if (el.hasAttribute("data-ans")) {
      var n = +el.getAttribute("data-ans");
      a[n] = { choice: el.getAttribute("data-key"), text: (a[n] || {}).text || "" };
      render();
      if (a[n].choice === "other") { var i = document.querySelector('[data-anstext="' + n + '"]'); if (i) i.focus(); }
      return;
    }
    var mode = el.getAttribute("data-send");
    S.ansBusy = true; render();
    post("/api/answers", { id: e.id, mode: mode, answers: mode === "answers" ? a : {} }).then(function (d) {
      S.ansBusy = false;
      if (d.error) S.actMsg = { ar: "ماتبعتتش: " + d.error, en: "Not sent: " + d.error, err: true };
      else { delete S.ans[e.id]; S.actMsg = { ar: "الإجابات وصلت والشغل كمّل.", en: "The answers are in and the run goes on." }; }
      refresh();
    }).catch(function () { S.ansBusy = false; S.actMsg = { ar: "اللوحة مارَدّتش", en: "The panel did not answer", err: true }; render(); });
  });
  document.addEventListener("input", function (ev) {
    var n = ev.target.getAttribute && ev.target.getAttribute("data-anstext");
    if (!n || !S.detail || !S.detail.approval) return;
    var a = ansOf(S.detail);
    a[n] = { choice: "other", text: ev.target.value };
    var b = document.querySelector('[data-send="answers"]');
    if (b) b.disabled = S.ansBusy || S.detail.approval.questions.some(function (q) { var c = a[q.n] || {}; return !c.choice || (c.choice === "other" && !(c.text || "").trim()); });
  });
  function typing() {                          /* never redraw under a field you are typing in */
    var x = document.activeElement;
    return !!(x && (x.id === "so-text" || x.id === "ed-text" || /^sw-|^st-|^rb-|^key-|^tr-|^ch-|^del-/.test(x.id || "") || (x.getAttribute && (x.getAttribute("data-anstext") || x.getAttribute("data-sline")))));
  }
  /* live progress (web panel plan 2.3): one stream for the episode on screen; the 5 s refresh stays for the list */
  function live() {
    var want = S.route === "progress" && S.sel && S.sel.indexOf("p:") === 0 ? S.sel : null;
    if (S.es && S.esId === want) return;
    if (S.es) { S.es.close(); S.es = null; S.esId = null; }
    if (!want || !window.EventSource) return;
    S.esId = want;
    S.es = new EventSource("/api/events?id=" + encodeURIComponent(want));
    S.es.onmessage = function (m) {
      var x;
      try { x = JSON.parse(m.data); } catch (err) { return; }
      if (S.sel !== x.id || S.route !== "progress") return;
      S.detail = x;
      S.episodes.forEach(function (ep) { if (ep.id === x.id) { ep.state = x.state; ep.state_label = x.state_label; } });
      if (!typing()) render();
    };
  }
  /* ---------------------------------------------------------------- phase 4: the Result screen */
  var MIXC = { stock: "#5B8DEF", archive: "#C9A24B", news: "#D9534F", ai: "#B07CE0", map: "#3FAF7A", numbers: "#E08A3C", graphic: "#8C8C8C",
               own: "#4FC1C9", card: "#6B6B6B", presenter: "#3A3F47" };
  var MIXN = { presenter: ["المذيع", "Presenter"] };
  var SECT = { "The channel profile": "ملف القناة", "Placeholder values (the channel has not given these yet)": "قيم مؤقتة (القناة لسه مادتهاش)",
               "What «عام» learned and applied": "اللي «عام» اتعلمه وطبّقه", "The narration (audio only)": "صوت المذيع (صوت بس)" };
  function tc(s) { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }
  function resultTarget() {
    if (S.rsel) return S.rsel;
    var done = (S.episodes || []).filter(function (e) { return e.state === "done" || e.state === "approved"; })
      .sort(function (a, b) { return (b.scope === "projects") - (a.scope === "projects") || String(b.updated || "").localeCompare(String(a.updated || "")); });
    /* no episode named in the link: the one open on the progress page when it is one of yours, else your latest
       finished episode; a test project only when it is opened on purpose (#/result/<id>) */
    return S.sel && done.some(function (e) { return e.id === S.sel && e.scope === "projects"; }) ? S.sel
      : (done.filter(function (e) { return e.scope === "projects"; })[0] || {}).id || null;
  }
  function resultLoad(force) {
    var id = resultTarget();
    if (!id) { if (S.res !== null) { S.res = null; S.resId = null; render(); } return; }
    if (!force && S.resId === id && S.res) return;
    S.resId = id; S.resVideo = null;
    api("/api/result?id=" + encodeURIComponent(id)).then(function (x) { if (S.resId === id) { S.res = x; render(); } });
  }
  /* phase 5: edit until satisfied */
  function edState(id) {
    if (!S.ed || S.ed.id !== id) S.ed = { id: id, reqs: [], text: "" };
    return S.ed;
  }
  function altButtons(d, ro) {
    if (ro) return "";
    S.alts = S.alts || [];
    var bs = [];
    if (d.kind === "picture" && d.other_n) {
      d.other_n.forEach(function (n, i) {
        S.alts.push({ alt: { kind: "pick", ref: d.ref, shot: d.shot, n: n }, t: d.t, label: (en() ? "Picture of " : "صورة ") + d.what + ": " + (d.others[i] || "#" + n) });
        bs.push('<button class="btn btn-ghost btn-sm" data-alt="' + (S.alts.length - 1) + '" dir="auto">' + t("غيّرها: ", "Change it: ") + esc((d.others[i] || "#" + n).slice(0, 40)) + "</button>");
      });
    } else if (d.others && d.others.length && d.kind !== "ai_image") {
      d.others.forEach(function (o) {
        S.alts.push({ alt: { kind: "choice", ref: d.ref || "montage/plan", what: d.what, chosen: d.chosen, use: o, at_s: d.t }, t: d.t, label: d.what + " → " + o });
        bs.push('<button class="btn btn-ghost btn-sm" data-alt="' + (S.alts.length - 1) + '" dir="auto">' + t("غيّرها: ", "Change it: ") + esc(o.slice(0, 40)) + "</button>");
      });
    } else {
      S.alts.push({ prefill: (en() ? "The drawn image «" : "الصورة المرسومة «") + d.what + "»: " });
      bs.push('<button class="btn btn-ghost btn-sm" data-alt="' + (S.alts.length - 1) + '">' + t("غيّرها (اكتب اللي عايزه)", "Change it (say what you want)") + "</button>");
    }
    return '<div class="row wrap" style="gap:6px;margin-top:6px">' + bs.join("") + "</div>";
  }
  function editCard(r, id, ro) {
    var ed = edState(id), rounds = r.edits || [], cur = rounds.filter(function (x) { return ["preparing", "prepared", "failed"].indexOf(x.status) >= 0; })[0];
    var h = '<div class="card" id="ed-card"><div class="card-h"><h2 class="h3">' + t("عايز تعدّل حاجة؟", "Want to change something?") + "</h2>" +
      '<span class="small ink2">' + t("النسخة الحالية " + r.version_now, "Current version " + r.version_now) + "</span></div>";
    if (ro) return h + t("حلقات الاختبار للقراءة بس.", "Test episodes are read-only.", "p", "small ink2") + "</div>";
    if (r.running) return h + '<div class="banner info pv-note">' + ic("loader") + '<div class="small">' + t("فيه شغل شغّال على الحلقة دي (نسخة جديدة بتتعمل). تابعها من «المتابعة».", "A run of this episode is going (a new version is being made). Follow it in Progress.") + "</div></div></div>";
    var label = function (x) {
      var a = x.alt || {}, txt = x.text || x.label || (a.kind === "pick" ? (en() ? "«Change it»: shot " + a.shot + " → candidate " + a.n : "«غيّرها»: صورة اللقطة " + a.shot + " ← البديل رقم " + a.n)
        : a.kind === "choice" ? "«" + (a.what || "") + "» → «" + (a.use || "") + "»" : "");
      return (x.t != null ? '<button class="chip gold num" data-jump="' + x.t + '">' + tc(x.t) + "</button> " : "") + '<span class="small" dir="auto">' + esc(txt) + "</span>"; };
    if (cur && cur.status === "preparing") {
      return h + '<div class="banner info pv-note">' + ic("loader") + '<div class="grow small">' + t("الوكيل بيحدد هيغيّر إيه وبيرد على كل طلب — بياخد دقايق. تقدر تقفل الصفحة.", "The agent is working out what to change and replying to each request — it takes minutes. You can close the page.") +
        "</div></div>" + cur.requests.map(function (x) { return '<div class="row" style="gap:8px;padding:4px 0">' + label(x) + "</div>"; }).join("") +
        '<button class="btn btn-ghost btn-sm" data-ed-cancel="' + cur.n + '">' + t("إلغي", "Cancel") + "</button></div>";
    }
    if (cur && cur.status === "failed") {
      return h + '<div class="banner err pv-note">' + ic("alert") + '<div class="grow small">' + t("ماقدرتش أجهّز التعديلات: ", "Could not prepare the edits: ") + '<span dir="ltr">' + esc(cur.why || "") + "</span></div></div>" +
        '<div class="row" style="gap:8px"><button class="btn btn-secondary btn-sm" data-ed-retry="' + cur.n + '">' + t("جرّب تاني", "Try again") + '</button><button class="btn btn-ghost btn-sm" data-ed-cancel="' + cur.n + '">' + t("إلغي", "Cancel") + "</button></div></div>";
    }
    if (cur && cur.status === "prepared") {
      var rd = cur.redo || {}, mins = rd.minutes || [0, 0], byN = {};
      (cur.replies || []).forEach(function (x) { byN[x.n] = x.reply; });
      h += t("ده اللي الوكيل هيعمله — لسه ماتغيّرش حاجة:", "This is what the agent will do — nothing has changed yet:", "p", "small ink2");
      h += cur.requests.map(function (x) { return '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="row wrap" style="gap:8px">' + label(x) + "</div>" +
        '<div class="small goldc" dir="auto" style="margin-top:4px">' + ic("chat", "sm") + " " + esc(byN[x.n] || "") + "</div></div>"; }).join("");
      if ((cur.changes || []).length) h += '<div class="small" style="margin-top:10px"><b>' + t("القرارات اللي هتتعمل تاني:", "Decisions to be made again:") + "</b>" + cur.changes.map(function (c) {
        return '<div class="small ink2" dir="auto" style="margin-top:4px"><span class="chip line micro" dir="ltr">' + esc(c.request) + "</span> " + esc(c.instruction) + "</div>"; }).join("") + "</div>";
      h += '<div class="banner gold pv-note">' + ic("clock") + '<div class="grow small">' +
        (rd.steps && rd.steps.length ? t("هيتعمل تاني من خطوة «" + ((cur.redo_groups || [])[0] || {}).ar + "»: ", "Redone from step «" + ((cur.redo_groups || [])[0] || {}).en + "»: ") +
          (cur.redo_groups || []).map(function (g) { return t(g.ar, g.en); }).join(" · ") + t(" — حوالي " + mins[0] + "–" + mins[1] + " دقيقة.", " — about " + mins[0] + "–" + mins[1] + " min.")
          : t("مفيش حاجة هتتغيّر.", "Nothing will change.")) +
        t(" اللقطات اللي ماتغيّرتش مابتترندرش تاني، والقرارات اللي ماتأثرتش بتفضل زي ما هي. النسخة الحالية بتتحفظ.",
          " Shots that did not change are not rendered again, and decisions the edit does not touch stay as they are. The current version is kept.") + "</div></div>" +
        '<div class="row" style="gap:8px"><button class="btn btn-primary btn-sm" data-ed-apply="' + cur.n + '"' + (rd.steps && rd.steps.length ? "" : " disabled") + ">" + t("نفّذ التعديلات (نسخة " + (r.version_now + 1) + ")", "Apply the edits (version " + (r.version_now + 1) + ")") + "</button>" +
        '<button class="btn btn-ghost btn-sm" data-ed-cancel="' + cur.n + '">' + t("إلغي", "Cancel") + "</button></div></div>";
      return h;
    }
    h += t("اكتب اللي مش عاجبك وهو بيتربط بتوقيت المشغّل دلوقتي، أو اختار بديل من «قرارات اتاخدت لوحدها». ابعت كله مرة واحدة.",
      "Write what you don't like; it is pinned to the player's current time — or choose an alternative under «Decisions taken alone». Send them all at once.", "p", "small ink2");
    h += ed.reqs.map(function (x, i) { return '<div class="row" style="gap:8px;padding:6px 0;border-bottom:1px solid var(--line)">' + label(x) +
      '<button class="btn btn-ghost btn-sm" data-ed-rm="' + i + '" style="margin-inline-start:auto">' + ic("x", "sm") + "</button></div>"; }).join("");
    h += '<div class="row" style="gap:8px;margin-top:10px"><input class="input grow" id="ed-text" dir="auto" maxlength="2000" style="height:38px" value="' + esc(ed.text) +
      '" placeholder="' + esc(en() ? "e.g. this picture doesn't fit what is said; use a factory instead" : "مثلاً: الصورة دي مش مناسبة للكلام، حط مصنع بدلها") + '">' +
      '<button class="btn btn-secondary btn-sm" data-ed-add>' + ic("plus", "sm") + t("ابعت عند التوقيت ده", "Add at this time") + "</button></div>";
    h += '<div class="row" style="gap:8px;margin-top:12px"><button class="btn btn-primary btn-sm" data-ed-send' + (ed.reqs.length ? "" : " disabled") + ">" +
      t("جهّز التعديلات (" + ed.reqs.length + ")", "Prepare the edits (" + ed.reqs.length + ")") + "</button>" +
      t("هيقولك قبل ما يبدأ: هيعمل إيه، ومن أنهي خطوة، وهياخد قد إيه.", "Before starting it tells you what it will do, from which step, and roughly how long.", "span", "micro ink2") + "</div>";
    var done = rounds.filter(function (x) { return x.status === "applied"; });
    if (done.length) h += '<details class="pv-note"><summary class="small ink2">' + t("التعديلات اللي اتعملت (" + done.length + ")", "Edits made (" + done.length + ")") + "</summary>" +
      done.map(function (x) { var byN = {}; (x.replies || []).forEach(function (y) { byN[y.n] = y.reply; });
        return '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><b class="small">' + t("نسخة " + x.version_from + " ← " + x.version_to, "v" + x.version_from + " → v" + x.version_to) + "</b>" +
          x.requests.map(function (y) { return '<div class="small" dir="auto">' + esc(y.text || (y.alt ? (y.alt.use || ("#" + y.alt.n)) : "")) + ' <span class="goldc">— ' + esc(byN[y.n] || "") + "</span></div>"; }).join("") + "</div>"; }).join("") + "</details>";
    return h + "</div>";
  }
  function compareCard(r, q) {
    if (!r.videos || r.videos.length < 2) return "";
    var c = S.cmp && S.cmp.id === S.resId ? S.cmp : (S.cmp = { id: S.resId, a: r.videos[r.videos.length - 2].name, b: r.videos[r.videos.length - 1].name, open: false });
    if (!c.open) return '<div class="row"><button class="btn btn-secondary btn-sm" data-cmp-open>' + t("قارن نسختين جنب بعض", "Compare two versions side by side") + "</button></div>";
    var pick = function (side) { return r.videos.map(function (v) { return '<button class="chip ' + (c[side] === v.name ? "gold" : "line") + '" data-cmp="' + side + ":" + esc(v.name) + '">' + t("نسخة " + v.version, "v" + v.version) + "</button>"; }).join(""); };
    var col = function (side) { return '<div class="col" style="gap:6px"><div class="row wrap" style="gap:6px">' + pick(side) + '</div><video id="cmp-' + side + '" controls preload="metadata" style="width:100%;border-radius:8px;background:#000" src="/api/media?' + q + encodeURIComponent(c[side]) + '"></video></div>'; };
    return '<div class="card"><div class="card-h"><h2 class="h3">' + t("مقارنة النسخ", "Compare versions") + '</h2><button class="btn btn-ghost btn-sm" data-cmp-close>' + ic("x", "sm") + "</button></div>" +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' + col("a") + col("b") + "</div>" +
      '<button class="btn btn-secondary btn-sm pv-note" data-cmp-sync>' + ic("play", "sm flip") + t("شغّل الاتنين من نفس التوقيت", "Play both from the same time") + "</button></div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-alt],[data-ed-add],[data-ed-rm],[data-ed-send],[data-ed-apply],[data-ed-cancel],[data-ed-retry],[data-cmp],[data-cmp-open],[data-cmp-close],[data-cmp-sync]") : null;
    if (!el || el.disabled || S.route !== "result") return;
    var id = S.resId, ed = edState(id), pl = document.getElementById("rs-player");
    if (el.hasAttribute("data-alt")) {
      var a = S.alts[+el.getAttribute("data-alt")];
      if (a.prefill) { ed.text = a.prefill; render(); var i = document.getElementById("ed-text"); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } return; }
      ed.reqs.push({ text: "", label: a.label, alt: a.alt, t: a.t });
      render(); var c = document.getElementById("ed-card"); if (c) c.scrollIntoView({ block: "nearest" });
    } else if (el.hasAttribute("data-ed-add")) {
      var tx = (document.getElementById("ed-text") || {}).value || "";
      if (!tx.trim()) return;
      ed.reqs.push({ text: tx.trim(), t: pl ? Math.round(pl.currentTime * 10) / 10 : null }); ed.text = ""; render();
    } else if (el.hasAttribute("data-ed-rm")) { ed.reqs.splice(+el.getAttribute("data-ed-rm"), 1); render(); }
    else if (el.hasAttribute("data-ed-send")) {
      el.disabled = true;
      post("/api/edits", { id: id, action: "new", requests: ed.reqs.map(function (x) { return { text: x.text, t: x.t, alt: x.alt || null }; }) }).then(function (d) {
        if (d.error) S.resMsg = { ar: "ماتبعتتش: " + d.error, en: "Not sent: " + d.error, err: true }; else ed.reqs = [];
        resultLoad(true);
      });
    } else if (el.hasAttribute("data-ed-apply") || el.hasAttribute("data-ed-cancel") || el.hasAttribute("data-ed-retry")) {
      var act = el.hasAttribute("data-ed-apply") ? "apply" : el.hasAttribute("data-ed-cancel") ? "cancel" : "retry";
      el.disabled = true;
      post("/api/edits", { id: id, action: act, n: +el.getAttribute("data-ed-" + act) }).then(function (d) {
        S.resMsg = d.error ? { ar: "ماتنفذش: " + d.error, en: "Not done: " + d.error, err: true }
          : act === "apply" ? { ar: "التعديلات بتتعمل في نسخة " + d.version + ". تابعها من «المتابعة».", en: "The edits are being made in version " + d.version + ". Follow them in Progress." } : null;
        resultLoad(true); refresh();
      });
    } else if (el.hasAttribute("data-cmp-open")) { S.cmp.open = true; render(); }
    else if (el.hasAttribute("data-cmp-close")) { S.cmp.open = false; render(); }
    else if (el.hasAttribute("data-cmp")) { var v = el.getAttribute("data-cmp").split(":"); S.cmp[v[0]] = v.slice(1).join(":"); render(); }
    else if (el.hasAttribute("data-cmp-sync")) {
      var A = document.getElementById("cmp-a"), B = document.getElementById("cmp-b");
      if (A && B) { B.currentTime = A.currentTime; A.play().catch(function () {}); B.play().catch(function () {}); }
    }
  });
  document.addEventListener("input", function (ev) { if (ev.target.id === "ed-text" && S.ed) S.ed.text = ev.target.value; });
  function resultPoll() {                       /* a preparing round or a run going: redraw only when its state changes */
    var id = S.resId;
    if (!id || !S.res || !S.res.ready) return;
    var active = S.res.running || (S.res.edits || []).some(function (x) { return x.status === "preparing"; });
    if (!active) return;
    api("/api/result?id=" + encodeURIComponent(id)).then(function (x) {
      if (S.resId !== id) return;
      var was = JSON.stringify([S.res.edits, S.res.running, S.res.video]), now = JSON.stringify([x.edits, x.running, x.video]);
      S.res = x;
      if (was !== now && !typing()) render();
    });
  }
  function resultView() {
    var id = resultTarget(), e = (S.episodes || []).filter(function (x) { return x.id === id; })[0];
    if (!id || !e) return '<div class="card"><div class="empty"><div class="ico">' + ic("play", "xl") + "</div>" + t("لسه مفيش فيديو خلصان", "No finished video yet", "h2", "h2") +
      t("أول ما حلقة تخلص، نتيجتها بتظهر هنا.", "As soon as an episode finishes, its result shows here.", "p", "ink2 small") + "</div></div>";
    var r = S.res;
    S.alts = [];
    if (!r || S.resId !== id) { resultLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل النتيجة…", "Loading the result…") + "</p></div>"; }
    if (!r.ready) return '<div class="card"><h1 class="h2">' + esc(e.name) + "</h1>" + t("الحلقة دي لسه مالهاش فيديو خلصان.", "This episode has no finished video yet.", "p", "ink2 small") + "</div>";
    var vid = S.resVideo || r.video, q = "id=" + encodeURIComponent(id) + "&name=", ro = e.scope !== "projects";
    var others = (S.episodes || []).filter(function (x) { return (x.state === "done" || x.state === "approved") && (x.scope === "projects" || x.id === id); });
    var h = '<div class="col" style="gap:24px">';
    /* header: title, versions, report, download, final approval */
    var ap = r.approved, arm = S.apArm === id;
    h += '<div class="card em lg"><div class="row between top wrap" style="gap:12px"><div><div class="row wrap" style="gap:8px;margin-bottom:8px">' +
      '<span class="chip">' + (e.type === "voice_only" ? t("صوت بس", "Audio only") : t("بمذيع", "With presenter")) + "</span>" +
      (ap ? '<span class="chip ok">' + ic("check", "sm") + t("موافقة نهائية: نسخة " + ap.version, "Final approval: version " + ap.version) + "</span>" : "") +
      (ro ? '<span class="chip line">' + t("اختبار · للقراءة بس", "Test · read-only") + "</span>" : "") + "</div>" +
      '<h1 class="h1">' + esc(e.name) + "</h1>" +
      (others.length > 1 ? '<div class="row wrap" style="gap:6px;margin-top:8px">' + others.slice(0, 8).map(function (x) {
        return '<a class="chip ' + (x.id === id ? "gold" : "line") + '" href="#/result/' + encodeURIComponent(x.id) + '">' + esc(x.name) + "</a>"; }).join("") + "</div>" : "") +
      "</div><div class=\"row wrap\" style=\"gap:8px\">" +
      (r.report ? '<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" href="/api/file?' + q + encodeURIComponent(r.report) + '">' + ic("doc", "sm") + t("التقرير", "Report") + "</a>" : "") +
      (r.credits ? '<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" href="/api/file?' + q + "credits.md" + '">' + t("المصادر والرخص", "Credits") + "</a>" : "") +
      '<a class="btn btn-secondary btn-sm" href="/api/file?' + q + encodeURIComponent(vid) + '&dl=1">' + ic("download", "sm") + t("تحميل MP4", "Download MP4") + "</a>" +
      (ro ? "" : ap && ap.video === vid ?          /* this version is approved: a done state, not a red call to action */
        '<span class="btn btn-sm btn-done" role="status">' + ic("check", "sm") + t("اتوافق عليها", "Approved") + "</span>" :
        '<button class="btn btn-primary btn-sm" data-approve="' + esc(vid) + '">' + ic("check", "sm") +
        t(arm ? "اضغط تاني للتأكيد" : "موافقة نهائية", arm ? "Click again to confirm" : "Final approval") + "</button>") +
      "</div></div>" +
      (r.videos.length > 1 ? '<div class="row wrap" style="gap:6px;margin-top:12px">' + t("النسخ: ", "Versions: ", "span", "small ink2") + r.videos.map(function (v) {
        return '<button class="chip ' + (v.name === vid ? "gold" : "line") + '" data-ver="' + esc(v.name) + '">' + t("نسخة " + v.version, "v" + v.version) + "</button>"; }).join("") +
        (vid !== r.video ? t(" — الأرقام والعلامات تحت للنسخة الأخيرة بس.", " — the figures and marks below are for the latest version only.", "span", "micro warnc") : "") + "</div>" : "") +
      (S.resMsg ? '<div class="banner ' + (S.resMsg.err ? "err" : "info") + ' pv-note">' + ic("alert") + "<div>" + t(S.resMsg.ar, S.resMsg.en) + "</div></div>" : "") + "</div>";
    /* the player, its watch-first ticks */
    var dur0 = r.duration_s || 1;
    var ticks = r.watch.filter(function (w) { return w.t != null; }).map(function (w) {
      return '<button class="rs-tick" data-jump="' + w.t + '" title="' + esc(tc(w.t) + " · " + (en() ? w.en : w.ar)) + '" style="position:absolute;inset-inline-start:' +
        (100 * w.t / dur0).toFixed(2) + '%;top:0;width:3px;height:14px;padding:0;border:0;background:var(--warning);cursor:pointer"></button>'; }).join("");
    h += '<div class="card" style="padding:12px"><video id="rs-player" controls preload="metadata" style="width:100%;border-radius:10px;background:#000" src="/api/media?' + q + encodeURIComponent(vid) + '"></video>' +
      '<div dir="ltr" style="position:relative;height:14px;margin-top:8px;background:var(--line);border-radius:3px">' + ticks + "</div>" +
      t("العلامات البرتقالي: «اتفرّج على دول الأول» — اضغط عليها تروح للتوقيت.", "Orange marks: «watch these first» — click one to jump there.", "p", "micro ink2 pv-note") + "</div>";
    h += editCard(r, id, ro) + compareCard(r, q);
    /* stat tiles */
    var st = r.stats;
    var tile = function (v, ar, eng) { return '<div class="card" style="padding:14px"><div class="h2 num">' + v + "</div>" + t(ar, eng, "div", "small ink2") + "</div>"; };
    h += '<div class="grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px">' +
      tile(tc(st.length_s), "المدة", "Length") + tile(st.shots, "لقطة", "Shots") + tile(st.pictures + ' <span class="small ink2">(' + st.moving + " " + (en() ? "moving" : "متحركة") + ")</span>", "صورة", "Pictures") +
      tile(st.music_cues == null ? "—" : st.music_cues, "مقطع مزيكا", "Music cues") + tile(st.sfx == null ? "—" : st.sfx, "مؤثر صوتي", "Sound effects") +
      tile(st.words_lost == null ? "—" : st.words_lost, "كلمات سكريبت ضاعت", "Script words lost") + "</div>";
    /* the material mix */
    var mx = r.mix, seg = mx.share.map(function (s) { return '<i title="' + esc((en() ? s.en : s.ar) + " " + Math.round(s.share * 100) + "%") + '" style="display:block;height:100%;width:' + (s.share * 100).toFixed(2) + "%;background:" + (MIXC[s.type] || "#888") + '"></i>'; }).join("");
    var strip = mx.strip.map(function (s) { return '<i data-jump="' + s.t0 + '" title="' + esc(tc(s.t0) + " · " + s.type) + '" style="display:block;cursor:pointer;height:100%;width:' + (100 * (s.t1 - s.t0) / dur0).toFixed(3) + "%;background:" + (MIXC[s.type] || "#888") + '"></i>'; }).join("");
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("مزيج الماتيريال", "Material mix") + "</h2>" +
      (mx.presenter_share ? '<span class="small ink2">' + t("المذيع " + Math.round(mx.presenter_share * 100) + "% من الوقت", "Presenter " + Math.round(mx.presenter_share * 100) + "% of the time") + "</span>" : "") + "</div>" +
      '<div dir="ltr" style="display:flex;height:14px;border-radius:7px;overflow:hidden">' + seg + "</div>" +
      '<div class="row wrap" style="gap:12px;margin-top:10px">' + mx.share.map(function (s) {
        return '<span class="small"><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:' + (MIXC[s.type] || "#888") + '"></i> ' + t(s.ar, s.en) + ' <b class="num">' + Math.round(s.share * 100) + "%</b></span>"; }).join("") + "</div>" +
      t("من غير وقت المذيع. شريط اللقطات تحت بالترتيب (اضغط على لقطة تروح لها):", "Without the presenter's time. The shot strip below, in order (click a shot to jump to it):", "p", "micro ink2 pv-note") +
      '<div dir="ltr" style="display:flex;height:22px;border-radius:4px;overflow:hidden;gap:1px">' + strip + "</div></div>";
    /* watch these first */
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("اتفرّج على دول الأول", "Watch these first") + '</h2><span class="small ink2 num">' + r.watch.length + "</span></div>" +
      (r.watch.length ? r.watch.map(function (w) {
        return '<div class="row" style="gap:10px;padding:6px 0;border-bottom:1px solid var(--line)">' +
          (w.t != null ? '<button class="chip gold num" data-jump="' + w.t + '">' + tc(w.t) + "</button>" : '<span class="chip line">—</span>') +
          '<span class="chip ' + (w.kind === "listen" ? "info" : "line") + '">' + ic(w.kind === "listen" ? "ear" : "eye", "sm") + t(w.kind === "listen" ? "اسمع" : "بُص", w.kind === "listen" ? "Listen" : "Look") + "</span>" +
          '<span class="small" dir="auto">' + esc(en() ? w.en : w.ar) + "</span></div>"; }).join("")
        : t("مفيش حاجة محتاجة نظرة: كل المراجعات نجحت.", "Nothing needs a look: every check passed.", "p", "small ink2")) +
      (r.selfcheck_ran ? "" : t("المراجعة الذاتية مااشتغلتش على الفيديو ده.", "The self-check did not run on this video.", "p", "micro warnc pv-note")) + "</div>";
    /* decisions taken alone */
    var dec = r.decisions, showAll = S.decAll;
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("قرارات اتاخدت لوحدها", "Decisions taken alone") + '</h2><span class="small ink2 num">' + dec.length + "</span></div>" +
      (dec.length ? (showAll ? dec : dec.slice(0, 8)).map(function (d) {
        var K = { picture: ["صورة اللقطة", "The shot's picture"], ai_image: ["صورة مرسومة", "A drawn image"], question: ["سؤال على الخطة", "A question on the plan"] }[d.kind] || [d.kind, d.kind];
        return '<div style="padding:10px 0;border-bottom:1px solid var(--line)"><div class="row wrap" style="gap:8px">' +
          (d.t != null ? '<button class="chip gold num" data-jump="' + d.t + '">' + tc(d.t) + "</button>" : "") + '<span class="chip line">' + t(K[0], K[1]) + "</span>" +
          '<b class="small" dir="auto">' + esc(d.chosen) + "</b></div>" + (d.why ? '<div class="small ink2" dir="auto" style="margin-top:4px">' + esc(d.why) + "</div>" : "") +
          (d.others && d.others.length && (ro || d.kind === "ai_image") ? '<div class="row wrap" style="gap:6px;margin-top:6px">' + t("البدائل:", "Other options:", "span", "micro ink2") + d.others.map(function (o) { return '<span class="chip line micro" dir="auto">' + esc(o) + "</span>"; }).join("") + "</div>" : "") +
          altButtons(d, ro) + "</div>"; }).join("") +
        (dec.length > 8 && !showAll ? '<button class="btn btn-ghost btn-sm" data-decall style="margin-top:8px">' + t("اعرض الكل (" + dec.length + ")", "Show all (" + dec.length + ")") + "</button>" : "")
        : t("مفيش قرارات ليها بدائل متسجلة في الحلقة دي.", "No decisions with recorded alternatives in this episode.", "p", "small ink2")) + "</div>";
    /* publishing checklist */
    var ck = r.checklist, cl = ck.credit_lines;
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("قبل النشر", "Before publishing") + "</h2></div>" +
      '<div class="small" style="margin-top:4px"><b>' + t("سطور المصادر في الوصف", "Credit lines for the description") + "</b>" +
      (cl === null ? t(" — ملف المصادر مش موجود.", " — the credits file is missing.", "span", "warnc") : cl.length ?
        '<pre class="pv-log" dir="ltr" id="rs-credits" style="margin-top:6px;white-space:pre-wrap">' + esc(cl.join("\n")) + '</pre><button class="btn btn-ghost btn-sm" data-copycredits>' + ic("copy", "sm") + t("انسخ", "Copy") + "</button>"
        : t(" — مفيش سطور مطلوبة (كل المصادر من غير نسب).", " — none needed (every source is free of attribution).", "span", "ink2")) + "</div>" +
      '<div class="small" style="margin-top:12px"><b>' + t("خانة YouTube «محتوى معدّل أو اصطناعي»", "YouTube's «altered or synthetic content» box") + "</b>: " +
      (ck.altered_or_synthetic.tick ? t("علّم عليها", "tick it", "b", "warnc") + ' <span class="ink2">(' + esc(ck.altered_or_synthetic.why.join("، ")) + ")</span>" : t("مش لازم", "not needed", "b", "okc")) + "</div>" +
      '<div class="small" style="margin-top:12px"><b>' + t("شاشة النهاية", "End screen") + "</b>: " +
      (ck.end_screen.set ? t("ضيفها في YouTube Studio على آخر " + ck.end_screen.seconds + " ثانية (" + ck.end_screen.video_slots + " فيديو" + (ck.end_screen.subscribe ? " + زرار الاشتراك" : "") + ")؛ المونتاج مابيرسمهاش.",
        "add it in YouTube Studio over the last " + ck.end_screen.seconds + " s (" + ck.end_screen.video_slots + " videos" + (ck.end_screen.subscribe ? " + the subscribe button" : "") + "); the montage does not draw it.")
        : t("القناة مالهاش إعداد لشاشة النهاية.", "The channel has no end-screen setting.", "span", "ink2")) + "</div>" +
      '<div class="small" style="margin-top:12px"><b>' + t("الموافقة النهائية", "Final approval") + "</b>: " +
      (ap ? t("نسخة " + ap.version + " — " + esc(ap.by) + " — " + esc(ap.at), "version " + ap.version + " — " + esc(ap.by) + " — " + esc(ap.at)) : t("لسه", "not yet", "span", "warnc")) + "</div></div>";
    /* today's report sections */
    r.sections.forEach(function (s) {
      h += '<div class="card"><h2 class="h3">' + t(SECT[s.title] || s.title, s.title) + "</h2>" +
        s.lines.map(function (l) { return '<div class="small" dir="auto" style="padding:4px 0">' + esc(l.replace(/\*\*/g, "")) + "</div>"; }).join("") + "</div>";
    });
    return h + "</div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-jump],[data-ver],[data-approve],[data-decall],[data-copycredits]") : null;
    if (!el || S.route !== "result") return;
    var pl = document.getElementById("rs-player");
    if (el.hasAttribute("data-jump")) { if (pl) { pl.currentTime = +el.getAttribute("data-jump"); pl.play().catch(function () {}); pl.scrollIntoView({ block: "nearest" }); } }
    else if (el.hasAttribute("data-ver")) { S.resVideo = el.getAttribute("data-ver"); render(); }
    else if (el.hasAttribute("data-decall")) { S.decAll = true; render(); }
    else if (el.hasAttribute("data-copycredits")) { var c = document.getElementById("rs-credits"); if (c && navigator.clipboard) navigator.clipboard.writeText(c.textContent); }
    else if (el.hasAttribute("data-approve")) {
      var id = S.resId;
      if (S.apArm !== id) { S.apArm = id; render(); setTimeout(function () { if (S.apArm === id) { S.apArm = null; render(); } }, 5000); return; }
      S.apArm = null;
      post("/api/approve", { id: id, video: el.getAttribute("data-approve"), by: (S.state && S.state.user && S.state.user.name) || "" }).then(function (d) {
        S.resMsg = d.error ? { ar: "ماتسجلتش الموافقة: " + d.error, en: "Not approved: " + d.error, err: true }
          : { ar: "الموافقة النهائية اتسجلت (نسخة " + d.approved.version + ").", en: "Final approval recorded (version " + d.approved.version + ")." };
        resultLoad(true); refresh();
      });
    }
  });
  /* ---------------------------------------------------------------- phase 6: the script writer */
  var TYPE_AR = { archive: ["أرشيف", "Archive"], news: ["خبر موثّق", "News"], stock: ["تكميلي", "Stock"], story: ["قصة مرسومة", "Story"], map: ["خريطة", "Map"], numbers: ["أرقام", "Numbers"] };
  var STAGE_N = { topic: 1, research: 2, outline: 3, draft: 4, review: 5, approved: 6 };
  function scriptLoad(force) {
    var id = S.ssel;
    if (!id) { if (S.sv) { S.sv = null; render(); } return; }
    if (!force && S.svId === id && S.sv && !(S.sv.run && S.sv.run.running)) return;
    var first = S.svId !== id;
    S.svId = id;
    api("/api/script?id=" + encodeURIComponent(id)).then(function (x) {
      if (S.svId !== id) return;
      var was = JSON.stringify(S.sv || null);
      S.sv = x;
      if ((first || was !== JSON.stringify(x)) && !typing()) render();
    });
  }
  function scriptView() {
    if (!S.ssel) return scriptHome();
    var e = (S.episodes || []).filter(function (x) { return x.id === S.ssel; })[0], x = S.sv;
    if (!x || S.svId !== S.ssel) { scriptLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل السكريبت…", "Loading the script…") + "</p></div>"; }
    if (x.error) return '<div class="card"><p class="small errc">' + esc(x.error) + "</p></div>";
    var ro = !e || e.scope !== "projects", at = STAGE_N[x.stage] || 1, run = x.run, h = '<div class="col" style="gap:24px;max-width:980px">';
    var hs = SCRIPT_STAGES.map(function (s, i) { var n = i + 1, cls = n < at || x.stage === "approved" ? "done" : n === at ? "on" : (n === 3 ? "gate" : "");
      return '<div class="hstep ' + cls + '"><span class="n">' + (cls === "done" ? ic("check", "sm") : n) + "</span>" + t(s[0], s[1]) + "</div>"; }).join("");
    h += '<div class="card em lg"><div class="row wrap" style="gap:8px;margin-bottom:8px"><span class="chip">' + esc((x.channel || {}).profile || "") + '</span><span class="chip">' +
      (x.type === "voice_only" ? t("صوت بس", "Audio only") : t("بمذيع", "With presenter")) + "</span>" + (ro ? '<span class="chip line">' + t("اختبار · للقراءة بس", "Test · read-only") + "</span>" : "") + "</div>" +
      '<h1 class="h1" dir="auto">' + esc(x.topic.topic || (e && e.name) || "") + "</h1>" + (x.topic.angle ? '<p class="small ink2" dir="auto">' + esc(x.topic.angle) + "</p>" : "") +
      '<div class="small ink2">' + t("المدة المستهدفة: ", "Target length: ") + '<b class="num">' + (x.topic.minutes || (x.channel.default_minutes ? x.channel.default_minutes + t(" (متوسط القناة)", " (the channel's average)") : "—")) + "</b>" + t(" دقيقة", " min") +
      (x.topic.sources ? " · " + t("المصادر المختارة: " + x.topic.sources.length, "Sources picked: " + x.topic.sources.length) : "") + "</div>" +
      '<div class="hsteps" style="margin-top:14px">' + hs + "</div>";
    if (run.running) h += '<div class="banner info pv-note">' + ic("loader") + '<div class="grow small">' + t("شغّال: ", "Running: ") + "<b>" + esc(run.step || "") + '</b><div class="micro ink2" dir="auto">' + esc((run.log || []).slice(-1)[0] || "") + "</div></div>" +
      (ro ? "" : '<button class="btn btn-ghost btn-sm" data-sw="stop">' + t("وقّف", "Stop") + "</button>") + "</div>";
    else if (run.failed) h += '<div class="banner err pv-note">' + ic("alert") + '<div class="grow small">' + t("خطوة «" + run.failed + "» وقفت بخطأ. اللي خلص محفوظ.", "Step «" + run.failed + "» stopped with an error. What was done is kept.") +
      '<details><summary class="micro">' + t("التفاصيل (الأحدث فوق)", "Details (newest first)") + '</summary><pre class="pv-log" dir="ltr">' + esc((run.log || []).slice().reverse().join("\n")) + "</pre></details></div>" +
      (ro ? "" : '<button class="btn btn-primary btn-sm" data-sw="run">' + t("كمّل", "Resume") + "</button>") + "</div>";
    else if (!ro && x.stage !== "approved" && !run.waiting_outline && x.stage !== "review") h += '<div class="row pv-note"><button class="btn btn-secondary btn-sm" data-sw="run">' + ic("play", "sm flip") + t("كمّل الشغل", "Continue") + "</button></div>";
    if (S.swMsg) h += '<div class="banner ' + (S.swMsg.err ? "err" : "info") + ' pv-note">' + ic("alert") + '<div class="small" dir="auto">' + t(S.swMsg.ar, S.swMsg.en) + "</div></div>";
    h += "</div>";
    if (x.local.only_local) h += '<div class="banner warn">' + ic("alert") + '<div class="grow small">' + t("المتاح على الماك ده النموذج المحلي المجاني بس: يقدر يعمل الطلبات الصغيرة في البحث، لكن مايقدرش يكتب الهيكل ولا المسودة. سجّل دخول Claude من «الربط بالخدمات».",
      "Only the free local model is available on this Mac: it can do research's small requests, but it cannot write the outline or the draft. Sign in to Claude under Integrations.") + "</div></div>";
    h += approvalBox(x, e, ro) + outlineBox(x, ro) + draftBox(x, ro) + cardsBox(x);
    return h + "</div>";
  }
  function scriptHome() {
    var mine = (S.episodes || []).filter(function (e) { return e.script; });
    var h = '<div class="col" style="gap:24px;max-width:980px">' + newScriptCard();
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("السكريبتات", "Scripts") + '</h2><a class="btn btn-ghost btn-sm" href="#/style">' + ic("doc", "sm") + t("دليل أسلوب القنوات", "The channels' style guides") + "</a></div>" +
      (mine.length ? mine.map(function (e) { return '<a class="ep" href="#/script/' + encodeURIComponent(e.id) + '"><div class="thumb">' + ic("pen") + '</div><div class="grow"><b class="small" style="display:block" dir="auto">' + esc(e.script.topic || e.name) + "</b>" +
        '<span class="micro ink2">' + esc(en() ? e.script.stage_en : e.script.stage) + (e.scope !== "projects" ? " · " + t("اختبار", "test") : "") + "</span></div></a>"; }).join("")
        : t("لسه مفيش سكريبتات.", "No scripts yet.", "p", "small ink2")) + "</div>";
    return h + "</div>";
  }
  function newScriptCard() {
    var F = S.sf || (S.sf = { profile: null, mode: "talking_head", topic: "", angle: "", minutes: "", sources: null }), st = S.sfStyle && S.sfStyle.slug === F.profile ? S.sfStyle : null;
    var P = (S.profiles || []).filter(function (x) { return x.slug === F.profile; })[0] || null;   /* only the chosen channel's types */
    var offers = function (m) { return !P || P.types.indexOf(m === "voice_only" ? "audio" : "presenter") >= 0; };
    if (P && !offers(F.mode)) F.mode = offers("talking_head") ? "talking_head" : "voice_only";
    var h = '<div class="card"><div class="card-h"><h2 class="h3">' + t("سكريبت جديد", "New script") + "</h2></div>" +
      '<div class="row wrap" style="gap:8px">' + t("القناة:", "Channel:", "span", "small ink2") + (S.profiles || []).map(function (pr) {
        return '<button class="chip ' + (F.profile === pr.slug ? "gold" : "line") + '" data-sfprof="' + esc(pr.slug) + '">' + esc(pr.name) + "</button>"; }).join("") + "</div>" +
      '<div class="row wrap" style="gap:8px;margin-top:10px">' + t("النوع:", "Type:", "span", "small ink2") +
      (offers("talking_head") ? '<button class="chip ' + (F.mode === "talking_head" ? "gold" : "line") + '" data-sfmode="talking_head">' + t("بمذيع", "With presenter") + "</button>" : "") +
      (offers("voice_only") ? '<button class="chip ' + (F.mode === "voice_only" ? "gold" : "line") + '" data-sfmode="voice_only">' + t("صوت بس", "Audio only") + "</button>" : "") + "</div>" +
      '<input class="input" id="sw-topic" dir="auto" maxlength="300" style="height:40px;margin-top:12px;width:100%" value="' + esc(F.topic) + '" placeholder="' + esc(en() ? "The topic" : "الموضوع") + '">' +
      '<input class="input" id="sw-angle" dir="auto" maxlength="300" style="height:40px;margin-top:8px;width:100%" value="' + esc(F.angle) + '" placeholder="' + esc(en() ? "The angle (optional)" : "الزاوية (اختياري)") + '">' +
      '<div class="row" style="gap:8px;margin-top:8px;align-items:center"><input class="input num" id="sw-minutes" style="height:40px;width:110px" inputmode="decimal" value="' + esc(F.minutes) + '" placeholder="' + esc(st && st.length ? String(st.length.default_minutes) : "—") + '">' +
      t("دقيقة — ", "min — ", "span", "small ink2") + t(st && st.length ? "فاضي = متوسط القناة (" + st.length.default_minutes + " دقيقة)" : "فاضي = متوسط القناة", st && st.length ? "empty = the channel's average (" + st.length.default_minutes + " min)" : "empty = the channel's average", "span", "small ink2") + "</div>";
    if (F.profile && st && st.sources) {
      var on = st.sources.filter(function (s) { return s.on; });
      if (F.sources === null) F.sources = on.map(function (s) { return s.id; });
      h += '<div class="small" style="margin-top:12px"><b>' + t("المصادر (من قايمة القناة):", "Sources (from the channel's list):") + '</b> <a class="micro" href="#/style/' + esc(F.profile) + '">' + t("عدّل القايمة", "edit the list") + "</a></div>" +
        '<div class="row wrap" style="gap:6px;margin-top:6px">' + on.map(function (s) { var sel = F.sources.indexOf(s.id) >= 0;
          return '<button class="chip ' + (sel ? "gold" : "line") + '" data-sfsrc="' + esc(s.id) + '" title="' + esc(s.kind + " · " + s.lang) + '">' + (sel ? ic("check", "sm") : "") + esc(s.name) + "</button>"; }).join("") + "</div>";
    } else if (F.profile && st && !st.sources) h += t("القناة دي مالهاش قايمة مصادر لسه.", "This channel has no source list yet.", "p", "small warnc pv-note");
    var ok = F.profile && F.topic.trim();
    if (S.swMsg) h += '<div class="banner ' + (S.swMsg.err ? "err" : "info") + ' pv-note">' + ic("alert") + '<div class="small" dir="auto">' + t(S.swMsg.ar, S.swMsg.en) + "</div></div>";   /* a refusal shows here too */
    h += '<div class="row" style="gap:8px;margin-top:14px"><button class="btn btn-primary btn-sm" data-sw="new"' + (ok ? "" : " disabled") + ">" + ic("play", "sm flip") + t("ابدأ البحث", "Start the research") + "</button>" +
      t("الوكيل بيدوّر ويطلع بطاقات الحقائق، وبعدين الهيكل، ويقف يستنى موافقتك.", "The agent researches and makes the fact cards, then the outline, and stops for your yes.", "span", "micro ink2") + "</div></div>";
    return h;
  }
  function who() { return (S.state && S.state.user && S.state.user.name) || ""; }
  function approvalBox(x, e, ro) {
    var a = x.approval, h = "";
    if (a.state === "approved") {
      h += '<div class="banner info">' + ic("check") + '<div class="grow small">' + t("السكريبت معتمد — " + esc(a.by) + " — " + esc(a.at) + " (مسودة " + a.version + ")", "The script is approved — " + esc(a.by) + " — " + esc(a.at) + " (draft " + a.version + ")") + "</div>" +
        (ro ? "" : '<button class="btn btn-primary btn-sm" data-sw="episode">' + ic("plus", "sm") + t("استخدمه في حلقة جديدة", "Use it in a new episode") + "</button>") + "</div>";
    } else if (a.state === "cancelled" || a.state === "stale") {
      h += '<div class="banner err">' + ic("alert") + '<div class="grow small"><b>' + t("الاعتماد اتلغى", "The approval was cancelled") + "</b> " +
        t("(كان " + esc(a.by || "") + "، مسودة " + (a.version || "") + "): ", "(it was " + esc(a.by || "") + ", draft " + (a.version || "") + "): ") + '<span dir="auto">' + esc(a.why || "") + "</span>" +
        (a.cancelled_at ? " — " + esc(a.cancelled_at) : "") + t(". راجع المسودة الجديدة واعتمدها تاني.", ". Check the new draft and approve it again.") + "</div></div>";
    }
    return h;
  }
  function outlineBox(x, ro) {
    var o = x.outline;
    if (!o) return "";
    var O = o.outline, gate = !o.ok, h = '<div class="card' + (gate && !ro ? " em" : "") + '"' + (gate && !ro ? ' style="border-color:var(--gold)"' : "") + '><div class="card-h"><h2 class="h3">' + t("الهيكل", "The outline") + "</h2>" +
      (o.ok ? '<span class="chip ok">' + t("موافق عليه — " + esc(o.ok.by), "Approved — " + esc(o.ok.by)) + "</span>" : '<span class="chip gold">' + t("مستني «أيوه» منك", "Waiting for your yes") + "</span>") + "</div>";
    h += '<b dir="auto">' + esc(O.title || "") + "</b>" + (O.angle ? '<div class="small ink2" dir="auto">' + esc(O.angle) + "</div>" : "");
    if (O.cold_open) h += '<div class="small" style="margin-top:8px" dir="auto"><b>' + t("البداية: ", "Cold open: ") + "</b>" + esc(O.cold_open.idea || "") + cardChips(O.cold_open.cards) + "</div>";
    (O.parts || []).forEach(function (pt, i) {
      h += '<div style="padding:8px 0;border-bottom:1px solid var(--line)"><b class="small" dir="auto">' + (i + 1) + ". " + esc(pt.title) + "</b> " +
        '<span class="micro ink2 num">' + (pt.words || "") + t(" كلمة", " words") + "</span>" + '<div class="small ink2" dir="auto">' + esc(pt.goal || "") + "</div>" + cardChips(pt.cards) + "</div>";
    });
    if (O.closing) h += '<div class="small" style="margin-top:8px" dir="auto"><b>' + t("الختام: ", "Closing: ") + "</b>" + esc(typeof O.closing === "string" ? O.closing : JSON.stringify(O.closing)) + "</div>";
    if ((o.made_by || "").indexOf("local") === 0) h += t("الهيكل ده كتبه النموذج المحلي المجاني: راجعه كويس.", "The free local model wrote this outline: read it closely.", "p", "small warnc pv-note");
    if (o.notes.length) h += '<details class="pv-note"><summary class="micro ink2">' + t("ملاحظاتك قبل كده (" + o.notes.length + ")", "Your earlier notes (" + o.notes.length + ")") + "</summary>" + o.notes.map(function (n) { return '<div class="small" dir="auto">' + esc(typeof n === "string" ? n : (n.notes || JSON.stringify(n))) + "</div>"; }).join("") + "</details>";
    if (gate && !ro && !x.run.running) {
      h += '<div class="row wrap" style="gap:8px;margin-top:14px;align-items:center">' + t("باسم:", "As:", "span", "small ink2") + '<input class="input" id="sw-name" style="height:36px;width:200px" value="' + esc(S.swName || who()) + '">' +
        '<button class="btn btn-primary btn-sm" data-sw="outline_ok">' + ic("check", "sm") + t("أيوه، اكتب المسودة", "Yes, write the draft") + "</button></div>" +
        '<textarea class="ta input" id="sw-notes" rows="3" dir="auto" style="height:auto;padding:10px;margin-top:10px;width:100%" placeholder="' + esc(en() ? "Or your notes on the outline: what to change" : "أو ملاحظاتك على الهيكل: إيه اللي يتغيّر") + '">' + esc(S.swNotes || "") + "</textarea>" +
        '<button class="btn btn-secondary btn-sm pv-note" data-sw="outline_edit">' + t("ابعت ملاحظاتي ويعمل الهيكل تاني", "Send my notes and redo the outline") + "</button>";
    }
    return h + "</div>";
  }
  function cardChips(ids) {
    if (!ids || !ids.length) return "";
    var by = {}; ((S.sv && S.sv.cards && S.sv.cards.ok) || []).forEach(function (c) { by[c.id] = c; });
    return '<span class="row wrap" style="gap:4px;display:inline-flex;margin-inline-start:6px">' + ids.map(function (c) { var k = by[c] || {};
      return '<a class="chip line micro" href="#card-' + esc(c) + '" title="' + esc((k.statement || "") + " — " + (k.outlet || "") + " " + (k.pub_date || "")) + '">' + esc(c) + "</a>"; }).join("") + "</span>";
  }
  function draftBox(x, ro) {
    var d = x.draft;
    if (!d) return "";
    var sc = d.script || {}, tot = d.totals || {}, E = S.sed && S.sed.id === S.ssel && S.sed.v === d.version ? S.sed : null;
    var h = '<div class="card"><div class="card-h"><h2 class="h3">' + t("المسودة " + d.version, "Draft " + d.version) + "</h2>" +
      '<span class="small ink2 num">' + (sc.words || 0) + " / " + (sc.target_words || "—") + t(" كلمة", " words") + "</span></div>" +
      '<div class="row wrap" style="gap:8px">' + '<span class="chip ' + (tot.errors ? "err" : "ok") + '">' + t((tot.errors || 0) + " أخطاء", (tot.errors || 0) + " errors") + "</span>" +
      '<span class="chip ' + (tot.warnings ? "warn" : "line") + '">' + t((tot.warnings || 0) + " تنبيهات", (tot.warnings || 0) + " warnings") + "</span>" +
      (sc.local_lines ? '<span class="chip warn">' + t(sc.local_lines + " سطر كتبه النموذج المحلي", sc.local_lines + " lines by the local model") + "</span>" : "") +
      '<span class="chip line">' + t((sc.cards_cited || 0) + " بطاقة مستخدمة", (sc.cards_cited || 0) + " cards cited") + "</span></div>" +
      t("الفحوص التلقائية: مفيش جملة منقولة من مصدر (٦ كلمات ورا بعض)، وكل رقم أو حقيقة ليها بطاقة بمصدرها.", "Automatic checks: no sentence copied from a source (6 words in a row), and every number or fact has its card with its source.", "p", "micro ink2 pv-note");
    if (d.edits_pending) h += '<div class="banner warn pv-note">' + ic("alert") + '<div class="small">' + t("فيه تعديلات لسه مااتفحصتش: «كمّل الشغل» يفحصها ويعمل مسودة جديدة.", "There are edits not yet checked: «Continue» checks them and makes a new draft.") + "</div></div>";
    h += '<div class="col" style="gap:0;margin-top:10px">';
    d.items.forEach(function (it) {
      if (it.kind !== "line") { h += '<div class="small goldc" style="padding:10px 0 4px" dir="auto"><b>' + esc(it.text) + "</b></div>"; return; }
      var ty = TYPE_AR[it.type] || [it.type, it.type], ch = (it.checks || []).filter(function (c) { return c.level !== "info"; }), ed = E && E.lines[it.id] || {};
      var text = E ? '<textarea class="ta input" data-sline="' + it.id + '" rows="2" dir="auto" style="width:100%;height:auto;padding:8px">' + esc(ed.text != null ? ed.text : it.text) + "</textarea>"
        : '<div class="small" dir="auto" style="' + (ed.delete ? "text-decoration:line-through" : "") + '">' + esc(it.text) + "</div>";
      h += '<div style="padding:8px 0;border-bottom:1px solid var(--line)' + (E && ed.delete ? ";opacity:.45" : "") + '"><div class="row wrap" style="gap:6px;align-items:center"><span class="micro ink2 num">' + it.id + "</span>" +
        (E ? '<select class="input" data-stype="' + it.id + '" style="height:28px;font-size:12px">' + Object.keys(TYPE_AR).map(function (k) { return '<option value="' + k + '"' + ((ed.type || it.type) === k ? " selected" : "") + ">" + (en() ? TYPE_AR[k][1] : TYPE_AR[k][0]) + "</option>"; }).join("") + "</select>"
          : '<span class="chip line micro">' + t(ty[0], ty[1]) + "</span>") +
        (it.edited ? '<span class="chip micro">' + t("متعدّل بإيدك", "edited by you") + "</span>" : "") + ((it.made_by || "").indexOf("local") === 0 ? '<span class="chip warn micro">' + t("النموذج المحلي", "local model") + "</span>" : "") +
        cardChips(it.cards) + (E ? '<button class="btn btn-ghost btn-sm" data-sdel="' + it.id + '" style="margin-inline-start:auto">' + t(ed.delete ? "رجّعه" : "امسحه", ed.delete ? "Keep it" : "Delete") + "</button>" +
          '<button class="btn btn-ghost btn-sm" data-sadd="' + it.id + '">' + ic("plus", "sm") + t("سطر بعده", "Line after") + "</button>" : "") + "</div>" + text +
        ch.map(function (c) { return '<div class="micro ' + (c.level === "error" ? "errc" : c.level === "warning" ? "warnc" : "ink2") + '" dir="auto">' + esc(c.text) + "</div>"; }).join("") +
        (E ? (E.after[it.id] || []).map(function (n, k) { return '<textarea class="ta input" data-snew="' + it.id + ":" + k + '" rows="2" dir="auto" style="width:100%;height:auto;padding:8px;margin-top:6px;border-color:var(--gold)" placeholder="' + esc(en() ? "New line" : "سطر جديد") + '">' + esc(n) + "</textarea>"; }).join("") : "") + "</div>";
    });
    h += "</div>";
    if (!ro && !x.run.running) {
      h += E ? '<div class="row wrap" style="gap:8px;margin-top:12px"><button class="btn btn-primary btn-sm" data-sw="edits">' + t("احفظ التعديلات وافحصها", "Save the edits and check them") + '</button><button class="btn btn-ghost btn-sm" data-sedit="off">' + t("إلغي", "Cancel") + "</button>" +
          t("أي تعديل بعد الاعتماد بيلغي الاعتماد، وبيتفحص تاني.", "Any edit after approval cancels the approval and is checked again.", "span", "micro warnc") + "</div>"
        : '<div class="row wrap" style="gap:8px;margin-top:12px;align-items:center"><button class="btn btn-secondary btn-sm" data-sedit="on">' + ic("pen", "sm") + t("عدّل هنا", "Edit here") + "</button>" +
          (d.review_docx ? '<a class="btn btn-secondary btn-sm" href="/api/sfile?id=' + encodeURIComponent(S.ssel) + "&name=" + encodeURIComponent(d.review_docx) + '">' + ic("download", "sm") + t("نسخة Word بتعليقات", "Word copy with comments") + "</a>" +
            '<label class="btn btn-secondary btn-sm">' + ic("upload", "sm") + t("ارفع نسخة Word المعدّلة", "Upload the edited Word copy") + '<input type="file" id="sw-docx" accept=".docx" hidden></label>' : "") + "</div>";
      if (x.approval.state !== "approved" && x.stage === "review" && !d.edits_pending) {
        h += '<div class="row wrap" style="gap:8px;margin-top:14px;align-items:center;padding-top:12px;border-top:1px solid var(--line)">' + t("باسم:", "As:", "span", "small ink2") +
          '<input class="input" id="sw-name2" style="height:36px;width:200px" value="' + esc(S.swName || who()) + '">' +
          (sc.local_lines ? '<label class="small"><input type="checkbox" id="sw-acclocal"> ' + t("قريت سطور النموذج المحلي كويس", "I read the local model's lines closely") + "</label>" : "") +
          '<button class="btn btn-primary btn-sm" data-sw="approve"' + (tot.errors ? " disabled" : "") + ">" + ic("check", "sm") + t("اعتماد السكريبت", "Approve the script") + "</button>" +
          (tot.errors ? t("صلّح الأخطاء الأول.", "Fix the errors first.", "span", "micro errc") : "") + "</div>";
      }
    }
    return h + "</div>";
  }
  function cardsBox(x) {
    var c = x.cards;
    if (!c.ok.length) return "";
    return '<div class="card"><details' + (S.cardsOpen ? " open" : "") + ' id="sw-cards"><summary class="card-h" style="cursor:pointer"><h2 class="h3" style="display:inline">' + t("بطاقات الحقائق", "Fact cards") + '</h2> <span class="small ink2 num">' + c.ok.length +
      (c.dropped ? t(" (واتشال " + c.dropped + ")", " (" + c.dropped + " dropped)") : "") + "</span></summary>" +
      c.ok.map(function (k) { return '<div id="card-' + esc(k.id) + '" style="padding:10px 0;border-bottom:1px solid var(--line)"><div class="row wrap" style="gap:6px"><span class="chip gold micro">' + esc(k.id) + '</span><span class="chip line micro">' + esc(k.kind || "") + "</span>" +
        (k.disputed ? '<span class="chip warn micro">' + t("محل خلاف", "disputed") + "</span>" : "") + '<b class="small" dir="auto">' + esc(k.statement || "") + "</b></div>" +
        (k.passage ? '<blockquote class="small ink2" dir="auto" style="margin:6px 0;padding-inline-start:10px;border-inline-start:3px solid var(--line)">' + esc(k.passage) + "</blockquote>" : "") +
        '<div class="micro ink2">' + esc(k.outlet || "") + (k.pub_date ? " · " + esc(k.pub_date) : "") + (k.url ? ' · <a href="' + esc(k.url) + '" target="_blank" rel="noopener noreferrer">' + t("المصدر", "source") + "</a>" : "") + "</div></div>"; }).join("") + "</details></div>";
  }
  /* the channel's style guide and source list */
  function styleLoad(force) {
    var slug = S.stsel || "general";
    if (!force && S.stv && S.stv.slug === slug) return;
    api("/api/style?slug=" + encodeURIComponent(slug)).then(function (x) { S.stv = x; S.stText = null; render(); });
  }
  function styleView() {
    var x = S.stv;
    if (!x || x.slug !== (S.stsel || "general")) { styleLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل…", "Loading…") + "</p></div>"; }
    if (x.error) return '<div class="card"><p class="small errc">' + esc(x.error) + "</p></div>";
    var h = '<div class="col" style="gap:24px;max-width:980px"><div class="row wrap" style="gap:8px">' + x.channels.map(function (c) {
      return '<a class="chip ' + (c.slug === x.slug ? "gold" : "line") + '" href="#/style/' + esc(c.slug) + '">' + esc(c.name) + "</a>"; }).join("") + "</div>";
    var st = x.status || "", ok = /^approved/.test(st), edited = /edited after approval/.test(st);
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("دليل أسلوب «" + x.name + "»", "«" + x.name + "» style guide") + "</h2>" +
      '<span class="chip ' + (ok ? "ok" : x.guide ? "warn" : "err") + '">' + (ok ? t("معتمد", "Approved") : edited ? t("اتعدّل بعد الاعتماد", "Edited after approval") : x.guide ? t("مسودة", "Draft") : t("مش موجود", "Missing")) + "</span></div>" +
      '<div class="small ink2" dir="ltr">' + esc(st) + "</div>" +
      (x.length ? t("متوسط القناة: " + x.length.default_minutes + " دقيقة، " + x.length.script_words_per_minute + " كلمة في الدقيقة.", "The channel's average: " + x.length.default_minutes + " min, " + x.length.script_words_per_minute + " words a minute.", "p", "small ink2") : "") +
      (x.guide === null ? t("القناة دي مالهاش دليل أسلوب لسه. اكتبه هنا، أو اتعلّمه من سكريبتاتها بالأمر bin/monteer script learn-style.", "This channel has no style guide yet. Write it here, or learn it from its scripts with bin/monteer script learn-style.", "p", "small warnc") : "") +
      '<textarea class="ta input" id="st-text" dir="auto" rows="22" style="width:100%;height:auto;padding:12px;margin-top:10px;font-size:13px;line-height:1.7">' + esc(S.stText != null ? S.stText : (x.guide || "")) + "</textarea>" +
      '<div class="row wrap" style="gap:8px;margin-top:10px;align-items:center"><button class="btn btn-secondary btn-sm" data-st="save">' + t("احفظ الدليل", "Save the guide") + "</button>" +
      t("باسم:", "As:", "span", "small ink2") + '<input class="input" id="st-name" style="height:36px;width:200px" value="' + esc(who()) + '">' +
      '<button class="btn btn-primary btn-sm" data-st="approve"' + (x.guide && !ok ? "" : " disabled") + ">" + ic("check", "sm") + t("اعتمد الدليل", "Approve the guide") + "</button>" +
      t("أي تعديل بعد الاعتماد بيرجّعه «اتعدّل بعد الاعتماد» لحد ما تعتمده تاني.", "Any edit after approval shows «edited after approval» until you approve it again.", "span", "micro ink2") + "</div>" +
      (S.stMsg ? '<div class="banner ' + (S.stMsg.err ? "err" : "info") + ' pv-note"><div class="small">' + t(S.stMsg.ar, S.stMsg.en) + "</div></div>" : "") + "</div>";
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("قايمة مصادر القناة", "The channel's source list") + "</h2></div>";
    if (!x.sources) h += t("مفيش قايمة لسه.", "No list yet.", "p", "small ink2") + '<button class="btn btn-secondary btn-sm" data-st="init">' + t("اعمل القايمة الأساسية", "Make the default list") + "</button>";
    else {
      h += x.sources.map(function (s) { var c = s.checked || {};
        return '<div class="row" style="gap:8px;padding:6px 0;border-bottom:1px solid var(--line)"><button class="chip ' + (s.on ? "ok" : "line") + '" data-st="' + (s.on ? "off" : "on") + '" data-stid="' + esc(s.id) + '">' + (s.on ? t("شغّال", "On") : t("مقفول", "Off")) + "</button>" +
          '<span class="small grow" dir="auto">' + esc(s.name) + ' <span class="micro ink2">' + esc(s.kind + " · " + s.lang + " · " + s.access) + "</span>" + (s.note ? '<div class="micro warnc" dir="auto">' + esc(s.note) + "</div>" : "") + "</span>" +
          (c.result ? '<span class="micro ' + (c.result === "ok" ? "okc" : "warnc") + '">' + esc(c.result + " " + (c.at || "")) + "</span>" : "") + "</div>"; }).join("");
      h += '<details class="pv-note"><summary class="small">' + t("ضيف مصدر", "Add a source") + '</summary><div class="col" style="gap:6px;margin-top:8px">' +
        ["id", "name", "kind", "lang", "access", "url"].map(function (k) { return '<input class="input" id="st-src-' + k + '" style="height:34px" placeholder="' + k + (k === "kind" ? " (news|official|data|legal|reference)" : k === "access" ? " (rss|domain|gdelt|…)" : "") + '" dir="ltr">'; }).join("") +
        '<button class="btn btn-secondary btn-sm" data-st="add">' + t("ضيف", "Add") + "</button></div></details>" +
        '<div class="row wrap pv-note" style="gap:8px;align-items:center"><button class="btn btn-secondary btn-sm" data-st="check"' + (x.checking ? " disabled" : "") + ">" + ic(x.checking ? "loader" : "retry", "sm") +
          t(x.checking ? "بيفحص المصادر… (دقايق)" : "افحص المصادر", x.checking ? "Checking the sources… (minutes)" : "Check the sources") + "</button>" +
          t("بيجرّب كل مصدر؛ اللي بيقع بيتقفل ومكتوب جنبه ليه.", "It tries every source; one that fails is switched off, with why.", "span", "micro ink2") + "</div>" +
          (x.last_check ? '<details class="pv-note"><summary class="small">' + t("آخر فحص: ", "Last check: ") + esc(x.last_check.name) + '</summary><pre class="pv-log" dir="auto" style="white-space:pre-wrap">' + esc(x.last_check.text) + "</pre></details>" : "");
    }
    return h + "</div></div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-sw],[data-sfprof],[data-sfmode],[data-sfsrc],[data-sedit],[data-sdel],[data-sadd],[data-st]") : null;
    if (!el || el.disabled) return;
    if (el.hasAttribute("data-st")) {
      var act = el.getAttribute("data-st"), body = { slug: S.stv.slug, action: act };
      if (act === "save") body.text = document.getElementById("st-text").value;
      if (act === "approve") body.name = (document.getElementById("st-name") || {}).value || "";
      if (act === "on" || act === "off") body.id = el.getAttribute("data-stid");
      if (act === "add") { body.source = {}; ["id", "name", "kind", "lang", "access", "url"].forEach(function (k) { body.source[k] = (document.getElementById("st-src-" + k) || {}).value || ""; }); }
      post("/api/style", body).then(function (d) {
        if (d.error) { S.stMsg = { ar: "ماتنفذش: " + d.error, en: "Not done: " + d.error, err: true }; render(); return; }
        S.stv = d; S.stText = null; S.stMsg = act === "approve" ? { ar: "الدليل اتعتمد.", en: "The guide is approved." } : act === "save" ? { ar: "اتحفظ.", en: "Saved." }
          : act === "check" ? { ar: "الفحص شغّال في الخلفية؛ النتيجة بتظهر هنا لما يخلص.", en: "The check runs in the background; the results show here when it ends." } : null; render();
      });
      return;
    }
    var F = S.sf;
    if (el.hasAttribute("data-sfprof")) { F.profile = el.getAttribute("data-sfprof"); F.sources = null; S.swMsg = null; api("/api/style?slug=" + encodeURIComponent(F.profile)).then(function (x) { S.sfStyle = x; render(); }); render(); return; }
    if (el.hasAttribute("data-sfmode")) { F.mode = el.getAttribute("data-sfmode"); render(); return; }
    if (el.hasAttribute("data-sfsrc")) { var sid = el.getAttribute("data-sfsrc"), i = F.sources.indexOf(sid); if (i >= 0) F.sources.splice(i, 1); else F.sources.push(sid); render(); return; }
    var x = S.sv, d = x && x.draft;
    if (el.hasAttribute("data-sedit")) { S.sed = el.getAttribute("data-sedit") === "on" ? { id: S.ssel, v: d.version, lines: {}, after: {} } : null; render(); return; }
    if (el.hasAttribute("data-sdel")) { var lid = el.getAttribute("data-sdel"), L = S.sed.lines[lid] || (S.sed.lines[lid] = {}); L.delete = !L.delete; render(); return; }
    if (el.hasAttribute("data-sadd")) { var a = el.getAttribute("data-sadd"); (S.sed.after[a] || (S.sed.after[a] = [])).push(""); render(); return; }
    var act2 = el.getAttribute("data-sw"), body2 = { id: S.ssel, action: act2 };
    if (act2 === "episode") {                    /* an approved script starts a new episode with its channel chosen */
      var sid = S.ssel, prof = x.channel.profile, ty = x.type === "voice_only" ? "audio" : "presenter";
      el.disabled = true;                        /* the approved scripts fetched now: one approved on this page is in it */
      api("/api/scripts").then(function (d) { S.scripts = d.scripts || []; }).catch(function () {}).then(function () {
        var sc = (S.scripts || []).filter(function (y) { return y.id === sid; })[0];
        S.form = freshForm(); S.form.profile = prof; S.form.type = ty;
        if (sc) S.form.script = { ok: true, name: sc.name + " (script.docx)", path: sc.path, bytes: 0, from: sc.id };
        location.hash = "#/new";
      });
      return;
    }
    if (act2 === "new") {
      body2 = { action: "new", profile: F.profile, mode: F.mode, topic: F.topic, angle: F.angle, minutes: F.minutes || null, sources: F.sources || [], name: F.topic };
    }
    if (act2 === "outline_ok" || act2 === "approve") body2.name = S.swName = ((document.getElementById(act2 === "approve" ? "sw-name2" : "sw-name") || {}).value || "").trim();
    if (act2 === "approve") body2.accept_local = !!((document.getElementById("sw-acclocal") || {}).checked);
    if (act2 === "outline_edit") body2.notes = (document.getElementById("sw-notes") || {}).value || "";
    if (act2 === "edits") {
      var ed = [];
      Object.keys(S.sed.lines).forEach(function (k) { var L2 = S.sed.lines[k], orig = d.items.filter(function (y) { return y.id === k; })[0] || {};
        if (L2.delete) ed.push({ id: k, "delete": true });
        else { var e1 = { id: k }; if (L2.text != null && L2.text !== orig.text) e1.text = L2.text; if (L2.type && L2.type !== orig.type) e1.type = L2.type; if (e1.text || e1.type) ed.push(e1); } });
      Object.keys(S.sed.after).forEach(function (k) { S.sed.after[k].forEach(function (tx) { if (tx.trim()) ed.push({ after: k, text: tx.trim() }); }); });
      if (!ed.length) { S.swMsg = { ar: "مفيش تعديل.", en: "No edit.", err: true }; render(); return; }
      body2.edits = ed; body2.name = who();
    }
    el.disabled = true;
    post("/api/script", body2).then(function (r) {
      if (r.error) { S.swMsg = { ar: "ماتنفذش: " + r.error, en: "Not done: " + r.error, err: true }; render(); return; }
      S.swMsg = null;
      if (act2 === "new") { S.sf = null; location.hash = "#/script/" + encodeURIComponent(r.id); refresh(); return; }
      if (act2 === "edits") S.sed = null;
      if (act2 === "outline_edit") S.swNotes = "";
      if (act2 === "approve") api("/api/scripts").then(function (d) { S.scripts = d.scripts || []; }).catch(function () {});
      scriptLoad(true); refresh();
    });
  });
  document.addEventListener("input", function (ev) {
    var id = ev.target.id || "";
    if (S.sf && id === "sw-topic") { S.sf.topic = ev.target.value; var b = document.querySelector('[data-sw="new"]'); if (b) b.disabled = !(S.sf.profile && S.sf.topic.trim()); }
    if (S.sf && id === "sw-angle") S.sf.angle = ev.target.value;
    if (S.sf && id === "sw-minutes") S.sf.minutes = ev.target.value;
    if (id === "sw-notes") S.swNotes = ev.target.value;
    if (id === "st-text") S.stText = ev.target.value;
    var sl = ev.target.getAttribute && ev.target.getAttribute("data-sline");
    if (sl && S.sed) (S.sed.lines[sl] || (S.sed.lines[sl] = {})).text = ev.target.value;
    var sn = ev.target.getAttribute && ev.target.getAttribute("data-snew");
    if (sn && S.sed) { var pp = sn.split(":"); S.sed.after[pp[0]][+pp[1]] = ev.target.value; }
  });
  document.addEventListener("change", function (ev) {
    var ty = ev.target.getAttribute && ev.target.getAttribute("data-stype");
    if (ty && S.sed) (S.sed.lines[ty] || (S.sed.lines[ty] = {})).type = ev.target.value;
    if (ev.target.id === "sw-docx" && ev.target.files && ev.target.files[0]) {
      var f = ev.target.files[0];
      S.swMsg = { ar: "برفع نسخة Word…", en: "Uploading the Word copy…" }; render();
      fetch("/api/review_upload?id=" + encodeURIComponent(S.ssel), { method: "PUT", credentials: "same-origin", body: f }).then(function (r) { return r.json(); }).then(function (d) {
        S.swMsg = d.error ? { ar: "ماترفعتش: " + d.error, en: "Not uploaded: " + d.error, err: true } : { ar: "اترفعت، والتعديلات بتتفحص دلوقتي.", en: "Uploaded; the edits are being checked now." };
        scriptLoad(true); refresh();
      });
    }
  });
  /* phase 9: the rulebook, and editing a rule with the owner's review */
  function rulesLoad() { api("/api/rules").then(function (x) { S.rb = x; if (S.route === "rules" && !typing()) render(); }); }
  function plain(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`([^`]+)`/g, '<code dir="ltr">$1</code>'); }
  function rulesView() {
    var x = S.rb;
    if (!x) { rulesLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل الدستور…", "Loading the rulebook…") + "</p></div>"; }
    var h = '<div class="col" style="gap:24px;max-width:1000px"><div class="page-h"><div>' + t("الدستور", "Rulebook", "h1", "h1") +
      t("قواعد المونتاج زي ما المحرك والعقل بيقروها من ملفات القواعد، وكل قاعدة بتتطبّق فين. أي تعديل بيتعرض عليك قبل ما يتكتب.", "The editing rules as the engine and the brain read them from the rule files, and where each is applied. Any edit is shown to you before it is written.", "p") + "</div></div>";
    var pend = x.proposals.filter(function (p) { return p.status === "proposed"; }), done = x.proposals.filter(function (p) { return p.status !== "proposed"; });
    if (pend.length) h += '<div class="card em" style="border-color:var(--gold)"><div class="card-h"><h2 class="h3">' + t("تعديلات مستنية موافقتك", "Edits waiting for your approval") + '</h2><span class="chip gold num">' + pend.length + "</span></div>" +
      pend.map(function (p) { return '<div style="padding:10px 0;border-bottom:1px solid var(--line)"><b class="small">' + t("قاعدة " + p.rule, "Rule " + p.rule) + "</b> · " + '<span class="micro ink2">' + esc(p.by + " · " + p.at) + "</span>" +
        '<pre class="pv-log" dir="auto" style="white-space:pre-wrap;margin-top:6px">' + p.diff.slice(2).map(function (l) {
          return '<span style="color:' + (l[0] === "+" ? "var(--success)" : l[0] === "-" ? "var(--danger)" : "inherit") + '">' + esc(l) + "</span>"; }).join("\n") + "</pre>" +
        '<div class="row wrap" style="gap:8px;margin-top:6px;align-items:center">' + t("باسم:", "As:", "span", "small ink2") + '<input class="input" id="rb-name-' + esc(p.id) + '" style="height:32px;width:180px" value="' + esc(who()) + '">' +
        '<button class="btn btn-primary btn-sm" data-rb="approve" data-rbid="' + esc(p.id) + '">' + ic("check", "sm") + t("اعتمد التعديل", "Approve the edit") + "</button>" +
        '<button class="btn btn-ghost btn-sm" data-rb="reject" data-rbid="' + esc(p.id) + '">' + t("ارفضه", "Reject it") + "</button></div></div>"; }).join("") +
      t("التعديل المعتمد بيتكتب في ملف القاعدة وبيتسجّل في rules/CHANGES.md. الحلقات اللي جاية بتمشي عليه؛ القرارات اللي طلبها مااتغيّرش بتفضل زي ما هي.", "An approved edit is written in the rule's file and logged in rules/CHANGES.md. Coming runs follow it; decisions whose request did not change stay as they are.", "p", "micro ink2 pv-note") + "</div>";
    if (S.rbMsg) h += '<div class="banner ' + (S.rbMsg.err ? "err" : "info") + '"><div class="small">' + t(S.rbMsg.ar, S.rbMsg.en) + "</div></div>";
    var groups = [["Cutting", "التقطيع", "Cutting"], ["Montage", "المونتاج", "Montage"], ["18-24", "فيديو بيشد المشاهد (١٨–٢٤)", "A video that keeps viewers (18–24)"]];
    groups.forEach(function (g) {
      var rs = x.rules.filter(function (r) { return r.group === g[0]; });
      if (!rs.length) return;
      h += '<div class="card"><h2 class="h3">' + t(g[1], g[2]) + "</h2>" + rs.map(function (r) {
        var editing = S.rbEdit === r.n;
        return '<div style="padding:12px 0;border-bottom:1px solid var(--line)"><div class="row wrap" style="gap:8px;align-items:baseline"><span class="chip gold num">' + r.n + '</span><b dir="auto">' + esc(r.title) + "</b>" +
          (editing ? "" : '<button class="btn btn-ghost btn-sm" data-rbedit="' + r.n + '" style="margin-inline-start:auto">' + ic("pen", "sm") + t("عدّل", "Edit") + "</button>") + "</div>" +
          (editing ? '<textarea class="ta input" id="rb-text" dir="auto" rows="8" style="width:100%;height:auto;padding:10px;margin-top:8px;font-size:13px">' + esc(S.rbText != null ? S.rbText : r.text) + "</textarea>" +
            '<div class="row wrap" style="gap:8px;margin-top:8px;align-items:center">' + t("باسم:", "As:", "span", "small ink2") + '<input class="input" id="rb-who" style="height:32px;width:180px" value="' + esc(who()) + '">' +
            '<button class="btn btn-secondary btn-sm" data-rb="propose" data-rbn="' + r.n + '">' + t("اعرض التعديل للمراجعة", "Show the edit for review") + '</button><button class="btn btn-ghost btn-sm" data-rbedit="">' + t("إلغي", "Cancel") + "</button></div>"
            : '<div class="small ink2" dir="auto" style="margin-top:6px;white-space:pre-wrap">' + plain(r.text.replace(/^\d+\.\s*/, "")) + "</div>") +
          '<div class="row wrap" style="gap:6px;margin-top:6px">' + (r.where ? '<span class="micro ink2">' + t("بتتطبّق في: ", "Applied in: ") + '<span dir="ltr">' + esc(r.where) + "</span></span>" : "") +
          r.applied_in.map(function (f) { return '<span class="chip line micro" dir="ltr">' + esc(f.replace("monteer/", "")) + "</span>"; }).join("") + "</div></div>"; }).join("") + "</div>";
    });
    x.sections.forEach(function (s) {
      h += '<div class="card"><details><summary class="h3" style="cursor:pointer">' + esc(s.title) + '</summary><div class="small ink2" dir="auto" style="white-space:pre-wrap;margin-top:8px">' + plain(s.text) + "</div></details></div>";
    });
    if (done.length) h += '<div class="card"><details><summary class="small">' + t("التعديلات اللي فاتت (" + done.length + ")", "Past edits (" + done.length + ")") + "</summary>" +
      done.map(function (p) { return '<div class="small" style="padding:4px 0">' + t("قاعدة " + p.rule, "Rule " + p.rule) + " — " + (p.status === "applied" ? t("اتعتمد", "approved", "b", "okc") + " " + esc(p.approved_by + " " + p.approved_at) : t("اترفض", "rejected", "b", "warnc") + " " + esc((p.rejected_by || "") + " " + (p.why || ""))) + "</div>"; }).join("") + "</details></div>";
    return h + "</div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-rb],[data-rbedit]") : null;
    if (!el || el.disabled) return;
    if (el.hasAttribute("data-rbedit")) { var n = el.getAttribute("data-rbedit"); S.rbEdit = n ? +n : null; S.rbText = null; render(); return; }
    var act = el.getAttribute("data-rb"), body = { action: act };
    if (act === "propose") { body.n = +el.getAttribute("data-rbn"); body.text = (document.getElementById("rb-text") || {}).value || ""; body.name = (document.getElementById("rb-who") || {}).value || ""; }
    else { body.id = el.getAttribute("data-rbid"); body.name = (document.getElementById("rb-name-" + body.id) || {}).value || who(); }
    el.disabled = true;
    post("/api/rules", body).then(function (d) {
      if (d.error) { S.rbMsg = { ar: "ماتنفذش: " + d.error, en: "Not done: " + d.error, err: true }; render(); return; }
      S.rb = d; S.rbMsg = act === "approve" ? { ar: "التعديل اتعتمد واتكتب في القاعدة.", en: "The edit is approved and written in the rule." } : act === "propose" ? { ar: "التعديل مستني مراجعتك فوق.", en: "The edit waits for your review above." } : null;
      if (act === "propose") { S.rbEdit = null; S.rbText = null; }
      render();
    });
  });
  document.addEventListener("input", function (ev) { if (ev.target.id === "rb-text") S.rbText = ev.target.value; });
  /* the training library (the plan's later part, first version): raw + published pairs per channel */
  function trainingLoad() { api("/api/training").then(function (x) { S.tl = x; if (S.route === "training" && !typing()) render(); }); }
  function trainingView() {
    var x = S.tl;
    if (!x) { trainingLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل…", "Loading…") + "</p></div>"; }
    var F = S.tr || (S.tr = { slug: "general", title: "", raw_video: null, raw_audio: null, script: null, published_video: null, published_link: "", notes: "" });
    var h = '<div class="col" style="gap:24px;max-width:1000px"><div class="page-h"><div>' + t("مكتبة التدريب", "Training library", "h1", "h1") +
      t("أزواج الخام والمنشور لكل قناة. أول نسخة: بتحفظ الأزواج بس — التعلّم منها مشروع لوحده بعدين. تحت كل قناة: الوكيل بيتعلّم من إيه النهارده.",
        "Raw and published pairs per channel. First version: it keeps the pairs only — learning from them is a project of its own, later. Under each channel: what the agent learns from today.", "p") + "</div></div>";
    x.channels.forEach(function (c) {
      h += '<div class="card"><div class="card-h"><h2 class="h3">' + esc(c.name) + '</h2><span class="small ink2 num">' + c.pairs.length + t(" زوج", " pairs") + "</span></div>" +
        c.learns_from.map(function (l) { return '<div class="small ink2">' + ic("book", "sm") + " " + esc(l.what) + " — " + esc(l.from) + "</div>"; }).join("") +
        c.pairs.map(function (p) { return '<div class="row wrap" style="gap:8px;padding:8px 0;border-bottom:1px solid var(--line)"><b class="small grow" dir="auto">' + esc(p.title) + "</b>" +
          '<span class="micro ink2" dir="ltr">' + esc(((p.raw_video || p.raw_audio || "").split("/").pop()) + " → " + (p.published_link || (p.published_video || "").split("/").pop())) + "</span>" +
          '<span class="chip line micro">' + t("لسه ماتعلّمش منه", "not learned from yet") + "</span>" +
          '<button class="btn btn-ghost btn-sm" data-tr="remove" data-trslug="' + esc(c.slug) + '" data-trid="' + esc(p.id) + '">' + ic("x", "sm") + "</button></div>"; }).join("") + "</div>";
    });
    var pickBtn = function (k, ar, eng) { var v = F[k]; return '<div class="row wrap" style="gap:8px;align-items:center"><button class="btn btn-secondary btn-sm" data-trpick="' + k + '">' + t(ar, eng) + "</button>" +
      (v ? '<span class="micro ' + (v.ok ? "okc" : "errc") + '" dir="ltr">' + esc(v.name || "") + (v.ok ? "" : " — " + esc(v.why || "")) + "</span>" : "") + "</div>"; };
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("ضيف زوج", "Add a pair") + "</h2></div>" +
      '<div class="row wrap" style="gap:8px">' + x.channels.map(function (c) { return '<button class="chip ' + (F.slug === c.slug ? "gold" : "line") + '" data-trslugpick="' + esc(c.slug) + '">' + esc(c.name) + "</button>"; }).join("") + "</div>" +
      '<input class="input" id="tr-title" dir="auto" style="height:38px;width:100%;margin-top:10px" value="' + esc(F.title) + '" placeholder="' + esc(en() ? "Title" : "العنوان") + '">' +
      '<div class="col" style="gap:8px;margin-top:10px">' + pickBtn("raw_video", "الخام: فيديو الكاميرا", "Raw: the camera video") + pickBtn("raw_audio", "الخام: الصوت (اختياري)", "Raw: the audio (optional)") +
      pickBtn("script", "السكريبت (اختياري)", "The script (optional)") + pickBtn("published_video", "المنشور: الفيديو", "Published: the video") + "</div>" +
      '<input class="input" id="tr-link" dir="ltr" style="height:38px;width:100%;margin-top:8px" value="' + esc(F.published_link) + '" placeholder="' + esc(en() ? "or the published link (https://…)" : "أو لينك المنشور (https://…)") + '">' +
      '<textarea class="ta input" id="tr-notes" dir="auto" rows="2" style="width:100%;height:auto;padding:8px;margin-top:8px" placeholder="' + esc(en() ? "Notes (optional)" : "ملاحظات (اختياري)") + '">' + esc(F.notes) + "</textarea>" +
      '<button class="btn btn-primary btn-sm pv-note" data-tr="add">' + ic("plus", "sm") + t("ضيف الزوج", "Add the pair") + "</button>" +
      t("الملفات بتفضل مكانها؛ بيتحفظ مكانها بس.", "The files stay where they are; only their place is kept.", "span", "micro ink2") +
      (S.trMsg ? '<div class="banner ' + (S.trMsg.err ? "err" : "info") + ' pv-note"><div class="small">' + t(S.trMsg.ar, S.trMsg.en) + "</div></div>" : "") + "</div>";
    return h + "</div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-tr],[data-trpick],[data-trslugpick]") : null;
    if (!el || el.disabled) return;
    var F = S.tr;
    if (el.hasAttribute("data-trslugpick")) { F.slug = el.getAttribute("data-trslugpick"); render(); return; }
    if (el.hasAttribute("data-trpick")) {
      var k = el.getAttribute("data-trpick"), kind = k === "raw_audio" ? "audio" : k === "script" ? "script" : "video";
      el.disabled = true;
      post("/api/pick", { kind: kind }).then(function (d) { var f = (d.files || [])[0]; if (f) F[k] = f; if (d.error) S.trMsg = { ar: d.error, en: d.error, err: true }; render(); });
      return;
    }
    var act = el.getAttribute("data-tr"), body = { action: act };
    if (act === "remove") { body.slug = el.getAttribute("data-trslug"); body.id = el.getAttribute("data-trid"); }
    else {
      var path = function (k) { return F[k] && F[k].ok ? F[k].path : null; };
      body.slug = F.slug; body.name = who();
      body.pair = { title: F.title, raw_video: path("raw_video"), raw_audio: path("raw_audio"), script: path("script"), published_video: path("published_video"), published_link: F.published_link, notes: F.notes };
    }
    post("/api/training", body).then(function (d) {
      if (d.error) { S.trMsg = { ar: "مااتضافش: " + d.error, en: "Not added: " + d.error, err: true }; render(); return; }
      S.tl = d; S.trMsg = act === "add" ? { ar: "الزوج اتضاف.", en: "The pair was added." } : null;
      if (act === "add") S.tr = { slug: F.slug, title: "", raw_video: null, raw_audio: null, script: null, published_video: null, published_link: "", notes: "" };
      render();
    });
  });
  document.addEventListener("input", function (ev) {
    if (!S.tr) return;
    if (ev.target.id === "tr-title") S.tr.title = ev.target.value;
    if (ev.target.id === "tr-link") S.tr.published_link = ev.target.value;
    if (ev.target.id === "tr-notes") S.tr.notes = ev.target.value;
  });
  /* the channels screen, read-only, and the box to tell «عام» things */
  function channelsLoad() { api("/api/channels").then(function (x) { S.chv = x; if (S.route === "channels" && !typing()) render(); }); }
  function val(v) { var s = typeof v === "string" ? v : JSON.stringify(v); return s == null ? "—" : s.length > 140 ? s.slice(0, 140) + "…" : s; }
  function channelsView() {
    var x = S.chv;
    if (!x) { channelsLoad(); return '<div class="card"><p class="small ink2">' + t("بحمّل…", "Loading…") + "</p></div>"; }
    var c = x.channels.filter(function (y) { return y.slug === S.chsel; })[0] || x.channels[0];
    var h = '<div class="col" style="gap:24px;max-width:1040px"><div class="page-h"><div>' + t("القنوات", "Channels", "h1", "h1") +
      t("كل قناة زي ما المحرك شايفها النهارده. للقراءة بس — التعديل بعدين، وكل تعديل بموافقتك.", "Each channel as the engine sees it today. Read-only — editing comes later, each change with your approval.", "p") + "</div></div>" +
      '<div class="row wrap" style="gap:8px">' + x.channels.map(function (y) { return '<a class="chip ' + (y.slug === c.slug ? "gold" : "line") + '" href="#/channels/' + esc(y.slug) + '">' + esc(y.name) + "</a>"; }).join("") + "</div>";
    h += '<div class="card"><div class="row wrap" style="gap:8px">' + c.types.map(function (ty) { return '<span class="chip">' + (ty === "presenter" ? t("بمذيع", "With presenter") : t("صوت بس", "Audio only")) + "</span>"; }).join("") +
      '<a class="chip line" href="#/style/' + esc(c.slug) + '">' + t("دليل الأسلوب: ", "Style guide: ") + esc(c.style) + "</a>" +
      (c.sources ? '<a class="chip line" href="#/style/' + esc(c.slug) + '">' + t("المصادر: " + c.sources.on + " شغّالة من " + c.sources.all, "Sources: " + c.sources.on + " on of " + c.sources.all) + "</a>" : "") + "</div>" +
      '<div class="small ink2" style="margin-top:8px">' + t("الفيديوهات المرجعية: ", "Reference videos: ") + c.reference.videos.length + (c.reference.study.length ? t(" — المقاسة: ", " — measured: ") + esc(c.reference.study.join(", ")) : "") + "</div></div>";
    var imgs = c.files.filter(function (f) { return f.kind === "image"; }), media = c.files.filter(function (f) { return f.kind === "media"; });
    h += '<div class="card"><h2 class="h3">' + t("هوية القناة", "The channel's identity") + "</h2>" +
      (imgs.length ? '<div class="row wrap" style="gap:12px;margin-top:8px">' + imgs.map(function (f) { return '<div style="text-align:center"><div style="background:repeating-conic-gradient(#3a3a3a 0 25%,#2a2a2a 0 50%) 50%/16px 16px;padding:8px;border-radius:8px">' +
        '<img alt="" style="max-height:90px;max-width:220px;display:block" src="/api/chimg?slug=' + encodeURIComponent(c.slug) + "&path=" + encodeURIComponent(f.path) + '"></div><div class="micro ink2" dir="ltr">' + esc(f.path.split("/").pop()) + "</div></div>"; }).join("") + "</div>"
        : t("مفيش لوجو للقناة دي (زي ما اتفقنا).", "No logo for this channel (as decided).", "p", "small ink2")) +
      (c.clips.length ? '<div class="small" style="margin-top:12px"><b>' + t("كليبات القناة:", "The channel's clips:") + "</b>" + c.clips.map(function (k) {
        return '<div class="row" style="gap:8px;padding:4px 0"><span class="chip ' + (k.on ? "ok" : "line") + ' micro">' + (k.on ? t("شغّال", "on") : t("مقفول", "off")) + '</span><span dir="auto">' + esc(k.what) + '</span><span class="micro ink2" dir="ltr">@ ' + esc(k.at) + "</span></div>"; }).join("") + "</div>" : "") +
      (media.length ? '<div class="micro ink2" style="margin-top:8px" dir="ltr">' + media.map(function (f) { return esc(f.path.split("/").pop()) + " (" + size(f.bytes) + ")"; }).join(" · ") + "</div>" : "") + "</div>";
    if (c.slug === "general") h += generalBox(x.general_box);
    var rd = c.settings.filter(function (s) { return s.read; }), later = c.settings.filter(function (s) { return !s.read; });
    var tbl = function (rows) { return '<table class="tbl"><tbody>' + rows.map(function (s) { return '<tr><td class="micro" dir="ltr" style="white-space:nowrap">' + esc(s.key) + '</td><td class="micro" dir="auto">' + esc(val(s.value)) + "</td></tr>"; }).join("") + "</tbody></table>"; };
    h += '<div class="card"><div class="card-h"><h2 class="h3">' + t("إعدادات المونتاج اللي المحرك بيقراها النهارده", "Montage settings the engine reads today") + '</h2><span class="chip ok num">' + rd.length + "</span></div>" + tbl(rd) + "</div>" +
      '<div class="card"><details><summary class="h3" style="cursor:pointer">' + t("متسجّلة لمرحلة بعدين", "Recorded for a later phase") + ' <span class="chip line num">' + later.length + "</span></summary>" + tbl(later) + "</details></div>";
    return h + "</div>";
  }
  function generalBox(b) {
    var h = '<div class="card em" style="border-color:var(--gold)"><div class="card-h"><h2 class="h3">' + t("قول حاجة لـ«عام»", "Tell «عام» something") + "</h2>" +
      '<span class="small ink2">' + t("سجلات: " + b.records + " فيديو خلصان", "Records: " + b.records + " finished videos") + "</span></div>" +
      t("«عام» بيطبّق كلامك من أول فيديو جاي، كتذكير في طلباته — عمره ما بيتخطى القواعد الثابتة ولا تعليمات الحلقة.", "«عام» applies your words from its next video, as a reminder in its requests — never above the standing rules or the episode's instructions.", "p", "small ink2") +
      '<div class="row" style="gap:8px;margin-top:8px"><input class="input grow" id="ch-tell" dir="auto" maxlength="1000" style="height:38px" placeholder="' + esc(en() ? "e.g. use fewer maps, more real footage of people" : "مثلاً: قلل الخرايط وزوّد لقطات الناس الحقيقية") + '">' +
      '<button class="btn btn-primary btn-sm" data-learn="tell">' + t("قوله", "Tell it") + "</button></div>";
    var act = b.notes.filter(function (n) { return n.active !== false; });
    if (act.length) h += '<div class="small" style="margin-top:12px"><b>' + t("اللي قلته:", "What you told it:") + "</b>" + act.map(function (n) {
      return '<div class="row" style="gap:8px;padding:4px 0"><span class="grow" dir="auto">' + esc(n.text) + '</span><span class="micro ink2">' + esc(n.at) + '</span><button class="btn btn-ghost btn-sm" data-learn="forget" data-ln="' + n.n + '">' + t("انساها", "Forget it") + "</button></div>"; }).join("") + "</div>";
    h += '<div class="small" style="margin-top:12px"><b>' + t("الدروس اللي فيديو «عام» جديد هياخدها دلوقتي:", "The lessons a new «عام» video would get now:") + "</b>" +
      (b.lessons_now.length ? b.lessons_now.map(function (l) { return '<div class="small ink2" dir="auto" style="padding:3px 0">• ' + esc(l.text) + ' <span class="micro">(' + esc(l.why) + ")</span></div>"; }).join("")
        : t(" لسه مفيش — محتاج حاجة تتكرر في أكتر من فيديو.", " none yet — something has to recur across videos.", "span", "ink2")) + "</div>";
    if (S.lnMsg) h += '<div class="banner ' + (S.lnMsg.err ? "err" : "info") + ' pv-note"><div class="small">' + t(S.lnMsg.ar, S.lnMsg.en) + "</div></div>";
    return h + "</div>";
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-learn]") : null;
    if (!el || el.disabled) return;
    var act = el.getAttribute("data-learn"), body = { action: act, name: who() };
    if (act === "tell") body.text = (document.getElementById("ch-tell") || {}).value || ""; else body.n = +el.getAttribute("data-ln");
    post("/api/learn", body).then(function (d) {
      if (d.error) { S.lnMsg = { ar: "ماتنفذش: " + d.error, en: "Not done: " + d.error, err: true }; render(); return; }
      S.chv.general_box = d.general_box; S.lnMsg = act === "tell" ? { ar: "«عام» هيطبّقها من أول فيديو جاي.", en: "«عام» applies it from its next video." } : null; render();
    });
  });
  /* paid services (20 Oct 2026: Magnific for الحدث الأخير and اقتصاد احمس): what it was used for, from its use log */
  function paidStat() {
    var m = S.cst && S.cst.magnific, sb = S.cst && S.cst.storyblocks;
    if (sb && sb.used) return '<div class="stat" style="padding:20px">' + t("Storyblocks + Magnific (مدفوع)", "Storyblocks + Magnific (paid)") + '<b class="num">' +
      (sb.downloads_month + ((m && m.downloads_month) || 0)) + "</b>" +
      t("تحميل الشهر ده: Storyblocks " + sb.downloads_month + " · Magnific " + ((m && m.downloads_month) || 0), "downloads this month: Storyblocks " + sb.downloads_month + " · Magnific " + ((m && m.downloads_month) || 0), "span", "small mutedc") + "</div>";
    if (!m || !m.connected) return '<div class="stat" style="padding:20px">' + t("الخدمات المدفوعة", "Paid services") + '<b class="num">0</b>' + t("مفيش خدمة مدفوعة مربوطة", "No paid service is connected", "span", "small mutedc") + "</div>";
    return '<div class="stat" style="padding:20px">' + t("Magnific (فيديوهات مدفوعة)", "Magnific (paid videos)") + '<b class="num">' + m.downloads_month + "</b>" +
      t("تحميل الشهر ده · النهارده " + m.downloads_today + " من " + m.daily_cap + " · " + m.searches_month + " بحث", "downloads this month · today " + m.downloads_today + " of " + m.daily_cap + " · " + m.searches_month + " searches", "span", "small mutedc") + "</div>";
  }
  function storyblocksCard(c) {
    var s = c.storyblocks;
    if (!s || !s.used) return "";
    var eps = Object.keys(s.by_episode || {});
    return '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("Storyblocks — الاستخدام", "Storyblocks — use") + "</h2>" + '<a class="small" href="#/paid">' + t("التفاصيل ←", "Details →") + "</a>" +
      '<span class="small ink2">' + t("اشتراك الشركة · الحدث الأخير واقتصاد احمس بس", "the company's subscription · الحدث الأخير and اقتصاد احمس only") + "</span></div>" +
      t("كل تحميل بيترخّص على حساب الشركة. بيتحمّل بس الفيديو اللي اتختار، نسخة HD MP4 (مش 4K)، وبحد " + s.cap_per_episode + " في الحلقة.",
        "Every download is licensed on the company's account. Only picked clips are downloaded, as HD MP4 (never 4K), at most " + s.cap_per_episode + " an episode.", "p", "small ink2") +
      '<div class="row" style="gap:24px;margin:8px 0"><div>' + t("تحميلات الشهر ده", "Downloads this month", "div", "small ink2") + '<b class="h2 num">' + s.downloads_month + "</b></div>" +
      "<div>" + t("النهارده", "Today", "div", "small ink2") + '<b class="h2 num">' + s.downloads_today + "</b></div>" +
      "<div>" + t("عمليات بحث", "Searches", "div", "small ink2") + '<b class="h2 num">' + s.searches_month + "</b></div></div>" +
      (eps.length ? '<table class="tbl"><thead><tr><th>' + t("الحلقة", "Episode") + "</th><th>" + t("تحميلات", "Downloads") + "</th></tr></thead><tbody>" +
        eps.map(function (k) { return "<tr><td>" + esc(k) + '</td><td class="num">' + s.by_episode[k] + " / " + s.cap_per_episode + "</td></tr>"; }).join("") + "</tbody></table>" : "") +
      (s.audit ? t("تنبيه: " + s.audit + " مرة اتطلب رابط تحميل لفيديو مش في القايمة (اتسجّل)", "Warning: " + s.audit + " time(s) a link was asked for a clip not on the list (logged)", "p", "micro warnc") : "") +
      (s.failed ? t(s.failed + " تحميل ماكملش", s.failed + " download(s) did not complete", "p", "micro warnc") : "") + "</div>";
  }
  function magnificCard(c) {
    var m = c.magnific;
    if (!m || !m.connected) return "";
    var eps = Object.keys(m.by_episode || {});
    var heads = Object.keys(m.credit_headers || {});
    return '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("Magnific — الاستخدام", "Magnific — use") + "</h2>" +
      '<span class="small ink2">' + t("الحدث الأخير واقتصاد احمس بس", "الحدث الأخير and اقتصاد احمس only") + "</span></div>" +
      t("بيتحمّل بس الفيديو اللي اتختار للقطة، مرة واحدة. الحد " + m.daily_cap + " تحميل في اليوم.", "Only the clip picked for a shot is downloaded, once. The cap is " + m.daily_cap + " downloads a day.", "p", "small ink2") +
      (eps.length ? '<table class="tbl"><thead><tr><th>' + t("الحلقة", "Episode") + "</th><th>" + t("تحميلات الشهر ده", "Downloads this month") + "</th></tr></thead><tbody>" +
        eps.map(function (k) { return "<tr><td>" + esc(k) + '</td><td class="num">' + m.by_episode[k] + "</td></tr>"; }).join("") + "</tbody></table>" : "") +
      (heads.length ? t("آخر رصيد بعتته Magnific: ", "Magnific's last reported figures: ", "p", "micro ink2") + '<div class="micro ink2" dir="ltr">' + heads.map(function (k) { return esc(k + ": " + m.credit_headers[k]); }).join(" · ") + "</div>" :
        t("Magnific مابتبعتش الرصيد في ردودها؛ الرصيد في حسابك على magnific.com.", "Magnific's replies do not carry the balance; it is on your magnific.com account.", "p", "micro ink2")) +
      (m.failed ? t(m.failed + " تحميل ماكملش", m.failed + " download(s) did not complete", "p", "micro warnc") : "") + "</div>";
  }
  /* «استخدام الخدمات المدفوعة» (owner's (d) of 20 Oct 2026): Magnific and Storyblocks by episode, day and month, against
     each plan's limits; Magnific's credit balance (read-only, at most once an hour from here) */
  function paidUsage() {
    var u = S.paid;
    if (!u || S.paidStale) {
      S.paidStale = false;
      api("/api/paid_usage?refresh=1").then(function (x) { S.paid = x; if (S.route === "paid") render();
        if (x.refreshing) setTimeout(function () { S.paidStale = true; if (S.route === "paid") render(); }, 25000); });
      if (!u) return t("بيحمّل…", "Loading…", "p", "ink2");
    }
    var tab = S.paidTab || "storyblocks", m = u.magnific, s = u.storyblocks, x = tab === "magnific" ? m : s;
    var h = '<div class="page-h"><div>' + t("استخدام الخدمات المدفوعة", "Paid services use", "h1", "h1") +
      t("Storyblocks (اشتراك الشركة) وMagnific: بالحلقة واليوم والشهر، قدام حدود كل خطة.", "Storyblocks (the company's subscription) and Magnific: by episode, day and month, against each plan's limits.", "p") + "</div></div>";
    h += '<div class="row" style="gap:8px;margin-bottom:16px">' + ["storyblocks", "magnific"].map(function (k) {
      return '<button class="chip ' + (tab === k ? "gold" : "line") + '" data-paidtab="' + k + '">' + (k === "storyblocks" ? "Storyblocks" : "Magnific") + "</button>"; }).join("") + "</div>";
    var lim = tab === "magnific" ? m.limit_per_day : null;
    h += '<div class="grid g3" style="gap:24px">' +
      '<div class="stat" style="padding:20px">' + t("النهارده", "Today") + '<b class="num">' + x.today.downloads + (lim ? " / " + lim : "") + "</b>" +
        t("تحميل · " + x.today.searches + " بحث", "downloads · " + x.today.searches + " searches", "span", "small mutedc") +
        (lim ? '<div class="bar thin" style="margin-top:8px"><i style="width:' + Math.min(100, 100 * x.today.downloads / lim) + '%"></i></div>' : "") + "</div>" +
      '<div class="stat" style="padding:20px">' + t("الشهر ده", "This month") + '<b class="num">' + x.month.downloads + "</b>" +
        t("تحميل · " + x.month.searches + " بحث · " + x.month.refused_size + " اترفض للحجم (أكبر من " + x.size_limit_mb + " ميجا)", "downloads · " + x.month.searches + " searches · " + x.month.refused_size + " refused for size (over " + x.size_limit_mb + " MB)", "span", "small mutedc") + "</div>";
    if (tab === "magnific") {
      var b = m.balance;
      h += '<div class="stat" style="padding:20px">' + t("رصيد Magnific", "Magnific balance") + '<b class="num">' + (b && b.available != null ? b.available : "—") + "</b>" +
        (b ? t("من " + (b.total_plan != null ? b.total_plan : "—") + " · اتصرف " + (b.spent != null ? b.spent : "—") + " · " + (b.plan || b.tier || "") + " · اتقرا " + b.at,
               "of " + (b.total_plan != null ? b.total_plan : "—") + " · spent " + (b.spent != null ? b.spent : "—") + " · " + (b.plan || b.tier || "") + " · read " + b.at, "span", "small mutedc")
           : t("لسه ماتقراش", "not read yet", "span", "small mutedc")) +
        (u.refreshing ? t("بيتقري دلوقتي…", "reading now…", "div", "micro ink2") : "") + "</div>";
    } else {
      h += '<div class="stat" style="padding:20px">' + t("حد الحلقة", "Per-episode cap") + '<b class="num">' + s.cap_per_episode + "</b>" +
        t(s.month.audit ? "تنبيه: " + s.month.audit + " طلب لفيديو مش في القايمة" : "مفيش طلبات برّه القايمة", s.month.audit ? "warning: " + s.month.audit + " request(s) off the list" : "no request off the list", "span", s.month.audit ? "small warnc" : "small mutedc") + "</div>";
    }
    h += "</div>";
    /* the last 30 days */
    var top = Math.max(lim || 0, 1, Math.max.apply(null, x.days.map(function (d) { return d.downloads; })));
    h += '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("آخر ٣٠ يوم", "The last 30 days") + "</h2>" +
      (lim ? '<span class="small ink2">' + t("الخط: حد " + lim + " في اليوم", "the line: the limit of " + lim + " a day") + "</span>" : "") + "</div>" +
      '<div style="position:relative;display:flex;align-items:flex-end;gap:3px;height:140px;padding-top:8px">' +
      (lim ? '<div style="position:absolute;inset-inline:0;bottom:' + (100 * lim / top) + '%;border-top:1px dashed var(--danger)"></div>' : "") +
      x.days.map(function (d) { return '<div title="' + esc(d.day + ": " + d.downloads + " / " + d.searches) + '" style="flex:1;background:var(--gold);opacity:' + (d.downloads ? 1 : 0.15) +
        ';height:' + Math.max(2, 100 * d.downloads / top) + '%;border-radius:3px 3px 0 0"></div>'; }).join("") + "</div>" +
      '<div class="row between micro ink2"><span class="num">' + esc(x.days[0].day) + '</span><span class="num">' + esc(x.days[x.days.length - 1].day) + "</span></div></div>";
    /* by episode */
    var eps = x.episodes || [];
    h += '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("بالحلقة", "By episode") + "</h2></div>" +
      (eps.length ? '<table class="tbl"><thead><tr><th>' + t("الحلقة", "Episode") + "</th><th>" + t("تحميلات", "Downloads") + "</th><th>" + t("في الفيديو", "In the video") + "</th><th>" +
        t("اترفض للحجم", "Refused for size") + "</th><th>" + t("ماكملش", "Failed") + "</th><th>" + (tab === "magnific" ? t("كريديت اتصرف", "Credits spent") : t("طلبات مرخّصة", "Licensed requests")) + "</th></tr></thead><tbody>" +
        eps.map(function (e) { return "<tr><td>" + esc(e.name) + '<div class="micro ink2">' + esc(e.last) + '</div></td><td class="num">' + e.downloads + (e.cap ? " / " + e.cap : "") +
          '</td><td class="num">' + (e.used_in_video == null ? "—" : e.used_in_video) + '</td><td class="num">' + e.refused_size + '</td><td class="num">' + e.failed + '</td><td class="num">' +
          (tab === "magnific" ? (e.credits_spent == null ? "—" : e.credits_spent) : e.licensed_calls) + "</td></tr>"; }).join("") + "</tbody></table>"
        : t("لسه مفيش حلقة استخدمته.", "No episode has used it yet.", "p", "small ink2")) + "</div>";
    /* by month */
    h += '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("بالشهر", "By month") + "</h2></div>" +
      (x.months.length ? '<table class="tbl"><thead><tr><th>' + t("الشهر", "Month") + "</th><th>" + t("تحميلات", "Downloads") + "</th><th>" + t("بحث", "Searches") + "</th><th>" + t("اترفض للحجم", "Refused for size") + "</th></tr></thead><tbody>" +
        x.months.map(function (r) { return '<tr><td class="num">' + esc(r.month) + '</td><td class="num">' + r.downloads + '</td><td class="num">' + r.searches + '</td><td class="num">' + r.refused_size + "</td></tr>"; }).join("") + "</tbody></table>"
        : t("مفيش لسه.", "Nothing yet.", "p", "small ink2")) + "</div>";
    return h;
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-paidtab]") : null;
    if (el) { S.paidTab = el.getAttribute("data-paidtab"); render(); }
  });
  /* phase 8: costs by month and recent use; keys */
  function costsMore() {
    var c = S.cst;
    if (!c) { api("/api/costs").then(function (x) { S.cst = x; if (S.route === "costs") render(); }); return ""; }
    var h = storyblocksCard(c) + magnificCard(c) + '<div class="card" style="margin-top:24px"><div class="card-h"><h2 class="h3">' + t("شغل العقل بالشهر", "The brain's work by month") + "</h2>" +
      '<span class="small ink2">' + t("كل الحلقات (" + c.scopes.projects + " حلقة + " + c.scopes.tests + " اختبار)", "Every episode (" + c.scopes.projects + " episodes + " + c.scopes.tests + " tests)") + "</span></div>" +
      '<table class="tbl"><thead><tr><th>' + t("الشهر", "Month") + "</th><th>" + t("قرارات", "Decisions") + "</th><th>" + t("وقت العقل", "Brain time") + "</th><th>" + t("توكنز", "Tokens") + "</th><th>" +
      t("مكافئ API (للعرض)", "API equivalent (shown only)") + "</th><th>" + t("النموذج المحلي", "Local model") + "</th></tr></thead><tbody>" +
      c.months.map(function (m) { return '<tr><td class="num">' + esc(m.month) + '</td><td class="num">' + m.decisions + '</td><td class="num">' + dur(m.brain_s) + '</td><td class="num" dir="ltr">' + tok(m.tokens) +
        '</td><td class="num">$' + m.api_equivalent_usd.toFixed(2) + '</td><td class="num">' + m.local + "</td></tr>"; }).join("") + "</tbody></table></div>";
    h += '<div class="grid g2" style="gap:24px;margin-top:24px"><div class="card"><h2 class="h3">' + t("استخدام الاشتراك مؤخرًا", "Recent use of the subscription") + "</h2>" +
      '<div class="row" style="gap:24px;margin-top:8px"><div>' + t("آخر ٥ ساعات", "Last 5 hours", "div", "small ink2") + '<b class="h2 num">' + dur(c.recent.h5.brain_s) + '</b><div class="micro ink2">' + c.recent.h5.decisions + t(" قرار", " decisions") + "</div></div>" +
      "<div>" + t("آخر ٧ أيام", "Last 7 days", "div", "small ink2") + '<b class="h2 num">' + dur(c.recent.d7.brain_s) + '</b><div class="micro ink2">' + c.recent.d7.decisions + t(" قرار", " decisions") + "</div></div></div>" +
      t("حدود الاشتراك بتتحسب في الفترتين دول. Claude Code مابيقولش للمحرك اتصرف قد إيه منها، فده وقت العقل بتاعنا كدليل بس. لو الحد خلص، الشغل بيستنى لوحده ويكمّل.",
        "The subscription's limits are counted over these two windows. Claude Code does not tell the engine how much of them is used, so this is the brain's own time, as a guide. If the limit is reached, the run waits by itself and goes on.", "p", "micro ink2 pv-note") + "</div>" +
      '<div class="card"><h2 class="h3">' + t("سقف شهري", "Monthly cap") + "</h2>" +
      t("العقل على اشتراكك والأدوات المحلية ببلاش. الخدمات المدفوعة (Storyblocks باشتراك الشركة، وMagnific بخطته) للحدث الأخير واقتصاد احمس بس، وبحدود: ٦٠ فيديو Storyblocks في الحلقة و١٠٠ تحميل Magnific في اليوم. استخدامها كله في «استخدام الخدمات المدفوعة».",
        "The brain runs on your subscription and local tools are free. The paid services (Storyblocks on the company's subscription, Magnific on its plan) are for الحدث الأخير and اقتصاد احمس only, within limits: 60 Storyblocks clips an episode and 100 Magnific downloads a day. All their use is on «Paid services use».", "p", "small ink2") + "</div></div>";
    return h;
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-key],[data-keyrm]") : null;
    if (!el) return;
    var name = el.getAttribute("data-key") || el.getAttribute("data-keyrm"), body = { name: name };
    if (el.hasAttribute("data-keyrm")) body.remove = true; else body.value = (document.getElementById("key-" + name) || {}).value || "";
    post("/api/keys", body).then(function (d) {
      S.keyMsg = d.error ? { ar: "مااتحفظش: " + d.error, en: "Not saved: " + d.error, err: true } : { ar: "اتحفظ.", en: "Saved." };
      if (!d.error && S.state) S.state.keys = d.keys;
      render();
    });
  });
  function brainCheck() {
    return api("/api/brain").then(function (b) { if (S.state) S.state.brain = b; render(); });
  }
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-brain-check],[data-so-open],[data-so-cancel],#so-go") : null;
    if (!el) return;
    var so = S.so || (S.so = { open: false, text: "", busy: false, msg: null });
    if (el.hasAttribute("data-brain-check")) { so.msg = null; brainCheck(); }
    else if (el.hasAttribute("data-so-open")) { so.open = true; so.text = ""; so.msg = null; render(); var i = document.getElementById("so-text"); if (i) i.focus(); }
    else if (el.hasAttribute("data-so-cancel")) { so.open = false; so.text = ""; render(); }
    else if (el.id === "so-go" && !el.disabled) {
      so.busy = true; render();
      post("/api/claude_signout", { confirm: so.text }).then(function (d) {
        so.busy = false;
        if (d.error) { so.msg = { ar: "ماسجّلتش خروج: " + d.error, en: "Not signed out: " + d.error, err: true }; }
        else { so.open = false; so.text = ""; if (S.state) S.state.brain = d.brain;
               so.msg = { ar: "اتسجّل خروج مستخدم الماك ده من Claude Code. الحلقات هتقف في أول خطوة لحد ما يسجّل دخول تاني.",
                          en: "This Mac user is signed out of Claude Code. Episodes stop at their first step until they sign in again." }; }
        render();
      }).catch(function () { so.busy = false; so.msg = { ar: "اللوحة مارَدّتش", en: "The panel did not answer", err: true }; render(); });
    }
  });
  document.addEventListener("input", function (ev) {        /* the typed confirmation: the button wakes when it matches */
    if (ev.target.id !== "so-text" || !S.so) return;
    S.so.text = ev.target.value;
    var b = (S.state && S.state.brain) || {}, want = (b.email || "SIGN OUT").toLowerCase(), go = document.getElementById("so-go");
    if (go) go.disabled = S.so.busy || S.so.text.trim().toLowerCase() !== want;
  });
  function later(key) {
    var x = LATER[key], when = x[3] ? t("لسه — بتتبني في المرحلة " + x[3] + " من خطة اللوحة", "Not built yet — phase " + x[3] + " of the panel plan")
      : t("لسه — هتتبني بعدين كمشروع لوحده", "Not built yet — later, as its own project");
    var extra = "";
    if (key === "integrations" && S.state) {
      var k = S.state.keys, names = Object.keys(k);
      extra = '<div class="card" style="margin-top:24px"><h2 class="h3">' + t("اللي اللوحة شايفاه دلوقتي (حقيقي)", "What the panel sees now (real)") + "</h2>" +
        '<div class="small" style="margin-top:8px">' + t("النموذج المحلي: ", "Local model: ") + (S.state.local_model ? t("موجود", "present", "b", "okc") : t("مش موجود", "missing", "b", "warnc")) + "</div>" +
        names.map(function (n) { return '<div class="small" dir="ltr">' + esc(n) + ": " + (k[n] ? '<b class="okc">present</b>' : '<b class="warnc">missing</b>') + "</div>"; }).join("") + "</div>";
    }
    return '<div class="card"><div class="empty"><div class="ico">' + ic(x[0], "xl") + "</div>" + t(x[1], x[2], "h2", "h2") +
      '<span class="chip warn">' + when + "</span>" + t(x[4], x[5], "p", "ink2 small") + "</div></div>" + extra;
  }


  /* ---------------------------------------------------------------- New episode (phase 2) */
  function rid() { var a = new Uint8Array(12); crypto.getRandomValues(a); return Array.prototype.map.call(a, function (x) { return ("0" + x.toString(36)).slice(-2); }).join("").slice(0, 20); }
  /* «٣ · المصادر» (owner's (c) of 20 Oct 2026; bug of 21 Oct 2026: the old free-only card stayed): today's real sources,
     the three choices for a channel with paid sources, and whether Magnific and Storyblocks are connected */
  var SRC_NAMES = { storyblocks: "Storyblocks", magnific: "Magnific" };
  function srcLabel(eo) {
    var paid = (eo && eo.paid_sources) || [], v = S.form && S.form.sources;
    if (!paid.length || v === "free") return t("مجاني بس", "Free only");
    return v === "paid" ? t("مدفوع بس", "Paid only") : t("مجاني + مدفوع", "Free + paid");
  }
  function sourcesCard(eo) {
    var F = S.form, paid = (eo && eo.paid_sources) || [], st = S.paidStatus;
    if (paid.length && !st && !S.paidStatusAsked) {
      S.paidStatusAsked = true;
      api("/api/paid_status").then(function (x) { S.paidStatus = x; if (S.route === "new") render(); });
    }
    var opt = function (on, inner, attr) {
      return '<button class="opt' + (on ? " on" : "") + '" ' + (attr || "") + ' style="padding:16px"><span class="radio"></span><span class="col" style="gap:4px">' + inner + "</span></button>";
    };
    var free = t("Pixabay (فيديو وصور) والمكتبة المحلية على الماك ده. التكلفة: ٠", "Pixabay (videos and photos) and the local library on this Mac. Cost: 0", "span", "small ink2");
    if (!paid.length) {
      return opt(true, t("مجاني بس", "Free only", "b") + free) +
        t("الخدمات المدفوعة (Storyblocks وMagnific) للحدث الأخير واقتصاد احمس بس.", "The paid services (Storyblocks and Magnific) are for الحدث الأخير and اقتصاد احمس only.", "p", "micro ink2");
    }
    var names = paid.map(function (k) { return SRC_NAMES[k]; }).join(" + ");
    var conn = paid.map(function (k) {
      var s = st && st[k];
      var state = !s ? t("بيتأكد…", "checking…") : s.connected ? t("مربوط ✓", "connected ✓") : s.connected === null ? t("ماعرفناش نتأكد", "could not check") : t("مش مربوط", "not connected");
      return '<span class="chip ' + (s && s.connected ? "ok" : "line") + '">' + SRC_NAMES[k] + ": " + state + "</span>";
    }).join(" ");
    var down = paid.filter(function (k) { return st && st[k] && st[k].connected === false; });
    return opt(F.sources === "both", t("مجاني + مدفوع (الافتراضي)", "Free + paid (default)", "b") +
        t(names + " الأول، وبعدين Pixabay والمكتبة المحلية.", names + " first, then Pixabay and the local library.", "span", "small ink2"), 'data-sources="both"') +
      opt(F.sources === "free", t("مجاني بس", "Free only", "b") + free +
        t("أسرع ومفيش تحميل مرخّص، بس صور أكتر (ممكن مايوصلش ٦٠٪ فيديو).", "Faster, no licensed downloads, but more photos (may miss 60% video).", "span", "small ink2"), 'data-sources="free"') +
      opt(F.sources === "paid", t("مدفوع بس", "Paid only", "b") +
        t(names + " بس للقطات. فيديو أكتر وتحميلات مرخّصة أكتر؛ اللي مالقاش يتعمل له خطة تانية.", names + " only for footage. More video, more licensed downloads; shots with no match are re-planned.", "span", "small ink2"), 'data-sources="paid"') +
      '<div class="row wrap" style="gap:6px">' + conn + "</div>" +
      (down.length && F.sources !== "free" ? t("تنبيه: " + down.map(function (k) { return SRC_NAMES[k]; }).join(" و") + " مش مربوط — اللقطات هتيجي من الباقي.",
        "Note: " + down.map(function (k) { return SRC_NAMES[k]; }).join(" and ") + " is not connected — the footage will come from the others.", "p", "micro warnc") : "");
  }
  function freshForm() {
    return { profile: null, ad: null, series_tag: false, opening: null, sources: "both", type: "presenter", title: "", output: "montage", video: null, audio: null, script: null, scriptFrom: "",
             clips: [], uploads: {}, instructions: "", run_mode: "auto", draft: rid(), busy: false, err: null };
  }
  function fileZone(key, icon, ar, en, opt, f) {
    var head, body, foot;
    if (f && f.busy) {
      head = '<span class="chip info"><span class="dot pulse"></span>' + t("بيترفع", "Uploading") + "</span>";
      body = '<div class="uz-f">' + esc(f.name) + "</div>";
      foot = '<div class="bar thin"><i style="width:' + (f.pct || 0) + '%"></i></div><div class="row between small ink2"><span class="num">' + (f.pct || 0) + "%</span></div>";
      return '<div class="uz busy"><div class="uz-top"><span class="uz-ico">' + ic(icon) + "</span>" + head + "</div><div>" + t(ar, en, "div", "uz-t") + body + '</div><div class="uz-foot">' + foot + "</div></div>";
    }
    if (f && f.ok) {
      var meta = [size(f.bytes)];
      if (f.seconds) meta.push(dur(f.seconds));
      if (f.width) meta.push(f.width + "×" + f.height);
      return '<div class="uz ready"><div class="uz-top"><span class="uz-ico">' + ic(icon) + '</span><span class="chip ok">' + ic("check") + t("جاهز", "Ready") + "</span></div>" +
        "<div>" + t(ar, en, "div", "uz-t") + '<div class="uz-f" title="' + esc(f.path || f.name) + '">' + esc(f.name) + "</div></div>" +
        '<div class="uz-foot"><div class="row between"><span class="small ink2 num" dir="ltr">' + esc(meta.join(" · ")) + "</span>" +
        '<button class="btn btn-ghost btn-sm" data-clear="' + key + '">' + t("غيّر", "Change") + "</button></div></div></div>";
    }
    if (f && f.ok === false) {
      return '<div class="uz fail"><div class="uz-top"><span class="uz-ico">' + ic("alert") + '</span><span class="chip err">' + t("مش نافع", "Can't use it") + "</span></div>" +
        "<div>" + t(ar, en, "div", "uz-t") + '<div class="uz-f">' + esc(f.name) + '</div><div class="uz-msg errc">' + esc(f.why) + "</div></div>" +
        '<div class="uz-foot"><button class="btn btn-secondary btn-sm" data-pick="' + key + '">' + t("اختار ملف تاني", "Choose another file") + "</button></div></div>";
    }
    return '<div class="uz empty" data-pick="' + key + '" role="button" tabindex="0"><span class="uz-ico">' + ic(icon) + "</span><div>" + t(ar, en, "div", "uz-t") +
      '<div class="uz-f">' + (opt ? t("اختياري", "Optional") : t("مطلوب", "Required")) + " · " + t("من جهازك", "from this Mac") + "</div></div>" +
      '<span class="btn btn-secondary btn-sm">' + ic("folder", "sm") + t("اختار", "Choose") + "</span></div>";
  }
  function clipsZone(F) {
    var up = Object.keys(F.uploads).map(function (k) { return F.uploads[k]; });
    var all = F.clips.concat(up), rows = all.map(function (c) {
      var st = c.busy ? '<span class="chip info"><span class="dot pulse"></span><span class="num" data-uppct="' + esc(c.key) + '">' + (c.pct || 0) + "%</span></span>"
        : c.ok === false ? '<span class="chip err">' + t("مش نافع", "Can't use it") + "</span>" : '<span class="chip ok">' + ic("check") + t("جاهز", "Ready") + "</span>";
      var why = c.ok === false ? '<div class="micro errc">' + esc(c.why) + "</div>" : "";
      return '<div class="pv-out"><span class="name small" title="' + esc(c.name) + '">' + esc(c.name) + why + '</span><span class="micro ink2 num" dir="ltr">' +
        (c.bytes ? size(c.bytes) : "") + (c.seconds ? " · " + dur(c.seconds) : "") + "</span>" + st +
        (c.busy ? "" : '<button class="btn btn-ghost btn-sm" data-rmclip="' + esc(c.key) + '">' + ic("x", "sm") + "</button>") + "</div>";
    }).join("");
    return '<div class="uz ' + (all.length ? "ready" : "empty") + '" id="pv-drop" style="grid-column:1/-1;min-height:120px">' +
      '<div class="uz-top"><span class="uz-ico">' + ic("clip") + "</span>" + t("لقطات إضافية (كليباتك)", "Extra clips (your own)", "div", "uz-t") +
      '<span class="row" style="gap:8px"><label class="btn btn-secondary btn-sm" for="pv-files">' + ic("upload", "sm") + t("ارفع", "Upload") + "</label>" +
      '<input id="pv-files" type="file" accept="video/*" multiple hidden>' +
      '<button class="btn btn-ghost btn-sm" data-pick="clips">' + ic("folder", "sm") + t("اختار من الجهاز", "Pick on this Mac") + "</button></span></div>" +
      (rows || '<div class="uz-f">' + t("اختياري · اسحب الكليبات هنا. المونتاج بيستخدمها الأول لو بتورّي الكلام، بنفس الفحوصات زي أي لقطة (من غير علَم أو لوجو أو وشوش قريبة لناس عادية).",
        "Optional · drop clips here. The montage uses them first where they show what is said, after the same checks as any footage (no flag, logo or close-up faces of private people).") + "</div>") + "</div>";
  }
  function newForm() {
    var F = S.form || (S.form = freshForm());
    var profs = S.profiles || [], P = profs.filter(function (x) { return x.slug === F.profile; })[0] || null;
    var offers = function (ty) { return !P || P.types.indexOf(ty) >= 0; };   /* only the chosen profile's types */
    if (P && !offers(F.type)) { F.type = P.types[0]; if (F.type !== "presenter") F.output = "montage"; }
    var pres = F.type === "presenter";
    var opt = function (on, dis, inner, attr) {
      return '<button class="opt' + (on ? " on" : "") + '"' + (dis ? " disabled" : "") + " " + (attr || "") + ' style="padding:16px' + (dis ? ";opacity:.55;cursor:not-allowed" : "") + '"><span class="radio"></span><span class="col" style="gap:4px">' + inner + "</span></button>";
    };
    var scripts = (S.scripts || []).filter(function (x) { return true; });
    var miss = [];
    if (!P) miss.push(["اختار القناة", "choose the channel"]);
    if (!F.title.trim()) miss.push(["اكتب عنوان الحلقة", "write the title"]);
    if (F.ad && F.ad.ok === false) miss.push(["الإعلان مش نافع", "the ad can't be used"]);
    if (pres && !(F.video && F.video.ok)) miss.push(["اختار فيديو الكاميرا", "choose the camera video"]);
    if (pres && !(F.script && F.script.ok)) miss.push(["اختار السكريبت", "choose the script"]);
    if (pres && F.script && F.script.ok && /\.txt$/i.test(F.script.path || "")) miss.push(["السكريبت لحلقة بمذيع لازم Word (.docx)", "a presenter episode needs a Word (.docx) script"]);
    if (!pres && !(F.audio && F.audio.ok)) miss.push(["اختار ملف الصوت", "choose the audio"]);
    if (Object.keys(F.uploads).some(function (k) { return F.uploads[k].busy; })) miss.push(["استنى الرفع يخلص", "wait for the upload to finish"]);
    var okClips = F.clips.filter(function (c) { return c.ok; }).length + Object.keys(F.uploads).filter(function (k) { return F.uploads[k].ok; }).length;
    var h = '<div class="page-h"><div>' + t("حلقة جديدة", "New episode", "h1", "h1") +
      t("اختار الخام من جهازك، والوكيل يعمل الباقي. الشغل كله على الجهاز ده.", "Pick the raw material on this Mac; the agent does the rest. The work runs on this computer.", "p") + "</div></div>";
    // 0 · the channel profile (no default: the owner's answer 3 of 18 Oct 2026)
    h += '<div class="card"><div class="card-h">' + t("القناة", "Channel", "h2", "h3") +
      t("لازم تختار. كل قناة ليها شكلها، وأنواع الحلقات اللي بتقدمها.", "Required. Each channel has its own look and the episode types it offers.", "span", "small ink2") + "</div>" +
      (profs.length ? '<div class="grid g3">' + profs.map(function (x) {
        var kinds = x.types.map(function (ty) { return ty === "presenter" ? t("بمذيع", "With presenter") : t("صوت بس", "Audio only"); }).join(" · ");
        return opt(F.profile === x.slug, false, t(x.name, x.name, "b") + '<span class="small ink2">' + kinds + "</span>", 'data-profile="' + esc(x.slug) + '"');
      }).join("") + "</div>"
        : t("مفيش قنوات متجهزة (فولدر channels).", "No channel profiles are set up (the channels folder).", "p", "small errc")) + "</div>";
    // 1 · type, title, output
    h += '<div class="card"><div class="card-h">' + t("١ · نوع الحلقة", "1 · Episode type", "h2", "h3") +
      '<label class="row small ink2" style="gap:8px">' + t("العنوان", "Title") + '<input class="input" id="pv-title" style="width:340px;height:38px" value="' + esc(F.title) + '" maxlength="200"></label></div>' +
      '<div class="grid g2">' +
      opt(pres, !offers("presenter"), '<span class="row">' + ic("mic") + t("بمذيع", "With presenter", "b", "") + "</span>" +
        t("فيديو الكاميرا + السكريبت (+ صوت المايك لو منفصل). الوكيل يزامن ويشيل الإعادات والسكوت، وبعدين يبني المونتاج حوالين المذيع.",
          "Camera video + script (+ the mic audio if separate). The agent syncs, cuts retakes and silences, then builds the montage around the presenter.", "span", "small ink2"), 'data-type="presenter"') +
      opt(!pres, !offers("audio"), '<span class="row">' + ic("wave") + t("صوت بس", "Audio only", "b", "") + "</span>" +
        t("ملف صوت، أو فيديو ناخد صوته. الوكيل يبني الصورة كلها، ومفيش مذيع بيظهر.",
          "An audio file, or a video whose sound is used. The agent builds the whole picture; no presenter appears.", "span", "small ink2"), 'data-type="audio"') + "</div>";
    var eo = (P && P.options) || {};
    if (eo.ad || eo.series_tag || (eo.openings || []).length > 1) {      /* what an episode of this channel may choose */
      h += '<div class="pv-sec">' + t("اختيارات القناة", "Channel options", "b", "label") + '</div><div class="grid g3">';
      if ((eo.openings || []).length > 1) {
        var op = F.opening || eo.opening;
        h += opt(op === "motion", false, t("بداية موشن", "Motion opening", "b") + t("جرافيك وكتابة موشن الأول، وبعدين اللقطات (المفضلة).", "Our graphics and kinetic text first, then footage (preferred).", "span", "small ink2"), 'data-opening="motion"') +
          opt(op === "timelapse", false, t("بداية تايم لابس", "Time-lapse opening", "b") + t("لقطات بتسرع: ٢×٣ث، ٣×٢ث، ٦×١ث، ١٠×نص ثانية.", "Shots that speed up: 2×3 s, 3×2 s, 6×1 s, 10×0.5 s.", "span", "small ink2"), 'data-opening="timelapse"');
      }
      if (eo.series_tag) {
        h += opt(F.series_tag, false, t("شارة «نخش في الموضوع الإقتصادي»", "Series tag «نخش في الموضوع الإقتصادي»", "b") + t("في الركن فوق على اليمين، الحلقة كلها.", "Top-right corner, the whole episode.", "span", "small ink2"), 'data-seriestag="1"');
      }
      h += "</div>";
      if (eo.ad) h += '<div class="grid g3" style="margin-top:12px">' + fileZone("ad", "film", "الإعلان (لو الحلقة فيها إعلان)", "The ad (if the episode has one)", true, F.ad) + "</div>";
    }
    if (pres) {
      h += '<div class="pv-sec">' + t("الناتج", "Output", "b", "label") + '</div><div class="grid g2">' +
        opt(F.output === "montage", false, t("المونتاج الكامل", "The full montage", "b") + t("التقطيع، وبعده المونتاج كله: لقطات، جرافيك، مزيكا، مؤثرات.", "The cut, then the whole montage: footage, graphics, music, effects.", "span", "small ink2"), 'data-output="montage"') +
        opt(F.output === "cut", false, t("بعد التقطيع بس", "Cut only", "b") + t("الفيديو بعد شيل الإعادات والسكوت والنَّفَس، من غير مونتاج.", "The video after removing retakes, silences and breaths, with no montage.", "span", "small ink2"), 'data-output="cut"') + "</div>";
    }
    h += "</div>";
    // 2 · raw material
    h += '<div class="card"><div class="card-h">' + t("٢ · الخام", "2 · Raw material", "h2", "h3") +
      t("الملفات بتتقري من مكانها على جهازك. الكليبات اللي بترفعها بتتنسخ لفولدر الحلقة على نفس الجهاز.", "Files are read where they are on this Mac. Clips you upload are copied into the episode's folder on this same computer.", "span", "small ink2") + "</div>" +
      '<div class="grid g3">' +
      (pres ? fileZone("video", "film", "الفيديو الخام", "Raw video", false, F.video) + fileZone("audio", "mic", "صوت المايك", "Mic audio", true, F.audio) +
        fileZone("script", "doc", "السكريبت", "Script", false, F.script)
        : fileZone("audio", "wave", "الصوت (أو فيديو ناخد صوته)", "The audio (or a video whose sound is used)", false, F.audio) +
          fileZone("script", "doc", "السكريبت المعتمد (Word أو نص)", "The approved script (Word or text)", true, F.script)) +
      clipsZone(F) + "</div>";
    if (!pres && !(F.script && F.script.ok)) {
      h += t("لو عندك السكريبت المعتمد، الكلام اللي بيظهر على الشاشة بيتكتب بنفس كتابته بدل ما يتاخد من التفريغ.",
             "With the approved script, the words shown on screen are spelled as the script writes them, not as the transcript heard them.", "p", "micro ink2 pv-note");
      if (P && P.options && P.options.subtitles)   /* owner's answer 6 of 2D: the intro's subtitles need the approved script */
        h += t("تنبيه: من غير السكريبت المعتمد، مقدمة الحلقة هتطلع من غير ترجمة (الترجمة بتتكتب من السكريبت بس).",
               "Note: without the approved script the intro will have no subtitles (they are written from the script only).", "p", "micro warnc pv-note");
    }
    if (scripts.length && !(F.script && F.script.ok)) {
      h += '<div class="row wrap pv-note" style="gap:8px">' + t("أو سكريبت معتمد من «كتابة السكريبت»:", "Or an approved script from the Script writer:", "span", "small ink2") +
        scripts.map(function (x, i) { return '<button class="chip line" data-script="' + i + '">' + esc(x.name) + (x.read_only ? " · " + t("اختبار", "test") : "") + "</button>"; }).join("") + "</div>";
    }
    h += "</div>";
    var cutOnly = pres && F.output === "cut";
    // 3 · sources, 4 · run mode
    h += '<div class="grid g2" style="gap:24px"><div class="card"><div class="card-h">' + t("٣ · المصادر", "3 · Sources", "h2", "h3") + '</div><div class="col" style="gap:10px">' +
      sourcesCard(eo) + "</div></div>" +
      '<div class="card"><div class="card-h">' + t("٤ · طريقة الشغل", "4 · Run mode", "h2", "h3") + '</div><div class="col" style="gap:10px">' +
      opt(F.run_mode !== "step" || cutOnly, false, '<span class="row" style="gap:6px">' + ic("moon", "sm") + t("تلقائي", "Automatic", "b") + "</span>" + t("يكمّل لوحده ويقرر بتوصيته — وكل قرار بيتسجّل وتشوفه في النتيجة.", "Continues alone and decides by its own recommendation — every choice is logged for the Result screen.", "span", "small ink2"), 'data-runmode="auto"') +
      opt(F.run_mode === "step" && !cutOnly, cutOnly, t("خطوة بخطوة بموافقتك", "Step by step, with your approval", "b") +
        (cutOnly ? t("مش متاحة مع «بعد التقطيع بس»: مفيش خطة مونتاج يسألك عليها.", "Not with «Cut only»: there is no montage plan to ask you about.", "span", "small ink2")
          : t("بعد خطة المونتاج، الوكيل بيسألك ٣–٦ أسئلة مترقّمة بتوصيته، والشغل يستنى إجاباتك.", "After the montage plan the agent asks you 3–6 numbered questions with its recommendation, and the run waits for your answers.", "span", "small ink2")), 'data-runmode="step"') + "</div></div></div>";
    // 5 · instructions
    h += '<div class="card"><div class="card-h">' + t("٥ · تعليمات قبل البدء", "5 · Instructions before starting", "h2", "h3") + t("اختياري", "Optional", "span", "small ink2") + "</div>" +
      '<textarea class="ta input" id="pv-instr" rows="4" style="height:auto;padding:12px" maxlength="4000" data-ar-ph="مثلاً: ركّز على أثر الأزمة على مصر، وماتستخدمش صور حرب." data-en-ph="For example: stress the effect on Egypt, and don\'t use war images." placeholder="' +
      esc(en() ? "For example: stress the effect on Egypt, and don't use war images." : "مثلاً: ركّز على أثر الأزمة على مصر، وماتستخدمش صور حرب.") + '">' + esc(F.instructions) + "</textarea>" +
      t("التعليمات بتوصل لخطة المونتاج زي ما هي، ومابتتخطاش القواعد الثابتة (الحقوق، البلد الصح…).", "Your words go to the montage plan as they are; they never override the standing rules (licences, the right country…).", "p", "micro ink2 pv-note") + "</div>";
    // summary + start
    var chips = [P ? esc(P.name) : t("من غير قناة", "No channel"), pres ? t("بمذيع", "With presenter") : t("صوت بس", "Audio only"), F.output === "cut" && pres ? t("بعد التقطيع بس", "Cut only") : t("المونتاج الكامل", "Full montage"),
                 srcLabel(eo), F.run_mode === "step" && !cutOnly ? t("خطوة بخطوة", "Step by step") : t("تلقائي", "Automatic")];
    if (okClips) chips.push(t(okClips + " كليب إضافي", okClips + " extra clip" + (okClips > 1 ? "s" : "")));
    h += '<div class="card"><div class="row between wrap" style="gap:12px"><div class="row wrap" style="gap:8px">' + chips.map(function (c) { return '<span class="chip">' + c + "</span>"; }).join("") + "</div>" +
      '<div style="text-align:end"><button class="btn btn-primary" id="pv-start"' + (miss.length || F.busy ? " disabled" : "") + ">" + ic("play", "sm flip") + t("ابدأ الشغل", "Start the work") + "</button>" +
      (miss.length ? '<div class="micro ink2" style="margin-top:6px">' + t("ناقص: " + miss.map(function (m) { return m[0]; }).join("، "), "Missing: " + miss.map(function (m) { return m[1]; }).join(", ")) + "</div>" : "") +
      (F.err ? '<div class="micro errc" style="margin-top:6px">' + esc(F.err) + "</div>" : "") + "</div></div></div>";
    return h;
  }
  function upload(file) {
    var F = S.form, key = "u" + rid().slice(0, 8);
    F.uploads[key] = { key: key, name: file.name, bytes: file.size, busy: true, pct: 0 };
    render();
    var x = new XMLHttpRequest();
    x.open("PUT", "/api/upload?draft=" + F.draft + "&name=" + encodeURIComponent(file.name));
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = function (ev) {
      if (!ev.lengthComputable) return;
      F.uploads[key].pct = Math.round(ev.loaded / ev.total * 100);
      var el = document.querySelector('[data-uppct="' + key + '"]');          /* in place: no redraw while you type */
      if (el) el.textContent = F.uploads[key].pct + "%";
    };
    x.onload = function () {
      var d = {};
      try { d = JSON.parse(x.responseText); } catch (e) {}
      F.uploads[key] = x.status === 200 ? { key: key, name: file.name, bytes: d.bytes, seconds: d.seconds, ok: true, uploaded: d.uploaded }
        : { key: key, name: file.name, ok: false, why: d.error || ("HTTP " + x.status) };
      render();
    };
    x.onerror = function () { F.uploads[key] = { key: key, name: file.name, ok: false, why: "the upload stopped" }; render(); };
    x.send(file);
  }
  function pickFiles(kind) {
    var F = S.form;
    F.busy = true; F.err = null; render();
    post("/api/pick", { kind: kind === "script" && F.type !== "presenter" ? "script_audio" : kind }).then(function (d) {
      F.busy = false;
      if (d.error) { F.err = d.error; render(); return; }      /* said, never taken for «cancelled» */
      var fs = d.files || [];
      if (kind === "clips") {
        fs.forEach(function (f) { f.key = "p" + rid().slice(0, 8); if (f.ok && !f.video) { f.ok = false; f.why = "no video in this file"; } F.clips.push(f); });
      } else if (fs.length) {
        var f = fs[0];
        if (f.ok && (kind === "video" || kind === "ad") && !f.video) { f.ok = false; f.why = "this file has no video"; }
        if (f.ok && kind === "audio" && !f.audio) { f.ok = false; f.why = "this file has no sound"; }
        F[kind] = f;
      }
      render();
    }).catch(function () { F.busy = false; F.err = "the panel did not answer"; render(); });
  }
  function startEpisode() {
    var F = S.form, pres = F.type === "presenter";
    F.busy = true; F.err = null; render();
    var eo2 = ((S.profiles || []).filter(function (x) { return x.slug === F.profile; })[0] || {}).options || {};
    post("/api/new", { profile: F.profile, type: F.type, title: F.title, sources: F.sources || "both",
                       ad: eo2.ad && F.ad && F.ad.ok ? F.ad.path : null, series_tag: !!(eo2.series_tag && F.series_tag),
                       opening: (eo2.openings || []).length > 1 ? (F.opening || null) : null, output: pres ? F.output : "montage", run_mode: (pres && F.output === "cut") ? "auto" : F.run_mode, instructions: F.instructions,
                       video: pres && F.video ? F.video.path : null, audio: F.audio && F.audio.ok ? F.audio.path : null,
                       script: F.script && F.script.ok ? F.script.path : null, script_from: F.script && F.script.from || null, draft: F.draft,
                       clips: F.clips.filter(function (c) { return c.ok; }).map(function (c) { return c.path; }) })
      .then(function (d) {
        F.busy = false;
        if (d.error) { F.err = d.error; render(); return; }
        S.form = null;
        location.hash = "#/progress/" + encodeURIComponent(d.id);
      }).catch(function () { F.busy = false; F.err = "the panel did not answer"; render(); });
  }
  /* ---------------------------------------------------------------- render and route */
  function render() {
    var view = document.getElementById("view");
    if (!view) return;
    setNav();
    setBrain();
    if (S.route === "new") {
      view.innerHTML = newForm();
    } else if (S.route === "progress") {
      view.innerHTML = '<div class="pv-grid"><div class="col" style="gap:24px">' + detail(S.detail) + '</div><aside class="col pv-side" style="gap:12px">' + sideList() + "</aside></div>";
      var d = document.getElementById("pv-log");
      if (d) d.addEventListener("toggle", function () { S.logOpen = d.open; });
      var tl = document.getElementById("pv-tests");
      if (tl) tl.addEventListener("toggle", function () { S.testsOpen = tl.open; });
    } else if (S.route === "costs") {
      view.innerHTML = costs() + costsMore();
    } else if (S.route === "paid") {
      view.innerHTML = paidUsage();
    } else if (S.route === "rules") {
      view.innerHTML = rulesView();
    } else if (S.route === "training") {
      view.innerHTML = trainingView();
    } else if (S.route === "channels") {
      view.innerHTML = channelsView();
    } else if (S.route === "integrations") {
      view.innerHTML = integrations();
    } else if (S.route === "result") {
      view.innerHTML = resultView();
    } else if (S.route === "script") {
      view.innerHTML = scriptView();
    } else if (S.route === "style") {
      view.innerHTML = styleView();
    } else {
      view.innerHTML = later(S.route);
    }
    icons(view);
    if (en()) M.setLang(true);
  }
  function parse() {
    var h = (location.hash || "#/progress").slice(2).split("/");
    S.route = CRUMB[h[0]] ? h[0] : "progress";
    S.sel = S.route === "progress" && h[1] ? decodeURIComponent(h.slice(1).join("/")) : S.sel;
    S.rsel = S.route === "result" ? (h[1] ? decodeURIComponent(h.slice(1).join("/")) : null) : S.rsel;
    if (S.route === "script") S.ssel = h[1] ? decodeURIComponent(h.slice(1).join("/")) : null;
    if (S.route === "channels") S.chsel = h[1] ? decodeURIComponent(h[1]) : (S.chsel || "general");
    if (S.route === "style") S.stsel = h[1] ? decodeURIComponent(h[1]) : (S.stsel || null);
  }
  function pickDefault() {
    if (S.sel && S.episodes.some(function (e) { return e.id === S.sel; })) return;
    var all = S.episodes.slice().sort(function (a, b) {
      return (b.scope === "projects") - (a.scope === "projects") || String(b.updated || "").localeCompare(String(a.updated || ""));
    });
    S.sel = all.length ? all[0].id : null;
  }
  function refresh() {
    return api("/api/episodes").then(function (d) {
      S.episodes = d.episodes || [];
      pickDefault();
      if (S.route === "progress" && Date.now() - (S.trashAt || 0) > 30000) { S.trashAt = Date.now(); loadTrash(); }
      if (S.route === "progress" && S.sel) return api("/api/episode?id=" + encodeURIComponent(S.sel)).then(function (x) { S.detail = x.error && !x.name ? null : x; });
      S.detail = null;
    }).then(function () {
      if (S.route === "new") setNav();          /* the form is never redrawn under your hands; only the nav badge */
      else if (S.route === "integrations" && S.so && S.so.open) setNav();   /* nor the typed sign-out confirmation */
      else if (typing()) setNav();
      else if (S.route === "result") { setNav(); resultLoad(); resultPoll(); }
      else if (S.route === "script") { if (S.ssel) { setNav(); scriptLoad(); } else render(); }
      else if (S.route === "rules") { setNav(); if (!S.rb) rulesLoad(); }
      else if (S.route === "training") { setNav(); if (!S.tl) trainingLoad(); }
      else if (S.route === "channels") { setNav(); if (!S.chv) channelsLoad(); }
      else if (S.route === "style") { setNav(); if (S.stv && S.stv.checking) { var cs = S.stv.slug; api("/api/style?slug=" + encodeURIComponent(cs)).then(function (x) {
        if (S.stv && S.stv.slug === cs && x.checking !== S.stv.checking) { S.stv = x; if (!typing()) render(); } }); } else styleLoad(); }
      else render();
      live();
    }).catch(function () {});
  }
  /* ---------------------------------------------------------------- what you do on the page */
  document.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("[data-profile],[data-opening],[data-seriestag],[data-sources],[data-type],[data-output],[data-runmode],[data-pick],[data-clear],[data-rmclip],[data-script],#pv-start,[data-stop],[data-run]") : null;
    if (!el) return;
    var F = S.form;
    if (el.hasAttribute("data-profile")) { F.profile = el.getAttribute("data-profile"); F.opening = null; F.series_tag = false; F.ad = null; F.sources = "both"; render(); }
    else if (el.hasAttribute("data-opening")) { F.opening = el.getAttribute("data-opening"); render(); }
    else if (el.hasAttribute("data-seriestag")) { F.series_tag = !F.series_tag; render(); }
    else if (el.hasAttribute("data-sources")) { F.sources = el.getAttribute("data-sources"); render(); }
    else if (el.hasAttribute("data-type")) { if (el.disabled) return; F.type = el.getAttribute("data-type"); if (F.type !== "presenter") F.output = "montage"; render(); }
    else if (el.hasAttribute("data-output")) { F.output = el.getAttribute("data-output"); render(); }
    else if (el.hasAttribute("data-runmode")) { if (el.disabled || el.classList.contains("dis")) return; F.run_mode = el.getAttribute("data-runmode"); render(); }
    else if (el.hasAttribute("data-pick")) { ev.preventDefault(); if (!F.busy) pickFiles(el.getAttribute("data-pick")); }
    else if (el.hasAttribute("data-clear")) { F[el.getAttribute("data-clear")] = null; render(); }
    else if (el.hasAttribute("data-script")) { var x = S.scripts[+el.getAttribute("data-script")]; F.script = { ok: true, name: x.name + " (script.docx)", path: x.path, bytes: 0, from: x.read_only ? null : x.id };
      if (x.profile) F.profile = x.profile; if (x.type) F.type = x.type; render(); }
    else if (el.hasAttribute("data-rmclip")) {
      var k = el.getAttribute("data-rmclip");
      if (F.uploads[k]) { if (F.uploads[k].uploaded) post("/api/upload_remove", { draft: F.draft, name: F.uploads[k].uploaded }); delete F.uploads[k]; }
      F.clips = F.clips.filter(function (c) { return c.key !== k; });
      render();
    }
    else if (el.id === "pv-start") { if (!el.disabled) startEpisode(); }
    else if (el.hasAttribute("data-stop")) {
      var id = el.getAttribute("data-stop");
      if (S.stopArm !== id) { S.stopArm = id; render(); setTimeout(function () { if (S.stopArm === id) { S.stopArm = null; render(); } }, 5000); return; }
      S.stopArm = null; S.actMsg = { ar: "بوقّف الشغل…", en: "Stopping the run…" }; render();
      post("/api/stop", { id: id }).then(function (d) {
        S.actMsg = d.error || d.refused ? { ar: "ماقدرتش أوقّفه: " + (d.error || d.refused), en: "Could not stop it: " + (d.error || d.refused), err: true }
          : { ar: "وقفته. الخطوات اللي خلصت فضلت زي ما هي، و«كمّل الشغل» يكمّل من عندها.", en: "Stopped. Finished steps stay as they are; «Resume» continues from there." };
        refresh();
      });
    }
    else if (el.hasAttribute("data-run")) {
      S.actMsg = { ar: "ببدأ الشغل…", en: "Starting the run…" }; render();
      post("/api/run", { id: el.getAttribute("data-run") }).then(function (d) {
        S.actMsg = d.error || d.refused ? { ar: "ماقدرتش أبدأ: " + (d.error || d.refused), en: "Could not start: " + (d.error || d.refused), err: true } : null;
        refresh();
      });
    }
  });
  document.addEventListener("input", function (ev) {
    if (!S.form) return;
    if (ev.target.id === "pv-title") { S.form.title = ev.target.value; refreshStart(); }
    if (ev.target.id === "pv-instr") S.form.instructions = ev.target.value;
  });
  function refreshStart() {                     /* the start button and its reason, without redrawing the form */
    var b = document.getElementById("pv-start"), fresh = document.createElement("div");
    if (!b) return;
    fresh.innerHTML = newForm();
    var nb = fresh.querySelector("#pv-start");
    b.parentElement.replaceWith(nb.parentElement);
    icons(document.getElementById("pv-start").parentElement);
    if (en()) M.setLang(true);
  }
  document.addEventListener("change", function (ev) {
    if (ev.target.id === "pv-files" && S.form) { Array.prototype.forEach.call(ev.target.files, upload); ev.target.value = ""; }
  });
  document.addEventListener("dragover", function (ev) { if (S.route === "new") ev.preventDefault(); });
  document.addEventListener("drop", function (ev) {
    if (S.route !== "new" || !S.form) return;
    ev.preventDefault();
    Array.prototype.forEach.call(ev.dataTransfer.files || [], upload);
  });

  /* ---------------------------------------------------------------- start */
  var saved = store("monteer.theme");
  if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  M.mount({ shell: { active: "progress", crumb: CRUMB.progress[0], crumbEn: CRUMB.progress[1] } });
  if (store("monteer.lang") === "en") M.setLang(true);
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("[data-act]");
    if (a) setTimeout(function () {
      store("monteer.lang", document.documentElement.lang);
      store("monteer.theme", document.documentElement.getAttribute("data-theme"));
    }, 0);
  });
  window.addEventListener("hashchange", function () { parse(); S.actMsg = null; S.resMsg = null; S.swMsg = null; if (S.route === "new" || S.route === "script") loadScripts();
    if (["result", "script", "style", "rules", "training", "channels"].indexOf(S.route) >= 0) render(); refresh(); });
  function loadScripts() {
    api("/api/scripts").then(function (d) { S.scripts = d.scripts || []; if (S.route === "new") render(); }).catch(function () {});
    api("/api/profiles").then(function (d) { S.profiles = d.profiles || []; if (S.route === "new" || (S.route === "script" && !S.ssel)) render(); }).catch(function () {});
  }
  parse();
  if (S.route === "new" || S.route === "script") loadScripts();
  api("/api/state").then(function (s) { S.state = s; render(); }).catch(function () {});
  refresh();
  setInterval(refresh, 5000);                    /* the list every 5 s; the episode on screen also has its live stream (phase 3) */
})();
