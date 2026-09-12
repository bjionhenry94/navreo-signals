/* Demo shim: serves recorded API responses so the real Navreo pages run on fixed data.
   Injected first in <head>. window.__FX_INDEX maps request keys to fixture files. */
(function () {
  var IDX = window.__FX_INDEX || {};
  var BASE = (function () {
    var s = document.currentScript && document.currentScript.src;
    if (!s) return "";
    return s.replace(/[^\/]*$/, "");
  })();
  var realFetch = window.fetch.bind(window);
  var cache = {};

  function key(u) {
    try { u = new URL(u, location.href); } catch (e) { return String(u); }
    var p = u.pathname.replace(/^\/app(?=\/api\/)/, "");
    var sp = u.searchParams; sp.delete("share"); sp.delete("_"); sp.delete("t");
    var q = sp.toString();
    return p + (q ? "?" + q : "");
  }
  function pathOnly(k) { return k.split("?")[0]; }
  function resolve(k) {
    if (IDX[k]) return IDX[k];
    var p = pathOnly(k);
    // same path, ignore query (live-status ids, queue filters, thread batches)
    var best = null;
    for (var kk in IDX) { if (pathOnly(kk) === p) { if (!best || kk.length > best.length) best = kk; } }
    if (best) return IDX[best];
    return null;
  }
  function jsonResponse(text, status) {
    return new Response(text, { status: status || 200, headers: { "Content-Type": "application/json" } });
  }
  function synth(k, method) {
    var p = pathOnly(k);
    if (method !== "GET") {
      if (p === "/api/report/share" && window.__FX_REPORT) return JSON.stringify({ ok: true, url: window.__FX_REPORT.url, client: "Navreo", start: "2026-08-31", end: "2026-09-06" });
      if (/\/api\/setter\/queue\/action/.test(p)) return JSON.stringify({ ok: true, status: "sent", sent_at: new Date().toISOString() });
      if (/\/api\/setter\/queue\/redraft/.test(p)) return JSON.stringify({ ok: true, job: "demo", status: "done" });
      if (/\/api\/onboarding\/draft/.test(p)) return JSON.stringify({ ok: true });
      return JSON.stringify({ ok: true, demo: true });
    }
    if (/\/api\/jobs$/.test(p)) return JSON.stringify({ jobs: [] });
    if (/\/api\/version$/.test(p)) return JSON.stringify({ commit: "demo", server_instance: "demo", uptime_seconds: 3600 });
    if (/\/api\/auth\/me$/.test(p)) return JSON.stringify({ email: "demo@navreo.ai", name: "Demo" });
    if (/status$/.test(p)) return JSON.stringify({ ok: true, running: false, status: "idle", done: true });
    if (/\/api\/notifications/.test(p)) return JSON.stringify({ items: [], rows: [], notifications: [] });
    if (/\/api\/setter\/subsequence\/unresolved/.test(p)) return JSON.stringify({ rows: [], items: [] });
    if (/\/api\/setter\/queue\/row/.test(p)) return JSON.stringify({});
    if (/\/api\/campaigns\/\d+\/variant-action-status/.test(p)) return JSON.stringify({ status: "done" });
    console.warn("[demo-shim] no fixture for", k);
    return JSON.stringify({});
  }
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    var k = key(url);
    if (!/^\/api\//.test(pathOnly(k))) return realFetch(input, init);
    if (method === "GET") {
      var file = resolve(k);
      if (file) {
        if (!cache[file]) cache[file] = realFetch(BASE + file, { cache: "force-cache" }).then(function (r) { return r.text(); });
        return cache[file].then(function (t) { return jsonResponse(t); });
      }
    }
    return Promise.resolve(jsonResponse(synth(k, method)));
  };
  if (navigator.sendBeacon) navigator.sendBeacon = function () { return true; };
  // Never bounce to login.
  var origAssign = window.location.assign;
  Object.defineProperty(window, "__demo", { value: true });
})();
