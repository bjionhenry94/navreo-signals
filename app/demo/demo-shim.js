/* Demo shim: serves recorded API responses so the real Navreo pages run on fixed data.
   Injected first in <head>. window.__FX_INDEX maps request keys to fixture files. */
(function () {
  var IDX = window.__FX_INDEX || {};
  var OVR = window.__FX_OVR || {};   // page-scoped fixtures (fx-deliv-index.js) win over the shared index
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
    if (OVR[k]) return OVR[k];
    if (IDX[k]) return IDX[k];
    var p = pathOnly(k);
    // same path, ignore query (live-status ids, queue filters, thread batches)
    var best = null;
    for (var kk in IDX) { if (pathOnly(kk) === p) { if (!best || kk.length > best.length) best = kk; } }
    if (best) return IDX[best];
    return null;
  }
  /* Keep the setter inbox "live": each conversation's reply lands a realistic, un-rounded
     few minutes to a few hours before page load (never over a day). Every timestamp on the
     row and in its thread shifts by the same amount so the story stays consistent. */
  var OFFS = [14, 23, 37, 52, 68, 86, 113, 137, 164, 211, 252, 306, 408, 503, 19, 31, 46, 71, 97, 128, 157, 193, 238, 284, 331, 377, 432, 486, 547, 612, 689, 754, 823, 901, 987, 1063, 1149, 1236, 1318];
  var DELTA = {}, NEXT = 0, T0 = Date.now();
  var ISO = /"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"/g;
  function shiftStr(str, d) {
    return str.replace(ISO, function (m, v) { var t = Date.parse(v); return isNaN(t) ? m : JSON.stringify(new Date(t + d).toISOString()); });
  }
  function retime(k, t) {
    var p = pathOnly(k);
    try {
      if (p === "/api/setter/queue" || p === "/api/setter/subsequence/unresolved") {
        var d = JSON.parse(t);
        (d.rows || []).forEach(function (r) {
          var id = String(r.id);
          if (DELTA[id] == null) {
            var rep = Date.parse(r.replied_at || r.sent_at || r.created_at);
            if (isNaN(rep)) return;
            var off = OFFS[NEXT++ % OFFS.length] * 60000 + (r.id % 53) * 1000;
            DELTA[id] = (T0 - off) - rep;
          }
          var nr = JSON.parse(shiftStr(JSON.stringify(r), DELTA[id]));
          Object.keys(nr).forEach(function (kk) { r[kk] = nr[kk]; });
        });
        return JSON.stringify(d);
      }
      if (p === "/api/setter/thread/batch") {
        var b = JSON.parse(t), th = b.threads || {};
        Object.keys(th).forEach(function (id) { if (DELTA[id] != null) th[id] = JSON.parse(shiftStr(JSON.stringify(th[id]), DELTA[id])); });
        return JSON.stringify(b);
      }
    } catch (e) {}
    return t;
  }
  /* Keep a page's recording "current": when the page sets __FX_ANCHOR (the capture
     date), every date moves forward so the recording ends today. Day-aligned series
     move by whole weeks so weekend lulls stay on weekends; timestamps that would land
     in the future read as a few minutes ago. */
  var SHIFT = (function () {
    if (!window.__FX_ANCHOR) return 0;
    var a = Date.parse(window.__FX_ANCHOR + "T00:00:00Z"), n = new Date();
    var t = Date.UTC(n.getFullYear(), n.getMonth(), n.getDate());
    return Math.max(0, Math.round((t - a) / 864e5));
  })();
  var DATE = /"(\d{4}-\d{2}-\d{2})((?:T[0-9:.]+)?(?:Z|[+-]\d{2}:\d{2})?)"/g;
  function realign(o, s) {
    if (Array.isArray(o)) { o.forEach(function (x) { realign(x, s); }); return; }
    if (!o || typeof o !== "object") return;
    var d = o.days;
    if (Array.isArray(d) && d.length && /^\d{4}-\d{2}-\d{2}/.test(String(d[0]))) {
      var N = d.length;
      (function walk(x) {
        if (Array.isArray(x)) {
          if (x !== d && x.length === N && typeof x[0] !== "string") {
            var old = x.slice();
            for (var i = 0; i < N; i++) { var j = i >= s ? i - s : i - s + 7; x[i] = j < N ? old[j] : 0; }
          } else x.forEach(walk);
        } else if (x && typeof x === "object") for (var kk in x) if (x[kk] !== d) walk(x[kk]);
      })(o);
      return;
    }
    for (var k in o) realign(o[k], s);
  }
  function freshen(k, t) {
    var p = pathOnly(k);
    if (!SHIFT || /^\/api\/setter\//.test(p)) return t;
    var s = (7 * Math.ceil(SHIFT / 7) - SHIFT) % 7;
    if (s) { try { var o = JSON.parse(t); realign(o, s); t = JSON.stringify(o); } catch (e) {} }
    var now = Date.now();
    return t.replace(DATE, function (m, day, rest) {
      var ms = Date.parse(day + "T00:00:00Z");
      if (isNaN(ms)) return m;
      var nd = new Date(ms + SHIFT * 864e5).toISOString().slice(0, 10);
      if (!rest) return '"' + nd + '"';
      var v = Date.parse(nd + (rest.charAt(0) === "T" ? rest : "T00:00:00" + rest));
      if (isNaN(v)) return '"' + nd + rest + '"';
      if (v > now) { var h = 0; for (var i = 0; i < m.length; i++) h = (h * 31 + m.charCodeAt(i)) % 997; v = now - (6 + h % 50) * 60000; }
      return JSON.stringify(new Date(v).toISOString());
    });
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
    if (method === "GET" && pathOnly(k) === "/api/setter/thread") {
      // Single-thread refresh: serve it from the recorded batch so the demo never
      // shows a "couldn't reach the mail server" line.
      var tid = decodeURIComponent((k.split("id=")[1] || "").split("&")[0]);
      var bf = resolve("/api/setter/thread/batch");
      if (!cache[bf]) cache[bf] = realFetch(BASE + bf + "?v=" + (window.__FX_VERSION || "2"), { cache: "no-cache" }).then(function (r) { return r.text(); });
      return cache[bf].then(function (t) {
        var th = []; try { th = (JSON.parse(retime("/api/setter/thread/batch", t)).threads || {})[tid] || []; } catch (e) {}
        return jsonResponse(JSON.stringify({ thread: th, stale: false }));
      });
    }
    if (method === "GET" && pathOnly(k) === "/api/setter/lead-contact") {
      // Per-prospect Profile data (role, company, size, HQ), keyed by queue row id.
      var lid = (k.split("id=")[1] || "").split("&")[0];
      var lf = "fx/lead-contact.json";
      if (!cache[lf]) cache[lf] = realFetch(BASE + lf + "?v=" + (window.__FX_VERSION || "2"), { cache: "no-cache" }).then(function (r) { return r.text(); });
      return cache[lf].then(function (t) { var m = {}; try { m = JSON.parse(t); } catch (e) {} return jsonResponse(JSON.stringify(m[decodeURIComponent(lid)] || {})); });
    }
    if (method === "GET") {
      var file = resolve(k);
      if (file) {
        if (!cache[file]) cache[file] = realFetch(BASE + file + "?v=" + (window.__FX_VERSION || "2"), { cache: "no-cache" }).then(function (r) { return r.text(); });
        return cache[file].then(function (t) { return jsonResponse(freshen(k, retime(k, t))); });
      }
    }
    return Promise.resolve(jsonResponse(synth(k, method)));
  };
  if (navigator.sendBeacon) navigator.sendBeacon = function () { return true; };
  // Never bounce to login.
  var origAssign = window.location.assign;
  Object.defineProperty(window, "__demo", { value: true });
})();
