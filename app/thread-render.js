/* Portal thread renderer (owner founding case 2026-08-17).
   ONE source of truth for how a training card's email thread is drawn -
   included by app/setter-train.html (the live client portal) AND by the
   throwaway round-feedback UI, so what the trainer verdicts is literally
   the markup clients see. Self-contained: own escaping, own date
   formatting, injects its own styles once. Expects case.thread as
   [{who: "us"|"lead", subject, body, at, from_name}] (bodies already
   cleaned server-side by clean_body) plus case.thread_earlier (count of
   older emails cut by the <=4 rule). */

(function () {
  "use strict";

  /* Design language (owner ruling, thread round 1 2026-08-17): match the
     tool as seen on Mailboxes/Campaigns — white cards on the cream page,
     thin neutral borders, small-caps gray labels like table headers, and
     orange ONLY as a thin accent (the to-do card's left bar), never as a
     background fill. Us/lead separation comes from alignment + label, not
     from color blocks. */
  var THREAD_CSS = [
    ".th-wrap { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }",
    ".th-subject { font-size: 13px; font-weight: 600; color: var(--ink, #1F1D1A); margin-bottom: 2px; }",
    ".th-earlier { font-size: 11.5px; color: var(--ink-3, #8A8578); text-align: center; padding: 2px 0; }",
    ".th-email { border: 1px solid var(--line, #E7E5E0); border-radius: 10px; padding: 10px 14px; max-width: 88%; box-sizing: border-box; background: var(--card, #fff); }",
    ".th-email.us { align-self: flex-start; background: var(--bg-sunken, #F7F7F6); }",
    ".th-email.lead { align-self: flex-end; }",
    ".th-email.latest { border-left: 3px solid var(--orange, #E56A1F); }",
    ".th-label { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-3, #8A8578); margin-bottom: 5px; display: flex; gap: 6px; align-items: baseline; }",
    ".th-label .th-when { font-weight: 400; text-transform: none; letter-spacing: 0; }",
    ".th-body { font-size: 13px; line-height: 1.55; color: var(--ink, #1F1D1A); white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow-y: auto; }",
  ].join("\n");

  function ensureStyles() {
    if (document.getElementById("thread-render-style")) return;
    var s = document.createElement("style");
    s.id = "thread-render-style";
    s.textContent = THREAD_CSS;
    document.head.appendChild(s);
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function shortWhen(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.getDate() + " " + MONTHS[d.getMonth()];
  }

  /* The thread's one subject: the first non-empty subject, stripped of
     leading Re:/Fwd: chains - shown once at the top, never repeated per
     email (Re: continuity is implied by the thread itself). */
  function threadSubject(thread) {
    for (var i = 0; i < thread.length; i++) {
      var s = String(thread[i].subject || "").replace(/^\s*((re|fwd?)\s*:\s*)+/i, "").trim();
      if (s) return s;
    }
    return "";
  }

  /* Renders one case's thread. Returns HTML string; empty string when the
     case has no usable thread (callers keep their legacy layout as the
     fallback for pre-thread cases). */
  function renderThreadHtml(c) {
    ensureStyles();
    var thread = (c && Array.isArray(c.thread)) ? c.thread.filter(function (e) {
      return e && String(e.body || "").trim();
    }) : [];
    if (!thread.length) return "";

    var earlier = Number(c.thread_earlier) || 0;
    var subj = threadSubject(thread);
    var html = ['<div class="th-wrap">'];
    if (subj) html.push('<div class="th-subject">' + esc(subj) + "</div>");
    if (earlier > 0) {
      html.push('<div class="th-earlier">&#8963; ' + earlier + " earlier email" + (earlier === 1 ? "" : "s") + " not shown</div>");
    }
    for (var i = 0; i < thread.length; i++) {
      var e = thread[i];
      var isLead = e.who === "lead";
      var isLatest = i === thread.length - 1 && isLead;
      var name = String(e.from_name || "").trim();
      var label = isLead
        ? (isLatest ? (name ? name + "'s latest reply" : "Their latest reply")
                    : (name ? name + " replied" : "They replied"))
        : "We sent";
      var when = shortWhen(e.at);
      html.push(
        '<div class="th-email ' + (isLead ? "lead" : "us") + (isLatest ? " latest" : "") + '">' +
          '<div class="th-label">' + esc(label) +
            (when ? ' <span class="th-when">&middot; ' + esc(when) + "</span>" : "") +
          "</div>" +
          '<div class="th-body">' + esc(e.body) + "</div>" +
        "</div>"
      );
    }
    html.push("</div>");
    return html.join("");
  }

  window.renderThreadHtml = renderThreadHtml;
})();
