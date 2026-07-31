function versionTableHTML(versions, note, meetings, combinations) {
    /* meetings land on the email STEP, never the version (Smartlead cannot
       attribute a booking to a variant) — so the count renders once, on the
       step's first row, and other rows of that step show a dot. */
    var hasMeet = !!(meetings && (meetings.by_step || meetings.by_variant));
    var byVar = (meetings && meetings.by_variant) || {};
    function rateSpan(n, d) { return (d && n) ? ' <span class="ring-caption">' + (n / d * 100).toFixed(1) + '%</span>' : ''; }
    function perPos(v) { return (v.positives > 0 && v.sent) ? fmtInt(Math.round(v.sent / v.positives)) : '<span class="ring-caption">' + (v.sent < 300 ? 'early' : '—') + '</span>'; }
    /* sent lookup by "step|label" — sizes the combination rows below. */
    var sentBy = {};
    versions.forEach(function (v) { if (!v.inline && v.label != null) sentBy[String(v.step) + '|' + v.label] = v.sent || 0; });
    /* group by email step; variants alphabetical, disabled flagged "off". */
    var byStep = {};
    versions.forEach(function (v) { var k = v.step != null ? String(v.step) : '?'; (byStep[k] = byStep[k] || []).push(v); });
    var stepKeys = Object.keys(byStep).sort(function (a, b) { return (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0); });
    /* best opener: Email-1, active, with positives, fewest sends per positive */
    var best = null;
    (byStep['1'] || []).forEach(function (v) {
      if (v.disabled || v.inline || !(v.positives > 0) || !v.sent) return;
      var pp = v.sent / v.positives;
      if (best === null || pp < best.pp) best = { label: v.label, pp: pp };
    });
    var rows = stepKeys.map(function (sk) {
      var vs = byStep[sk].slice().sort(function (a, b) { return (a.label == null ? '￿' : String(a.label)).localeCompare(b.label == null ? '￿' : String(b.label)); });
      var band = '<tr class="vp-band"><td class="vp-l" colspan="7">Email ' + esc(sk) +
        ' <span class="ring-caption">' + vs.length + ' variant' + (vs.length === 1 ? '' : 's') + '</span></td></tr>';
      var body = vs.map(function (v) {
        var label = v.inline ? 'inline' : (v.label || '?');
        var isBest = best && sk === '1' && !v.disabled && !v.inline && v.label === best.label;
        /* deduced meetings on this variant (calls whose journey ran through it) */
        var mv = (!v.inline && v.label != null) ? (byVar[sk + '|' + v.label] || 0) : null;
        var meetCell = !hasMeet ? '' : (mv == null ? '<span class="ring-caption">&middot;</span>'
          : (mv > 0 ? fmtInt(mv) : '<span class="ring-caption">0</span>'));
        var pmCell = (mv && v.sent) ? fmtInt(Math.round(v.sent / mv)) : '';
        return '<tr>' +
          '<td data-label="Version">' + esc(label) +
            (v.disabled ? ' <span class="ring-caption">off</span>' : '') +
            (isBest ? ' <span class="vp-best">best</span>' : '') + '</td>' +
          '<td class="tnum" data-label="Sent">' + fmtInt(v.sent) + '</td>' +
          '<td class="tnum" data-label="Replies">' + fmtInt(v.replies) + rateSpan(v.replies, v.sent) + '</td>' +
          '<td class="tnum" data-label="Positives">' + fmtInt(v.positives) + rateSpan(v.positives, v.sent) + '</td>' +
          '<td class="tnum" data-label="Sent / positive">' + perPos(v) + '</td>' +
          '<td class="tnum" data-label="Meetings">' + meetCell + '</td>' +
          '<td class="tnum" data-label="Sent / meeting">' + pmCell + '</td></tr>';
      }).join('');
      return band + body;
    }).join('');
    /* combinations: opener → follow-up paths deduced from booked replies */
    var comboHTML = '';
    if (combinations && Object.keys(combinations).length) {
      var crows = Object.keys(combinations).map(function (k) {
        var p = k.split('>');
        return { e1: p[0], e2: p[1], mt: combinations[k], snt: (sentBy['1|' + p[0]] || 0) + (sentBy['2|' + p[1]] || 0) };
      }).sort(function (a, b) { return b.mt - a.mt || String(a.e1).localeCompare(String(b.e1)); });
      var bestMt = crows.reduce(function (m, c) { return Math.max(m, c.mt); }, 0);
      comboHTML = '<div class="vp-combos"><div class="vp-combos-h">Best combination <span class="ring-caption">the opener the booker saw &rarr; the follow-up · sent counts both emails</span></div>' +
        '<div class="leads-table-wrap"><table class="leads-table version-perf-table"><thead><tr><th>Combination</th><th class="tnum">Sent</th><th class="tnum">Meetings</th><th class="tnum">Sent / meeting</th></tr></thead><tbody>' +
        crows.map(function (c) {
          var isb = c.mt === bestMt && c.mt > 0;
          return '<tr' + (isb ? ' class="vp-win"' : '') + '><td data-label="Combination">' + esc(c.e1) + ' <span class="ring-caption">&rarr;</span> ' + esc(c.e2) + (isb ? ' <span class="vp-best">best</span>' : '') + '</td>' +
            '<td class="tnum" data-label="Sent">' + (c.snt ? fmtInt(c.snt) : '<span class="ring-caption">—</span>') + '</td>' +
            '<td class="tnum" data-label="Meetings">' + fmtInt(c.mt) + '</td>' +
            '<td class="tnum" data-label="Sent / meeting">' + (c.mt && c.snt ? fmtInt(Math.round(c.snt / c.mt)) : '<span class="ring-caption">—</span>') + '</td></tr>';
        }).join('') + '</tbody></table></div></div>';
    }
    var meetNote = '';
    if (hasMeet) {
      var tot = meetings.total || 0, att = meetings.attributed || 0;
      meetNote = fmtInt(tot) + ' meeting' + (tot === 1 ? '' : 's') + ' on this campaign, one per person. ' +
        fmtInt(att) + ' tied to the variant each booker saw by matching the email they quoted back in their reply' +
        (tot > att ? ' (' + fmtInt(tot - att) + " didn't quote enough to tell, or the variants share the same copy)" : '') +
        ". A booked call runs through an opener and a follow-up, so a variant's Meetings counts every call whose journey passed through it.";
    }
    return '<div class="leads-table-wrap"><table class="leads-table version-perf-table">' +
      '<thead><tr><th>Version</th><th class="tnum">Sent</th><th class="tnum">Replies</th><th class="tnum">Positives</th><th class="tnum">Sent / positive</th><th class="tnum">Meetings</th><th class="tnum">Sent / meeting</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>' + comboHTML +
      (meetNote ? '<p class="sample-footer">' + esc(meetNote) + '</p>' : '') +
      (note ? '<p class="sample-footer">' + esc(note) + '</p>' : '');
  }
