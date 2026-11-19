/* Program pages for docs/dashboard.html: charts, tables, legislation,
   state comparison, key findings, and the source list.  build_dashboard.py
   inlines this file before app.js.  Everything on these pages comes from
   the PROGRAM object (ip/program_data.json) or, for the
   "Well list in charts" page, from the well table the well pages use.

   Nothing here estimates a value.  A figure an agency didn't publish is
   null in the data and is drawn as a gap and labeled "not published",
   never as zero. */
(function () {
  'use strict';

  var NP = 'not published';
  var $ = function (id) { return document.getElementById(id); };
  var tip = $('tip');

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  function fmtInt(n) { return Math.round(n).toLocaleString('en-US'); }
  function fmtUsd(v) {
    var a = Math.abs(v);
    if (a >= 1e9) { return '$' + (v / 1e9).toFixed(2) + 'B'; }
    if (a >= 1e6) { return '$' + (v / 1e6).toFixed(a >= 1e8 ? 0 : 1) + 'M'; }
    if (a >= 1e4) { return '$' + Math.round(v / 1e3) + 'K'; }
    return '$' + fmtInt(v);
  }
  function fmt(v, unit) {
    if (v === null || v === undefined || v === '') { return NP; }
    if (typeof v !== 'number') { return String(v); }
    if (unit === 'usd') { return fmtUsd(v); }
    if (unit === 'usdfull') { return '$' + fmtInt(v); }
    if (unit === 'pct') { return (Math.round(v * 10) / 10) + '%'; }
    if (unit === 'yr') { return (Math.round(v * 10) / 10) + ' yr'; }
    if (unit === 'x') { return (Math.round(v * 100) / 100) + 'x'; }
    if (unit === 'year') { return String(v); }
    return fmtInt(v);
  }
  function link(url, text) { return '<a target="_blank" rel="noopener" href="' + esc(url) + '">' + esc(text) + '</a>'; }
  function srcLink(id) {
    var s = PROGRAM.sources[id];
    if (!s) { return esc(id); }
    return link(s.url, s.t) + (s.pub ? ', ' + esc(s.pub) : '') + (s.date ? ', ' + esc(s.date) : '');
  }

  // ------------------------------------------------------------------
  // Tooltip

  function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; moveTip(e); }
  function moveTip(e) {
    var x = Math.min(e.clientX + 14, window.innerWidth - 330);
    var y = Math.min(e.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
    tip.style.left = Math.max(x, 8) + 'px';
    tip.style.top = Math.max(y, 8) + 'px';
  }
  function hideTip() { tip.hidden = true; }

  // ------------------------------------------------------------------
  // Canvas helpers

  var K = {};
  function readTokens() {
    var cs = getComputedStyle(document.documentElement);
    ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 'fg', 'fg-2', 'muted', 'line', 'line-2', 'surface', 'accent', 'sans', 'mono'].forEach(function (n) {
      K[n] = cs.getPropertyValue('--' + n).trim();
    });
  }
  function color(c) { return K[c] || c || K.s1; }
  function cssColor(c) { return c && c.charAt(0) === '#' ? c : 'var(--' + c + ')'; }
  function prep(c, h, wOverride) {
    var w = wOverride || Math.floor(c.parentElement.clientWidth);
    if (!w) { return null; }
    var dpr = window.devicePixelRatio || 1;
    c.style.width = w + 'px'; c.style.height = h + 'px';
    c.width = Math.round(w * dpr); c.height = Math.round(h * dpr);
    var ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return {ctx: ctx, w: w, h: h};
  }
  function txt(ctx, s, x, y, o) {
    o = o || {};
    ctx.font = (o.weight || 400) + ' ' + (o.size || 11) + 'px ' + (o.mono ? K.mono : K.sans);
    ctx.fillStyle = o.color || K['fg-2'];
    ctx.textAlign = o.align || 'left';
    ctx.textBaseline = o.base || 'middle';
    ctx.fillText(s, x, y);
    return ctx.measureText(s).width;
  }
  function fit(ctx, s, maxW) {
    if (ctx.measureText(s).width <= maxW) { return s; }
    while (s.length > 1 && ctx.measureText(s + '…').width > maxW) { s = s.slice(0, -1); }
    return s + '…';
  }
  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); } else { ctx.rect(x, y, w, h); }
    ctx.fill();
  }
  function niceMax(v) {
    if (!(v > 0)) { return 1; }
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var m = v / p;
    var steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) { if (m <= steps[i]) { return steps[i] * p; } }
    return 10 * p;
  }

  var CHARTS = [];
  function chart(c, label, draw) {
    c.setAttribute('role', 'img');
    c.setAttribute('aria-label', label);
    var o = {c: c, draw: function () { c._hits = []; c._hitFn = null; if (c.offsetParent !== null) { draw(c); } }};
    function hover(e) {
      var r = c.getBoundingClientRect();
      var x = e.clientX - r.left, y = e.clientY - r.top;
      var h = c._hitFn ? c._hitFn(x, y) : (c._hits || []).filter(function (q) {
        return x >= q.x && x <= q.x + q.w && y >= q.y && y <= q.y + q.h;
      })[0];
      if (h) { showTip(e, h.tip); } else { hideTip(); }
    }
    c.addEventListener('pointermove', hover);
    c.addEventListener('pointerdown', hover);
    c.addEventListener('pointerleave', hideTip);
    var raf = 0;
    new ResizeObserver(function () { cancelAnimationFrame(raf); raf = requestAnimationFrame(o.draw); }).observe(c.parentElement);
    CHARTS.push(o);
    return o;
  }
  function drawAll() { readTokens(); CHARTS.forEach(function (o) { o.draw(); }); }

  // Vertical bars, grouped or stacked, with optional line series on a right axis.
  function drawBars(c, d) {
    var p = prep(c, d.height || 280); if (!p) { return; }
    var ctx = p.ctx, w = p.w, h = p.h;
    var bars = d.series.filter(function (s) { return s.type !== 'line'; });
    var lines = d.series.filter(function (s) { return s.type === 'line'; });
    var rightAxis = lines.some(function (s) { return s.axis === 'right'; });
    var n = d.x.length;
    var maxL = 0, maxR = 0;
    d.x.forEach(function (_, i) {
      var sum = 0;
      bars.forEach(function (s) { var v = s.values[i]; if (typeof v === 'number') { sum += v; if (!d.stacked) { maxL = Math.max(maxL, v); } } });
      if (d.stacked) { maxL = Math.max(maxL, sum); }
      lines.forEach(function (s) { var v = s.values[i]; if (typeof v === 'number') { if (s.axis === 'right') { maxR = Math.max(maxR, v); } else { maxL = Math.max(maxL, v); } } });
    });
    maxL = niceMax(maxL); maxR = niceMax(maxR);
    var padL = 52, padR = rightAxis ? 52 : 12, padT = 14, padB = 30;
    var pw = w - padL - padR, ph = h - padT - padB;
    for (var t = 0; t <= 4; t++) {
      var gy = Math.round(padT + ph - ph * t / 4) + 0.5;
      ctx.strokeStyle = K.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(w - padR, gy); ctx.stroke();
      txt(ctx, fmt(maxL * t / 4, d.unit), padL - 6, gy, {align: 'right'});
      if (rightAxis) { txt(ctx, fmt(maxR * t / 4, d.unit2), w - padR + 6, gy, {color: color(lines[0].c)}); }
    }
    var slot = pw / n;
    var groupW = Math.min(slot * 0.72, 64);
    var skip = Math.ceil(n / Math.max(1, Math.floor(pw / 46)));
    d.x.forEach(function (lab, i) {
      var cx = padL + slot * i + slot / 2;
      if (i % skip === 0) { txt(ctx, String(lab), cx, h - padB + 13, {align: 'center'}); }
      var rows = [];
      var any = false;
      if (d.stacked) {
        var y = padT + ph;
        bars.forEach(function (s) {
          var v = s.values[i];
          rows.push([s, v]);
          if (typeof v !== 'number') { return; }
          any = true;
          var bh = v / maxL * ph;
          ctx.fillStyle = color(s.c);
          ctx.fillRect(cx - groupW / 2, y - bh, groupW, Math.max(bh - 1, 0));
          y -= bh;
        });
      } else {
        var bw = groupW / Math.max(bars.length, 1);
        bars.forEach(function (s, j) {
          var v = s.values[i];
          rows.push([s, v]);
          if (typeof v !== 'number') { return; }
          any = true;
          var bh = v / maxL * ph;
          ctx.fillStyle = color(s.c);
          rrect(ctx, cx - groupW / 2 + bw * j + 1, padT + ph - bh, Math.max(bw - 2, 2), bh, 2);
        });
      }
      if (!any && bars.length) { txt(ctx, 'n/p', cx, padT + ph - 9, {align: 'center', size: 10, color: K.muted}); }
      lines.forEach(function (s) { rows.push([s, s.values[i]]); });
      var total = d.stacked && bars.length > 1 ? bars.reduce(function (a, s) { return a + (typeof s.values[i] === 'number' ? s.values[i] : 0); }, 0) : null;
      c._hits.push({x: cx - slot / 2, y: padT, w: slot, h: ph + padB, tip: '<b>' + esc(lab) + '</b>' + rows.map(function (r) {
        return '<br>' + esc(r[0].name) + ': ' + esc(fmt(r[1], r[0].axis === 'right' ? d.unit2 : (r[0].unit || d.unit)));
      }).join('') + (total !== null && any ? '<br>Total shown: ' + esc(fmt(total, d.unit)) : '')});
    });
    lines.forEach(function (s) {
      var mx = s.axis === 'right' ? maxR : maxL;
      var col = color(s.c);
      ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineJoin = 'round';
      var open = false;
      ctx.beginPath();
      s.values.forEach(function (v, i) {
        if (typeof v !== 'number') { open = false; return; }
        var x = padL + slot * i + slot / 2, y = padT + ph - v / mx * ph;
        if (open) { ctx.lineTo(x, y); } else { ctx.moveTo(x, y); open = true; }
      });
      ctx.stroke();
      s.values.forEach(function (v, i) {
        if (typeof v !== 'number') { return; }
        var x = padL + slot * i + slot / 2, y = padT + ph - v / mx * ph;
        ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fillStyle = col; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = K.surface; ctx.stroke();
      });
    });
  }

  // Ranked horizontal bars.  A row with no published value keeps its place
  // at the bottom and says so.
  function drawHbar(c, d) {
    var rows = d.rows;
    var rowH = d.rowH || 26;
    var p = prep(c, rows.length * rowH + 26); if (!p) { return; }
    var ctx = p.ctx, w = p.w;
    ctx.font = '400 12px ' + K.sans;
    var labW = Math.min(Math.max.apply(null, rows.map(function (r) { return ctx.measureText(r.label).width; })) + 10, w * 0.48);
    var valW = 96;
    var pw = Math.max(w - labW - valW, 40);
    var max = niceMax(Math.max.apply(null, rows.map(function (r) { return typeof r.value === 'number' ? r.value : 0; })));
    for (var t = 0; t <= 4; t++) {
      var gx = Math.round(labW + pw * t / 4) + 0.5;
      ctx.strokeStyle = K.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, rows.length * rowH); ctx.stroke();
      txt(ctx, fmt(max * t / 4, d.unit), gx, rows.length * rowH + 13, {align: t === 0 ? 'left' : t === 4 ? 'right' : 'center', size: 10});
    }
    rows.forEach(function (r, i) {
      var y = i * rowH;
      ctx.font = (r.hl ? 600 : 400) + ' 12px ' + K.sans;
      txt(ctx, fit(ctx, r.label, labW - 8), labW - 8, y + rowH / 2, {align: 'right', size: 12, weight: r.hl ? 600 : 400, color: r.hl ? K.fg : K['fg-2']});
      if (typeof r.value === 'number') {
        var bw = Math.max(r.value / max * pw, 2);
        ctx.fillStyle = color(r.c || (r.hl ? (d.hlColor || 's2') : (d.c || 's1')));
        rrect(ctx, labW, y + 5, bw, rowH - 10, 3);
        txt(ctx, fmt(r.value, d.unit) + (r.mark || ''), labW + bw + 6, y + rowH / 2, {size: 11.5, weight: r.hl ? 600 : 400, color: K.fg});
      } else {
        txt(ctx, NP, labW + 6, y + rowH / 2, {size: 11, color: K.muted});
      }
      c._hits.push({x: 0, y: y, w: w, h: rowH, tip: '<b>' + esc(r.label) + '</b>: ' + esc(fmt(r.value, d.unit)) + (r.note ? '<br>' + esc(r.note) : '')});
    });
  }

  function drawDonut(c, d) {
    var s = Math.min(c.parentElement.clientWidth, 210);
    var p = prep(c, s, s); if (!p) { return; }
    var ctx = p.ctx, cx = s / 2, cy = s / 2, r1 = s / 2 - 4, r0 = r1 - 28;
    var tot = d.segs.reduce(function (a, x) { return a + (x.value || 0); }, 0) || 1;
    var a = -Math.PI / 2, arcs = [];
    d.segs.forEach(function (sg) {
      if (!sg.value) { return; }
      var da = sg.value / tot * Math.PI * 2, gap = d.segs.length > 1 ? 0.02 : 0;
      ctx.beginPath(); ctx.arc(cx, cy, r1, a + gap, a + da - gap); ctx.arc(cx, cy, r0, a + da - gap, a + gap, true); ctx.closePath();
      ctx.fillStyle = color(sg.c); ctx.fill();
      arcs.push({a0: a, a1: a + da, tip: '<b>' + esc(sg.label) + '</b>: ' + esc(fmt(sg.value, d.unit)) + ' (' + (100 * sg.value / tot).toFixed(1) + '%)'});
      a += da;
    });
    txt(ctx, d.center || fmt(tot, d.unit), cx, cy - 7, {align: 'center', size: 20, weight: 600, color: K.fg});
    txt(ctx, d.sub || '', cx, cy + 14, {align: 'center', size: 11});
    c._hitFn = function (x, y) {
      var dx = x - cx, dy = y - cy, dist = Math.hypot(dx, dy);
      if (dist < r0 || dist > r1) { return null; }
      var ang = Math.atan2(dy, dx); if (ang < -Math.PI / 2) { ang += Math.PI * 2; }
      return arcs.filter(function (q) { return ang >= q.a0 && ang < q.a1; })[0] || null;
    };
  }

  // ------------------------------------------------------------------
  // Tables

  function cellHtml(v, col) {
    if (v === null || v === undefined || v === '') { return '<span class="blank">' + NP + '</span>'; }
    if (typeof v === 'object' && v.u) { return link(v.u, v.t); }
    if (typeof v === 'object' && v.t !== undefined) { return esc(v.t); }
    if (typeof v === 'number') { return esc(fmt(v, col.unit)); }
    return esc(v);
  }
  function cellSort(v) {
    if (v === null || v === undefined || v === '') { return null; }
    if (typeof v === 'object') { return v.v !== undefined ? v.v : String(v.t).toLowerCase(); }
    return typeof v === 'number' ? v : String(v).toLowerCase();
  }
  function tableHtml(d, cls) {
    return '<div class="tablewrap ' + (cls || 'short') + '"><table class="data"><thead><tr>' + d.cols.map(function (col, i) {
      return '<th class="sortable' + (col.num ? ' num' : '') + '" data-i="' + i + '">' + esc(col.label) + '</th>';
    }).join('') + '</tr></thead><tbody>' + rowsHtml(d, d.rows) + '</tbody></table></div>';
  }
  function rowsHtml(d, rows) {
    return rows.map(function (r) {
      return '<tr' + (r.hl ? ' class="hl"' : '') + '>' + d.cols.map(function (col) {
        return '<td class="' + (col.num ? 'num' : '') + (col.wrap ? ' wrap' : '') + (col.nw ? ' nw' : '') + '">' + cellHtml(r[col.k], col) + '</td>';
      }).join('') + '</tr>';
    }).join('');
  }
  function bindSort(wrap, d) {
    var state = {i: -1, dir: 1};
    Array.prototype.forEach.call(wrap.querySelectorAll('th.sortable'), function (th) {
      th.onclick = function () {
        var i = Number(th.getAttribute('data-i'));
        state = {i: i, dir: state.i === i ? -state.dir : 1};
        var k = d.cols[i].k;
        var rows = d.rows.slice().sort(function (a, b) {
          var x = cellSort(a[k]), y = cellSort(b[k]);
          if (x === null && y === null) { return 0; }
          if (x === null) { return 1; }
          if (y === null) { return -1; }
          return (x < y ? -1 : x > y ? 1 : 0) * state.dir;
        });
        wrap.querySelector('tbody').innerHTML = rowsHtml(d, rows);
        Array.prototype.forEach.call(wrap.querySelectorAll('th'), function (h, j) {
          h.innerHTML = esc(d.cols[j].label) + (j === i ? ' <span class="arrow">' + (state.dir > 0 ? '▲' : '▼') + '</span>' : '');
        });
      };
    });
  }

  // ------------------------------------------------------------------
  // Cards

  function chartDataTable(d) {
    if (d.kind === 'bars') {
      return {cols: [{k: 'x', label: d.xLabel || 'Period'}].concat(d.series.map(function (s, j) {
        return {k: 's' + j, label: s.name, num: true, unit: s.axis === 'right' ? d.unit2 : (s.unit || d.unit)};
      })), rows: d.x.map(function (x, i) {
        var r = {x: String(x)};
        d.series.forEach(function (s, j) { r['s' + j] = s.values[i]; });
        return r;
      })};
    }
    if (d.kind === 'hbar') {
      return {cols: [{k: 'label', label: d.rowLabel || 'Item'}, {k: 'value', label: d.valueLabel || 'Value', num: true, unit: d.unit}, {k: 'note', label: 'Basis', wrap: true}],
        rows: d.rows.map(function (r) { return {label: r.label, value: r.value, note: r.note || ' ', hl: r.hl}; })};
    }
    if (d.kind === 'donut') {
      return {cols: [{k: 'label', label: 'Part'}, {k: 'value', label: 'Value', num: true, unit: d.unit}],
        rows: d.segs.map(function (s) { return {label: s.label, value: s.value}; })};
    }
    return null;
  }

  function legendHtml(d) {
    if (d.kind === 'bars' && d.series.length > 1) {
      return '<div class="legend">' + d.series.map(function (s) {
        return '<span' + (s.type === 'line' ? ' class="ln"' : '') + ' style="--c:' + esc(cssColor(s.c)) + '">' + esc(s.name) + '</span>';
      }).join('') + '</div>';
    }
    if (d.kind === 'donut') {
      return '<div class="legend" style="flex-direction:column;gap:6px;font-size:13px">' + d.segs.map(function (s) {
        return '<span style="--c:' + esc(cssColor(s.c)) + '"><b style="color:var(--fg)">' + esc(fmt(s.value, d.unit)) + '</b> ' + esc(s.label) + '</span>';
      }).join('') + '</div>';
    }
    if (d.kind === 'hbar' && d.legend) {
      return '<div class="legend">' + d.legend.map(function (s) { return '<span style="--c:' + esc(cssColor(s.c)) + '">' + esc(s.name) + '</span>'; }).join('') + '</div>';
    }
    return '';
  }

  var cardSeq = 0;
  function renderCard(d, host) {
    var div = document.createElement('div');
    div.className = 'card' + (d.wide ? ' wide' : '');
    if (d.id) { div.id = 'card-' + d.id; }
    var cid = 'cv' + (++cardSeq);
    var html = '<div class="card-head"><h3>' + esc(d.title) + '</h3>' +
      (d.derived ? '<span class="tag derived plain">includes derived figures</span>' : d.eyebrow ? '<span class="eyebrow">' + esc(d.eyebrow) + '</span>' : '') + '</div>' +
      (d.lead ? '<p class="lead">' + esc(d.lead) + '</p>' : '');
    if (d.kind === 'bars' || d.kind === 'hbar') {
      html += legendHtml(d) + '<div><canvas id="' + cid + '"></canvas></div>';
    } else if (d.kind === 'donut') {
      html += '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:18px"><div style="width:210px;max-width:100%"><canvas id="' + cid + '"></canvas></div>' + legendHtml(d) + '</div>';
    } else if (d.kind === 'table') {
      html += tableHtml(d, d.tall ? 'free' : 'short');
    } else if (d.kind === 'bullets') {
      html += '<ul class="bullets">' + d.items.map(function (it) {
        if (typeof it === 'string') { return '<li>' + esc(it) + '</li>'; }
        return '<li>' + (it.b ? '<b>' + esc(it.b) + '</b>  ' : '') + esc(it.t) + (it.src ? ' (' + it.src.map(function (id, n) {
          var s = PROGRAM.sources[id];
          return s ? link(s.url, 'source' + (it.src.length > 1 ? ' ' + (n + 1) : '')) : '';
        }).join(', ') + ')' : '') + '</li>';
      }).join('') + '</ul>';
    }
    if (d.notes && d.notes.length) {
      html += '<ul class="cardnotes">' + d.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>';
    }
    var dt = chartDataTable(d);
    if (dt || (d.src && d.src.length)) {
      html += '<details class="src"><summary>' + (dt ? 'Data and sources' : 'Sources') + '</summary>' +
        (dt ? tableHtml(dt, 'short') : '') +
        (d.src && d.src.length ? '<ul>' + d.src.map(function (id) { return '<li>' + srcLink(id) + '</li>'; }).join('') + '</ul>' : '') + '</details>';
    }
    div.innerHTML = html;
    host.appendChild(div);
    var cv = $(cid);
    if (cv) {
      chart(cv, d.title, d.kind === 'bars' ? function (c) { drawBars(c, d); } : d.kind === 'hbar' ? function (c) { drawHbar(c, d); } : function (c) { drawDonut(c, d); });
    }
    Array.prototype.forEach.call(div.querySelectorAll('.tablewrap'), function (wrap, i) {
      bindSort(wrap, d.kind === 'table' && i === 0 ? d : dt);
    });
    return div;
  }

  function renderCards(pageId, def, before) {
    var page = $('page-' + pageId);
    if (def.lead) {
      var pl = document.createElement('p'); pl.className = 'pagelead'; pl.textContent = def.lead; page.appendChild(pl);
    }
    if (before) { before(page); }
    var host = document.createElement('div');
    host.className = 'cards';
    page.appendChild(host);
    (def.cards || []).forEach(function (d) { renderCard(d, host); });
    return host;
  }

  // ------------------------------------------------------------------
  // KPI tiles

  function renderTiles(page, tiles) {
    var host = document.createElement('div');
    host.className = 'tiles';
    page.appendChild(host);
    tiles.forEach(function (t, i) {
      var div = document.createElement('div');
      div.className = 'kpi ' + (t.g || 'g' + (i % 6 + 1));
      var s = t.src ? PROGRAM.sources[t.src] : null;
      div.innerHTML = '<div class="top"><div style="min-width:0"><div class="v">' + esc(t.v) + '</div><div class="k">' + esc(t.k) + '</div></div>' +
        (t.bars ? '<div class="mini"><canvas></canvas></div>' : '') + '</div>' +
        '<div class="foot">' + esc(t.n || '') + (s ? ' · <a target="_blank" rel="noopener" href="' + esc(s.url) + '">source</a>' : t.go ? ' · <a href="#' + esc(t.go) + '">open</a>' : '') + '</div>';
      host.appendChild(div);
      var cv = div.querySelector('canvas');
      if (cv) {
        chart(cv, t.k + ' by period', function (c) {
          var p = prep(c, 34); if (!p) { return; }
          var vals = t.bars.filter(function (v) { return typeof v === 'number'; });
          var n = t.bars.length, gap = 3, bw = Math.max((p.w - gap * (n - 1)) / n, 3), max = Math.max.apply(null, vals.concat([1]));
          t.bars.forEach(function (v, j) {
            if (typeof v !== 'number') { return; }
            var bh = Math.max(v / max * (p.h - 2), 2), x = j * (bw + gap);
            p.ctx.fillStyle = 'rgba(255,255,255,.9)';
            rrect(p.ctx, x, p.h - bh, bw, bh, 2);
            c._hits.push({x: x, y: 0, w: bw + gap, h: p.h, tip: '<b>' + esc(t.barLabels[j]) + '</b>: ' + esc(fmt(v, t.unit))});
          });
        });
      }
    });
  }

  // ------------------------------------------------------------------
  // Well list in charts.  Counts come from the same well table as the map
  // and the well list, so they total the same number of wells.

  function count(wells, keyFn) {
    var m = {};
    wells.forEach(function (w) { var k = keyFn(w); m[k] = (m[k] || 0) + 1; });
    return m;
  }
  function topRows(m, n, restLabel) {
    var rows = Object.keys(m).map(function (k) { return {label: k, value: m[k]}; }).sort(function (a, b) { return b.value - a.value || (a.label < b.label ? -1 : 1); });
    if (n && rows.length > n) {
      var rest = rows.slice(n);
      rows = rows.slice(0, n);
      rows.push({label: restLabel.replace('{n}', rest.length), value: rest.reduce(function (a, r) { return a + r.value; }, 0), c: 's4'});
    }
    return rows;
  }
  function yearOf(mdy) { var m = /(\d{4})$/.exec(mdy || ''); return m ? Number(m[1]) : null; }

  function wellCards() {
    var wells = window.orphanWells.shown();
    var total = wells.length;
    var cards = [];
    if (!total) { return cards; }
    // The map's tier colors, so the two pages read the same way.
    var tierC = {1: '#c00000', 2: '#ed7d31', 3: '#ffc000', 4: '#70ad47'};
    var tiers = count(wells, function (w) { return w.Tier; });
    cards.push({kind: 'donut', title: 'Wells by SRA priority tier', eyebrow: 'SRA score',
      lead: 'Tier is Subsurface Risk Analytics’ priority score for this dataset.  ECMC sets its own plugging priorities, and the tier isn’t ECMC’s ranking or a plugging order.',
      unit: 'n', center: fmtInt(total), sub: total === window.orphanWells.wells.length ? 'wells on the list' : 'wells shown',
      segs: ['1', '2', '3', '4'].map(function (t) { return {label: 'SRA tier ' + t, value: tiers[t] || 0, c: tierC[t]}; })});

    var di = count(wells, function (w) { return w.DI_Community_Nov2024 === 'Yes' ? 'In a DI community' : 'Outside DI communities'; });
    cards.push({kind: 'donut', title: 'Wells inside disproportionately impacted communities', eyebrow: 'CDPHE, Nov 2024',
      lead: 'A well counts when it sits in a block group CDPHE designated a disproportionately impacted (DI) community in November 2024.',
      unit: 'n', center: fmtInt(di['In a DI community'] || 0), sub: 'in a DI community',
      segs: [{label: 'In a DI community', value: di['In a DI community'] || 0, c: 's5'}, {label: 'Outside DI communities', value: di['Outside DI communities'] || 0, c: 's4'}]});

    cards.push({kind: 'hbar', wide: true, title: 'Wells by county', eyebrow: 'ECMC list', unit: 'n', rowLabel: 'County', valueLabel: 'Wells',
      lead: 'The 15 counties with the most wells on the list.  The County and project summary page has every county.',
      rows: topRows(count(wells, function (w) { return w.County; }), 15, 'Other counties ({n})')});

    cards.push({kind: 'hbar', wide: true, title: 'Wells by ECMC Orphaned Well Program project', eyebrow: 'ECMC list', unit: 'n', rowLabel: 'OWP project', valueLabel: 'Wells',
      lead: 'ECMC groups orphaned wells into projects, usually by the operator that left them.  The 15 largest are shown.',
      rows: topRows(count(wells, function (w) { return w.Project; }), 15, 'Other projects ({n})')});

    var dec = {}, noDate = 0, completionOnly = 0;
    wells.forEach(function (w) {
      var y = yearOf(w.spud_date);
      if (y === null) { y = yearOf(w.completion_date); if (y !== null) { completionOnly++; } }
      if (y === null) { noDate++; return; }
      var d = Math.floor(y / 10) * 10;
      dec[d] = (dec[d] || 0) + 1;
    });
    var decs = Object.keys(dec).map(Number).sort(function (a, b) { return a - b; });
    var xs = [];
    for (var d0 = decs[0]; d0 <= decs[decs.length - 1]; d0 += 10) { xs.push(d0); }
    if (xs.length) { cards.push({kind: 'bars', wide: true, title: 'Decade each well was drilled', eyebrow: 'COGIS scout cards', unit: 'n', xLabel: 'Decade',
      lead: 'From the spud date on the scout card, or the completion date when the card has no spud date.',
      x: xs.map(function (d) { return d + 's'; }), series: [{name: 'Wells', c: 's1', values: xs.map(function (d) { return dec[d] || 0; })}],
      notes: [fmtInt(completionOnly) + ' wells are placed by completion date because the scout card has no spud date.',
        fmtInt(noDate) + ' wells have neither date on the scout card and aren’t in the chart.  No date is estimated.']}); }

    var bins = [[0, 1000], [1000, 2000], [2000, 3000], [3000, 4000], [4000, 5000], [5000, 6000], [6000, 7000], [7000, 8000], [8000, 9000], [9000, 10000], [10000, Infinity]];
    var depth = bins.map(function () { return 0; }), noTd = 0;
    wells.forEach(function (w) {
      var v = w.measured_td_ft === '' ? NaN : Number(String(w.measured_td_ft).replace(/,/g, ''));
      if (isNaN(v)) { noTd++; return; }
      for (var i = 0; i < bins.length; i++) { if (v >= bins[i][0] && v < bins[i][1]) { depth[i]++; break; } }
    });
    cards.push({kind: 'bars', wide: true, title: 'Measured total depth', eyebrow: 'COGIS scout cards', unit: 'n', xLabel: 'Measured TD, ft',
      lead: 'Wells by measured total depth as recorded on the scout card, in 1,000 ft bands.',
      x: bins.map(function (b) { return b[1] === Infinity ? '10,000+' : (b[0] / 1000) + ' to ' + (b[1] / 1000) + 'k'; }),
      series: [{name: 'Wells', c: 's7', values: depth}],
      notes: [fmtInt(noTd) + ' wells have no measured TD on the scout card and aren’t in the chart.']});

    var CLS = ['liquid flow', 'pressure persists or rebuilds', 'flow at end of test', 'flow bled off', 'no flow', 'flow not reported', 'no tests on file'];
    var call = count(wells, function (w) { return w.bh_flow_class; });
    var clat = count(wells, function (w) { return w.bh_flow_class_latest; });
    cards.push({kind: 'bars', wide: true, title: 'Bradenhead flow class: all tests on file and the latest test', eyebrow: 'COGIS bradenhead pages', unit: 'n', xLabel: 'Flow class', height: 300,
      lead: 'The classes summarize what ECMC’s bradenhead test records show.  They aren’t a safety or hazard rating and no class is an ECMC compliance finding.  The About page gives the definitions.',
      x: CLS, series: [{name: 'All tests on file', c: 's1', values: CLS.map(function (k) { return call[k] || 0; })},
        {name: 'Latest test only', c: 's2', values: CLS.map(function (k) { return clat[k] || 0; })}],
      notes: ['The latest test can be years old.  The next chart shows the year of each well’s last test.']});

    var ly = {}, noTest = 0;
    wells.forEach(function (w) { var y = yearOf(w.bh_last_test_date); if (y === null) { noTest++; return; } ly[y] = (ly[y] || 0) + 1; });
    var years = Object.keys(ly).map(Number).sort(function (a, b) { return a - b; });
    var yx = [];
    for (var y0 = years[0]; y0 <= years[years.length - 1]; y0++) { yx.push(y0); }
    if (yx.length) { cards.push({kind: 'bars', title: 'Year of the last bradenhead test', eyebrow: 'COGIS bradenhead pages', unit: 'n', xLabel: 'Year',
      x: yx, series: [{name: 'Wells', c: 's5', values: yx.map(function (y) { return ly[y] || 0; })}],
      notes: [fmtInt(noTest) + ' wells have no dated bradenhead test on file and aren’t in the chart.']}); }

    var st = count(wells, function (w) { return w.well_status === '' ? 'not on the scout card' : w.well_status; });
    cards.push({kind: 'hbar', title: 'Status code on the COGIS scout card', eyebrow: 'COGIS scout cards', unit: 'n', rowLabel: 'Status code', valueLabel: 'Wells',
      lead: 'The code on the scout card can differ from the well’s place on ECMC’s unplugged orphan list, so some wells show PR (producing) or PA (plugged and abandoned).  ECMC’s code list governs.',
      rows: topRows(st, 10, 'Other codes ({n})')});
    return cards;
  }

  // ------------------------------------------------------------------
  // Legislation and rules

  var KIND = {bill: ['Colorado bill', 's1'], rule: ['ECMC rule or board action', 's3'], order: ['Executive order', 's5'], federal: ['Federal', 's2'], other: ['Court, audit, or ballot', 's6']};

  function renderLaw() {
    var page = $('page-law');
    var L = PROGRAM.laws;
    page.innerHTML = '<p class="pagelead">' + esc(L.lead) + '</p>' +
      '<div class="cards"><div class="card wide"><div class="card-head"><h3>Timeline</h3><span class="eyebrow">' + L.items.length + ' entries</span></div>' +
      '<div class="legend">' + Object.keys(KIND).map(function (k) { return '<span style="--c:var(--' + KIND[k][1] + ')">' + KIND[k][0] + '</span>'; }).join('') + '</div>' +
      '<div><canvas id="lawline"></canvas></div></div>' +
      '<div class="card wide"><div class="controls noprint"><label>Type<select id="lawkind"><option value="">All</option>' +
      Object.keys(KIND).map(function (k) { return '<option value="' + k + '">' + KIND[k][0] + '</option>'; }).join('') + '</select></label>' +
      '<label>Status<select id="lawstatus"><option value="">All</option></select></label>' +
      '<label>Search<input type="search" id="lawq" size="28" placeholder="bill number, statute, word"></label>' +
      '<span class="note" id="lawcount"></span></div><div id="lawlist"></div></div>' +
      '<div class="card wide"><div class="card-head"><h3>Statutes and rules in force</h3><span class="eyebrow">core references</span></div>' +
      '<div class="tablewrap free"><table class="data"><thead><tr><th>Citation</th><th>What it covers</th></tr></thead><tbody>' +
      L.refs.map(function (r) { return '<tr><td class="nw">' + link(r[2], r[0]) + '</td><td>' + esc(r[1]) + '</td></tr>'; }).join('') +
      '</tbody></table></div></div>' +
      '<div class="card wide"><div class="card-head"><h3>How Colorado law defines an orphaned well and an orphaned site</h3><span class="eyebrow">definitions</span></div>' +
      '<ul class="bullets">' + L.defs.map(function (d) { return '<li><b>' + esc(d.b) + '</b>  ' + esc(d.t) + '</li>'; }).join('') + '</ul>' +
      '<details class="src"><summary>Sources</summary><ul><li>' + srcLink('rules100') + '</li><li>' + srcLink('act2026') + '</li></ul></details></div></div>';
    var statuses = [];
    L.items.forEach(function (it) { if (statuses.indexOf(it.status) < 0) { statuses.push(it.status); } });
    $('lawstatus').innerHTML += statuses.sort().map(function (s) { return '<option>' + esc(s) + '</option>'; }).join('');
    function draw() {
      var k = $('lawkind').value, s = $('lawstatus').value, q = $('lawq').value.trim().toLowerCase();
      var rows = L.items.filter(function (it) {
        if (k && it.kind !== k) { return false; }
        if (s && it.status !== s) { return false; }
        if (q && (it.cite + ' ' + it.title + ' ' + it.summary + ' ' + (it.sections || '')).toLowerCase().indexOf(q) < 0) { return false; }
        return true;
      });
      $('lawcount').textContent = 'Showing ' + rows.length + ' of ' + L.items.length + ', newest first.';
      $('lawlist').innerHTML = rows.map(function (it) {
        return '<div class="law" id="law-' + esc(it.id || '') + '"><div class="when">' + esc(it.date) + '</div><div><h4><span class="cite">' + esc(it.cite) + '</span>' + esc(it.title) + '</h4>' +
          '<p><span class="tag" style="--c:var(--' + KIND[it.kind][1] + ')">' + KIND[it.kind][0] + '</span> <span class="tag plain">' + esc(it.status) + '</span>' +
          (it.sections ? ' <span class="note">' + esc(it.sections) + '</span>' : '') + '</p>' +
          '<p>' + esc(it.summary) + '</p>' +
          '<p class="links">' + it.links.map(function (l) { return link(l[1], l[0]); }).join('') + '</p></div></div>';
      }).join('') || '<p class="note">No entries match.</p>';
    }
    ['lawkind', 'lawstatus'].forEach(function (id) { $(id).addEventListener('change', draw); });
    $('lawq').addEventListener('input', draw);
    draw();
    chart($('lawline'), 'Timeline of Colorado orphaned well legislation, rules, and federal actions', function (c) {
      var kinds = Object.keys(KIND);
      var rowH = 30, p = prep(c, kinds.length * rowH + 30); if (!p) { return; }
      var ctx = p.ctx, w = p.w, padL = 170, padR = 16;
      var ys = L.items.map(function (it) { return Number(it.date.slice(0, 4)) + (Number(it.date.slice(5, 7) || 6) - 0.5) / 12; });
      var y0 = Math.floor(Math.min.apply(null, ys)), y1 = Math.ceil(Math.max.apply(null, ys));
      var X = function (v) { return padL + (v - y0) / Math.max(y1 - y0, 1) * (w - padL - padR); };
      var step = Math.ceil((y1 - y0) / Math.max(1, Math.floor((w - padL - padR) / 50)));
      for (var y = y0; y <= y1; y += step) {
        var gx = Math.round(X(y)) + 0.5;
        ctx.strokeStyle = K.line; ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, kinds.length * rowH); ctx.stroke();
        txt(ctx, String(y), gx, kinds.length * rowH + 14, {align: 'center'});
      }
      kinds.forEach(function (k, i) { txt(ctx, KIND[k][0], padL - 10, i * rowH + rowH / 2, {align: 'right', size: 12}); });
      L.items.forEach(function (it, n) {
        var i = kinds.indexOf(it.kind), x = X(ys[n]), y = i * rowH + rowH / 2;
        ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fillStyle = color(KIND[it.kind][1]); ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1;
        ctx.lineWidth = 1.5; ctx.strokeStyle = K.surface; ctx.stroke();
        c._hits.push({x: x - 7, y: y - 7, w: 14, h: 14, tip: '<b>' + esc(it.cite) + '</b> ' + esc(it.date) + '<br>' + esc(it.title) + '<br>' + esc(it.status)});
      });
    });
  }

  // ------------------------------------------------------------------
  // Sources

  function renderSources() {
    var page = $('page-sources');
    var S = PROGRAM.sources;
    var used = {};
    function note(pageName, d) { (d.src || []).forEach(function (id) { (used[id] = used[id] || {})[pageName] = 1; }); }
    Object.keys(PROGRAM.pages).forEach(function (pk) { (PROGRAM.pages[pk].cards || []).forEach(function (d) {
      note(PAGE_TITLE[pk], d);
      (d.items || []).forEach(function (it) { if (it.src) { note(PAGE_TITLE[pk], it); } });
    }); });
    (PROGRAM.kpis || []).forEach(function (t) { if (t.src) { (used[t.src] = used[t.src] || {}).Overview = 1; } });
    var rows = Object.keys(S).map(function (id) {
      var s = S[id];
      return {pub: s.pub || '', doc: {t: s.t, u: s.url}, date: s.date || '', used: Object.keys(used[id] || {}).join(', ') || 'Reference', note: s.note || ' '};
    }).sort(function (a, b) { return a.pub < b.pub ? -1 : a.pub > b.pub ? 1 : (a.doc.t < b.doc.t ? -1 : 1); });
    var d = {cols: [{k: 'pub', label: 'Publisher'}, {k: 'doc', label: 'Document or page', wrap: true}, {k: 'date', label: 'Dated', nw: true}, {k: 'used', label: 'Used on', wrap: true}, {k: 'note', label: 'Note', wrap: true}], rows: rows};
    page.innerHTML = '<p class="pagelead">' + esc(PROGRAM.sourcesLead) + '</p>' +
      '<div class="controls noprint"><label>Search sources<input type="search" id="srcq" size="32" placeholder="publisher, title, page"></label><span class="note" id="srccount"></span></div>' +
      tableHtml(d, 'free') +
      '<div class="cards" style="margin-top:20px"><div class="card wide"><h3>What the public record doesn’t contain</h3><ul class="bullets">' +
      PROGRAM.gaps.map(function (g) { return '<li>' + esc(g) + '</li>'; }).join('') + '</ul></div></div>';
    var wrap = page.querySelector('.tablewrap');
    bindSort(wrap, d);
    function filter() {
      var q = $('srcq').value.trim().toLowerCase();
      var shown = rows.filter(function (r) { return !q || (r.pub + ' ' + r.doc.t + ' ' + r.used + ' ' + r.note).toLowerCase().indexOf(q) >= 0; });
      wrap.querySelector('tbody').innerHTML = rowsHtml(d, shown);
      $('srccount').textContent = 'Showing ' + shown.length + ' of ' + rows.length + ' sources.';
    }
    $('srcq').addEventListener('input', filter);
    filter();
  }

  // ------------------------------------------------------------------
  // Page registry.  The well pages' router calls show() for these names.

  var PAGE_TITLE = {overview: 'Overview', findings: 'Key findings', finance: 'Funding and spending', activity: 'Plugging and inventory', federal: 'Federal funding',
    profile: 'Well list in charts', law: 'Legislation and rules', states: 'State comparison', policy: 'Bonding and fees by state', sources: 'Sources'};
  var built = {};

  function show(name) {
    if (!built[name]) {
      built[name] = true;
      readTokens();
      if (name === 'overview') {
        var page = $('page-overview');
        var W = window.orphanWells.wells;
        var tiles = [{k: 'Wells on ECMC’s unplugged orphan list', v: fmtInt(W.length), n: 'ECMC list retrieved ' + String(META.listRetrieved).slice(0, 10), g: 'g5', go: 'list'}].concat(PROGRAM.kpis);
        var pl = document.createElement('p'); pl.className = 'pagelead'; pl.textContent = PROGRAM.pages.overview.lead; page.appendChild(pl);
        renderTiles(page, tiles);
        renderCards('overview', {cards: PROGRAM.pages.overview.cards});
      } else if (name === 'profile') {
        renderProfile();
      } else if (name === 'findings') {
        renderFindings();
      } else if (name === 'law') {
        renderLaw();
      } else if (name === 'sources') {
        renderSources();
      } else if (PROGRAM.pages[name]) {
        renderCards(name, PROGRAM.pages[name]);
      }
    }
    requestAnimationFrame(function () {
      drawAll();
      if (pendingCard && pendingCard[0] === name) {
        var target = document.querySelector('#page-' + name + ' #card-' + pendingCard[1]);
        pendingCard = null;
        if (target) { target.scrollIntoView({block: 'start'}); window.scrollBy(0, -90); }
      }
    });
  }

  // ------------------------------------------------------------------
  // Key findings.  Each statement is a template in the data file.  The
  // numbers are worked out here from the same card data the charts draw, so
  // a corrected figure changes the chart and the finding together.

  var pendingCard = null;
  function getCard(page, id) {
    var hit = (PROGRAM.pages[page].cards || []).filter(function (c) { return c.id === id; })[0];
    if (!hit) { throw new Error('Key findings: no card ' + page + '/' + id); }
    return hit;
  }
  function money(v) { return v >= 1e6 ? '$' + (v / 1e6).toFixed(1) + ' million' : '$' + fmtInt(v); }
  function pct1(v) { return (Math.round(v * 10) / 10).toFixed(1).replace(/\.0$/, ''); }
  function ordinal(n) { var s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function longMonth(label) { return String(label).replace('Jul ', 'July ').replace('Aug ', 'August '); }
  function findingFacts() {
    var spend = getCard('finance', 'spend');
    var n = spend.x.length - 1;
    function ser(c, name) { return c.series.filter(function (s) { return s.name.indexOf(name) === 0; })[0].values; }
    var bars = spend.series.filter(function (s) { return s.type !== 'line'; });
    function totalAt(i) { return bars.reduce(function (a, s) { return a + (s.values[i] || 0); }, 0); }
    var wells = ser(spend, 'Wells plugged'), iija = ser(spend, 'Federal IIJA'), blm = ser(spend, 'Federal BLM');
    var fee = ser(spend, 'Enterprise fee'), approp = ser(spend, 'State appropriation'), bond = ser(spend, 'Operator bond');
    var priorMax = 0, priorMaxFy = '';
    wells.forEach(function (v, i) { if (i < n && typeof v === 'number' && v > priorMax) { priorMax = v; priorMaxFy = spend.x[i]; } });
    var i22 = spend.x.indexOf('FY22');
    var inv = getCard('activity', 'inventory');
    var iw = inv.series[0].values, is = inv.series[1].values, m = iw.length - 1;
    var fw = getCard('finance', 'feewells'), fv = fw.series[0].values, k = fv.length - 1;
    var co = getCard('federal', 'coawards');
    var awards = co.segs.reduce(function (a, s) { return a + s.value; }, 0);
    var formula = co.segs.filter(function (s) { return s.label.indexOf('Formula') === 0; }).reduce(function (a, s) { return a + s.value; }, 0);
    var st = getCard('federal', 'stateawards').rows.filter(function (r) { return typeof r.value === 'number'; }).sort(function (a, b) { return b.value - a.value; });
    var sh = getCard('states', 'orphanshare').rows.filter(function (r) { return typeof r.value === 'number'; }).sort(function (a, b) { return a.value - b.value; });
    function rankOf(rows) { for (var i = 0; i < rows.length; i++) { if (rows[i].label === 'Colorado') { return i + 1; } } throw new Error('Key findings: Colorado row missing'); }
    var mix = getCard('activity', 'mix26').segs;
    var iijaSpent = iija.reduce(function (a, v) { return a + (v || 0); }, 0);
    var X = PROGRAM.facts;
    return {
      fy: spend.x[n], fyPrev: spend.x[n - 1], wells: fmtInt(wells[n]), wellsPrev: fmtInt(wells[n - 1]),
      wellsPct: Math.round((wells[n] / wells[n - 1] - 1) * 100), wellsPriorMax: fmtInt(priorMax), wellsPriorMaxFy: priorMaxFy,
      total: money(totalAt(n)), iija: money(iija[n]), iijaPct: pct1(100 * iija[n] / totalAt(n)), fedPct: pct1(100 * (iija[n] + blm[n]) / totalAt(n)),
      iijaPctPrev: pct1(100 * iija[n - 1] / totalAt(n - 1)), appropPct22: pct1(100 * approp[i22] / totalAt(i22)),
      feePct: pct1(100 * fee[n] / totalAt(n)), bondPct: pct1(100 * bond[n] / totalAt(n)),
      perWell: '$' + fmtInt(totalAt(n) / wells[n]),
      inv: fmtInt(iw[m]), invPrev: fmtInt(iw[m - 1]), invChange: fmtInt(iw[m] - iw[m - 1]), invDate: longMonth(inv.x[m]), invPrevDate: longMonth(inv.x[m - 1]),
      invFirst: fmtInt(iw[0]), invFirstDate: longMonth(inv.x[0]), sites: fmtInt(is[m]),
      pendingWells: fmtInt(X.pendingWells), pendingOne: fmtInt(X.pendingOneOperator),
      formula: '$' + fmtInt(formula), eligibility: '$' + fmtInt(X.formulaEligibility), awards: money(awards),
      awardRank: ordinal(rankOf(st)), awardCount: st.length, iijaSpent: money(iijaSpent), spentPct: pct1(100 * iijaSpent / awards),
      feeWellsFirst: fmtInt(fv[0]), feeWellsLast: fmtInt(fv[k]), feeFyFirst: fw.x[0], feeFyLast: fw.x[k], feeWellsDrop: pct1(100 * (1 - fv[k] / fv[0])),
      feeNow: X.feeNow, feeNext: X.feeNext,
      mixPlug: mix[0].value, mixRecl: mix[1].value, mixEnv: mix[2].value,
      shareCO: sh.filter(function (r) { return r.label === 'Colorado'; })[0].value, shareRank: ordinal(rankOf(sh)), shareCount: sh.length
    };
  }
  function renderFindings() {
    var page = $('page-findings');
    var facts = findingFacts();
    function fill(t) {
      return esc(t).replace(/\{(\w+)\}/g, function (_, key) {
        if (facts[key] === undefined) { throw new Error('Key findings: no fact named ' + key); }
        return esc(facts[key]);
      });
    }
    page.innerHTML = '<p class="pagelead">' + esc(PROGRAM.findings.lead) + '</p><div class="cards">' +
      PROGRAM.findings.items.map(function (f, i) {
        return '<div class="card wide finding"><div class="num">' + (i + 1) + '</div><div>' +
          '<div class="card-head"><h3>' + fill(f.title) + '</h3>' + (f.derived ? '<span class="tag derived plain">derived</span>' : '') + '</div>' +
          '<p>' + fill(f.text) + '</p><p class="basis"><b>Basis.</b>  ' + esc(f.basis) + '</p>' +
          '<p class="links">' + f.see.map(function (s) { return '<a href="#' + esc(s[1]) + '" data-card="' + esc(s[2]) + '">Chart: ' + esc(s[0]) + '</a>'; }).join('') +
          f.src.map(function (id) { var so = PROGRAM.sources[id]; return link(so.url, 'Source: ' + so.t.replace(/^Orphaned Well Program annual report, fiscal year /, 'annual report, FY')); }).join('') + '</p>' +
          '</div></div>';
      }).join('') + '</div>';
    Array.prototype.forEach.call(page.querySelectorAll('a[data-card]'), function (a) {
      a.addEventListener('click', function () { pendingCard = [a.getAttribute('href').slice(1), a.getAttribute('data-card')]; });
    });
  }

  // ------------------------------------------------------------------
  // Shell: menu, theme, counts

  $('asof').textContent = PROGRAM.asOf;
  $('srcBadge').textContent = Object.keys(PROGRAM.sources).length;
  $('menuBtn').addEventListener('click', function () { document.body.classList.add('menu'); });
  $('scrim').addEventListener('click', function () { document.body.classList.remove('menu'); });
  $('tabs').addEventListener('click', function () { document.body.classList.remove('menu'); });
  $('themeBtn').addEventListener('click', function () {
    var cur = document.documentElement.getAttribute('data-theme') || 'light';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('owp-theme', next); } catch (_) { /* storage is optional */ }
    drawAll();
  });
  try {
    var saved = localStorage.getItem('owp-theme');
    if (saved) { document.documentElement.setAttribute('data-theme', saved); }
  } catch (_) { /* storage is optional */ }

  // ------------------------------------------------------------------
  // Pages that follow the shared well filters

  var CLASS_LIST = ['liquid flow', 'pressure persists or rebuilds', 'flow at end of test', 'flow bled off', 'no flow', 'flow not reported', 'no tests on file'];
  var PROFILE_FILTERS = [
    ['county', 'County', function () { return uniq('County'); }, null],
    ['project', 'OWP project', function () { return uniq('Project'); }, null],
    ['tier', 'SRA tier', function () { return ['1', '2', '3', '4']; }, null],
    ['cls', 'Flow class, all tests', function () { return CLASS_LIST; }, null],
    ['clsLatest', 'Flow class, latest test', function () { return CLASS_LIST; }, null],
    ['di', 'DI community', function () { return ['Yes', 'No']; }, ['In a DI community', 'Outside DI communities']],
    ['fed', 'Federal/Tribal', function () { return ['fed', 'nonfed']; }, ['Federal/Tribal only', 'Exclude Federal/Tribal']]
  ];
  function uniq(key) {
    var seen = {};
    window.orphanWells.wells.forEach(function (w) { seen[w[key]] = 1; });
    return Object.keys(seen).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
  }
  function dropDeadCharts() {
    for (var i = CHARTS.length - 1; i >= 0; i--) { if (!document.contains(CHARTS[i].c)) { CHARTS.splice(i, 1); } }
  }

  // Well list in charts.  The charts count the wells that pass the filters,
  // the same wells the map and the well list show.
  function renderProfile() {
    var page = $('page-profile');
    var OW = window.orphanWells;
    var F = OW.filters;
    var all = OW.wells.length, shown = OW.shown().length;
    page.innerHTML = '';
    dropDeadCharts();
    var lead = document.createElement('p');
    lead.className = 'pagelead';
    lead.textContent = (shown === all ? 'Every chart on this page counts the ' + fmtInt(all) + ' wells on ECMC’s unplugged orphan list'
      : 'The charts count the ' + fmtInt(shown) + ' of ' + fmtInt(all) + ' wells that pass the filters') +
      ', the same wells as the map and the well list.  Values are as ECMC recorded them.  A well with a blank field is counted in a note under the chart and isn’t drawn as zero.';
    page.appendChild(lead);
    var bar = document.createElement('div');
    bar.className = 'controls noprint';
    bar.innerHTML = PROFILE_FILTERS.map(function (f) {
      var vals = f[2]();
      return '<label>' + f[1] + '<select data-f="' + f[0] + '"><option value="">All</option>' + vals.map(function (v, i) {
        return '<option value="' + esc(v) + '"' + (F[f[0]] === v ? ' selected' : '') + '>' + esc(f[3] ? f[3][i] : v) + '</option>';
      }).join('') + '</select></label>';
    }).join('') + '<button type="button" id="profclear">Clear filters</button>';
    page.appendChild(bar);
    Array.prototype.forEach.call(bar.querySelectorAll('select'), function (sel) {
      sel.addEventListener('change', function () { OW.setFilter(sel.getAttribute('data-f'), sel.value); });
    });
    $('profclear').onclick = OW.clearFilters;
    if (!shown) {
      var none = document.createElement('p');
      none.className = 'note';
      none.textContent = 'No wells pass these filters.';
      page.appendChild(none);
      return;
    }
    var host = document.createElement('div');
    host.className = 'cards';
    page.appendChild(host);
    wellCards().forEach(function (d) { renderCard(d, host); });
  }

  // Well sheet: a list of wells beside the sheet, so a well can be picked
  // without knowing its API number.  The list follows the filters.
  var browser = {q: '', top: 0, api: ''};
  function wellBrowser(api) {
    var page = $('page-well');
    var OW = window.orphanWells;
    browser.api = api || '';
    var old = $('wellnav');
    if (old) { browser.top = old.querySelector('.wellrows').scrollTop; }
    var main = document.createElement('div');
    main.id = 'wellmain';
    var kids = Array.prototype.filter.call(page.childNodes, function (n) { return !n.classList || !n.classList.contains('wellsplit'); });
    var stale = page.querySelector('.wellsplit');
    if (kids.length) {
      // The sheet was just rewritten into the page: wrap it beside a new list.
      kids.forEach(function (n) { main.appendChild(n); });
      if (stale) { page.removeChild(stale); }
      var split = document.createElement('div');
      split.className = 'wellsplit';
      var nav = document.createElement('aside');
      nav.id = 'wellnav';
      nav.className = 'noprint';
      split.appendChild(nav);
      split.appendChild(main);
      page.appendChild(split);
    }
    var navEl = $('wellnav');
    navEl.innerHTML = '<h3>Wells</h3><input type="search" id="wellnavq" placeholder="Name, API, county, project" value="' + esc(browser.q) + '">' +
      '<p class="note" id="wellnavcount"></p><div class="wellrows"></div>';
    function draw() {
      var q = browser.q.toLowerCase();
      var pool = OW.shown();
      var rows = pool.filter(function (w) {
        return !q || (w.API_10 + ' ' + w.WellName + ' ' + w.County + ' ' + w.Project).toLowerCase().indexOf(q) >= 0;
      });
      $('wellnavcount').textContent = fmtInt(rows.length) + ' of ' + fmtInt(OW.wells.length) + ' wells, in SRA rank order' +
        (pool.length < OW.wells.length ? '.  The filters above apply.' : '.');
      navEl.querySelector('.wellrows').innerHTML = rows.map(function (w) {
        return '<a href="#well=' + esc(w.API_10) + '"' + (w.API_10 === browser.api ? ' class="on"' : '') + '><b>' + esc(w.WellName) + '</b>' +
          '<span>' + esc(w.API_10) + ' · ' + esc(w.County) + ' · SRA tier ' + esc(w.Tier) + '</span></a>';
      }).join('') || '<p class="note">No wells match.</p>';
    }
    draw();
    var box = navEl.querySelector('.wellrows');
    box.scrollTop = browser.top;
    var on = box.querySelector('a.on');
    if (on) {
      var rel = on.getBoundingClientRect().top - box.getBoundingClientRect().top;
      if (rel < 0 || rel > box.clientHeight - 40) { box.scrollTop += rel - 80; }
    }
    $('wellnavq').addEventListener('input', function () { browser.q = this.value.trim(); draw(); });
  }

  function filtersChanged() {
    if (built.profile) { renderProfile(); requestAnimationFrame(drawAll); }
    if ($('wellnav')) { wellBrowser(browser.api); }
  }

  window.owpProgram = {show: show, titles: PAGE_TITLE, charts: CHARTS, redraw: drawAll, wellBrowser: wellBrowser, filtersChanged: filtersChanged};

})();
