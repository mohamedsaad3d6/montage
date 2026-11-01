/* The design's own bundle (monteer_design/monteer-design-source/components/bundle.js), with three changes for the local
   panel: the logos come from /static, the font from the panel itself, and the nav items are real links. */
/* @ds-bundle: {"format":4,"namespace":"Monteer","components":[]} */
(function () {
  var LOGO = "/static/monteer-mark.svg";          /* the panel: local files (was the design tool's blob) */
  var LOGO_LIGHT = "/static/monteer-mark-light.svg";
  var IC = {
    upload: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
    download: '<path d="M12 4v12M6 10l6 6 6-6M4 20h16"/>',
    play: '<path d="M7 5l12 7-12 7z" fill="currentColor" stroke="none"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    pause: '<path d="M9 6v12M15 6v12"/>',
    alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    retry: '<path d="M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4"/>',
    film: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3 9h18M3 15h18M8 5v4M16 5v4M8 15v4M16 15v4"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    wave: '<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2"/>',
    doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    clip: '<path d="M15 7l-6.5 6.5a2.5 2.5 0 0 0 3.5 3.5L19 10a4.5 4.5 0 0 0-6.4-6.4L6 10.2a6.5 6.5 0 0 0 9.2 9.2L20 14.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
    pen: '<path d="M4 20l4-1L19 8l-3-3L5 16z"/><path d="M14 7l3 3"/>',
    book: '<path d="M4 5.5C4 4.7 4.7 4 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM20 5.5c0-.8-.7-1.5-1.5-1.5H13v16h5.5c.8 0 1.5-.7 1.5-1.5z"/>',
    rules: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    coins: '<ellipse cx="12" cy="7" rx="7" ry="3"/><path d="M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5"/>',
    plug: '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4"/>',
    spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
    report: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/>',
    send: '<path d="M4 12l16-8-6 16-3-7z"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
    image: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 8"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    map: '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    archive: '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9M10 13h4"/>',
    news: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h4M7 16h4M14 12h3v4h-3z"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    home: '<path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
    chev: '<path d="M15 6l-6 6 6 6"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    ear: '<path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-5.5 1.6"/><path d="M10 9.5a2 2 0 0 1 4 0"/>',
    split: '<path d="M6 3v6a6 6 0 0 0 6 6 6 6 0 0 1 6 6M18 3v6"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.5 7.5L20 18M8.5 16.5L20 6"/>',
    youtube: '<rect x="2.5" y="5.5" width="19" height="13" rx="4"/><path d="M10 9.5v5l4.5-2.5z" fill="currentColor"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H10l2 2.5h7.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
    laptop: '<rect x="4" y="5" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
    loader: '<path d="M12 3a9 9 0 1 0 9 9" />',
    filter: '<path d="M4 5h16l-6 8v6l-4-2v-4z"/>',
    hash: '<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>'
  };
  function icon(name, cls) {
    return '<span class="ic ' + (cls || '') + '"><svg viewBox="0 0 24 24" aria-hidden="true">' + (IC[name] || '') + '</svg></span>';
  }

  var NAV = [
    ["new", "plus", "حلقة جديدة", "New episode"],
    ["progress", "film", "المتابعة", "Progress"],
    ["result", "play", "النتيجة", "Result"],
    ["script", "pen", "كتابة السكريبت", "Script writer"],
    ["h", "", "التعلّم", "Learning"],
    ["training", "book", "مكتبة التدريب", "Training library"],
    ["rules", "rules", "الدستور", "Rulebook"],
    ["style", "doc", "دليل أسلوب القناة", "Channel style guide"],
    ["channels", "list", "القنوات", "Channels"],
    ["h", "", "الحساب", "Account"],
    ["costs", "coins", "التكاليف", "Costs"],
    ["paid", "coins", "استخدام الخدمات المدفوعة", "Paid services use"],
    ["integrations", "plug", "الربط بالخدمات", "Integrations"]
  ];

  function shell(root, o) {
    o = o || {};
    var content = root.innerHTML;
    var nav = NAV.map(function (n) {
      if (n[0] === "h") return '<div class="nav-h" data-en="' + n[3] + '">' + n[2] + '</div>';
      return '<a href="#/' + n[0] + '" data-nav="' + n[0] + '" class="' + (o.active === n[0] ? 'on' : '') + '">' + icon(n[1]) + '<span data-en="' + n[3] + '">' + n[2] + '</span>' + (n[4] ? '<span class="badge num">' + n[4] + '</span>' : '') + '</a>';
    }).join("");
    var brain = o.brain === "limit"
      ? '<div class="row" style="gap:6px"><span class="dot warnc" style="color:var(--warning)"></span><b data-en="Claude · limit reached">Claude · وصل للحد</b></div><div class="ink2" style="margin-top:4px" data-en="Resumes on its own at [time]">هيكمل لوحده الساعة [الوقت]</div>'
      : o.brain === "local"
      ? '<div class="row" style="gap:6px"><span class="dot" style="color:var(--warning)"></span><b data-en="Local model only">النموذج المحلي بس</b></div><div class="ink2" style="margin-top:4px" data-en="Claude is not logged in">Claude مش مسجّل دخول</div>'
      : '<div class="row" style="gap:6px"><span class="dot" style="color:var(--success)"></span><b data-en="Brain: your Claude">العقل: Claude بتاعك</b></div><div class="ink2" style="margin-top:4px" data-en="Included in subscription · no API key">ضمن اشتراكك · من غير مفتاح API</div>';
    root.innerHTML =
      '<div class="app"><aside class="side">' +
      '<div class="brand"><img class="mark" alt="" data-logo><div><b data-en="Monteer">مونتير</b><small data-en="AI video editor">مونتير الفيديو الذكي</small></div></div>' +
      '<nav class="nav">' + nav + '</nav>' +
      '<div class="brain-mini">' + brain + '</div>' +
      '</aside><main class="main"><header class="topbar">' +
      '<div class="grow"><div class="crumb" data-en="' + (o.crumbEn || "") + '">' + (o.crumb || "") + '</div></div>' +
      (o.topExtra || "") +
      '<button class="icon-btn" data-act="lang" title="EN / ع">EN</button>' +
      '<button class="icon-btn" data-act="theme" title="Theme">' + icon("sun", "sm") + '</button>' +
      '<span class="avatar">ش</span>' +
      '</header><div class="page">' + content + '</div></main></div>';
  }

  function setLang(en) {
    var h = document.documentElement;
    h.lang = en ? "en" : "ar";
    h.dir = en ? "ltr" : "rtl";
    document.querySelectorAll("[data-en]").forEach(function (n) {
      if (n.dataset.ar == null) n.dataset.ar = n.textContent;
      n.textContent = en ? n.dataset.en : n.dataset.ar;
    });
    document.querySelectorAll("[data-en-ph]").forEach(function (n) {
      if (n.dataset.arPh == null) n.dataset.arPh = n.placeholder;
      n.placeholder = en ? n.dataset.enPh : n.dataset.arPh;
    });
    document.querySelectorAll('[data-act="lang"]').forEach(function (b) { b.textContent = en ? "ع" : "EN"; });
  }
  function syncTheme() {
    var dark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";
    document.querySelectorAll("[data-logo]").forEach(function (i) { i.src = dark ? LOGO : LOGO_LIGHT; });
    document.querySelectorAll('[data-act="theme"]').forEach(function (b) { b.innerHTML = icon(dark ? "sun" : "moon", "sm"); });
  }

  function mount(o) {
    o = o || {};
    var root = document.getElementById("app") || document.body.firstElementChild;
    if (o.shell && root) shell(root, o.shell);
    document.documentElement.dir = "rtl";
    document.documentElement.lang = "ar";
    if (!document.documentElement.getAttribute("data-theme")) document.documentElement.setAttribute("data-theme", "dark");
    document.querySelectorAll("i[data-ic]").forEach(function (n) {
      n.outerHTML = icon(n.getAttribute("data-ic"), n.className);
    });
    syncTheme();
    new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("[data-act],[data-tc],[data-pick],.seg button,.opt,.toggle,.fact") : null;
    if (!t) return;
    var a = t.getAttribute("data-act");
    if (a === "lang") { e.preventDefault(); setLang(document.documentElement.lang !== "en"); return; }
    if (a === "theme") {
      e.preventDefault();
      var h = document.documentElement;
      h.setAttribute("data-theme", (h.getAttribute("data-theme") || "dark") === "dark" ? "light" : "dark");
      return;
    }
    if (t.hasAttribute("data-tc")) {
      var p = parseFloat(t.getAttribute("data-tc")), tot = parseFloat(t.getAttribute("data-total") || "1235");
      document.querySelectorAll("[data-playhead]").forEach(function (ph) { ph.style.left = (p / tot * 100) + "%"; });
      document.querySelectorAll("[data-playfill]").forEach(function (ph) { ph.style.width = (p / tot * 100) + "%"; });
      document.querySelectorAll("[data-playtime]").forEach(function (x) { x.textContent = fmt(p); });
      return;
    }
    if (t.classList.contains("toggle")) { t.classList.toggle("on"); return; }
    if (t.classList.contains("fact")) { t.classList.toggle("show"); return; }
    var grp = t.parentElement;
    if (t.matches(".seg button") || t.classList.contains("opt")) {
      grp.querySelectorAll(":scope > .on").forEach(function (x) { x.classList.remove("on"); });
      t.classList.add("on");
    }
  });
  function fmt(s) { s = Math.round(s); var m = Math.floor(s / 60), r = s % 60; return m + ":" + (r < 10 ? "0" : "") + r; }

  /* Cairo is served by the panel from this Mac (monteer_data/assets/fonts): no request leaves the computer */
  window.Monteer = { mount: mount, shell: shell, icon: icon, setLang: setLang, fmt: fmt, LOGO: LOGO, LOGO_LIGHT: LOGO_LIGHT };
})();
