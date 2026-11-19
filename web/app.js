/* Page code for docs/dashboard.html and docs/map.html.  build_dashboard.py
   inlines this file after the data, which arrives as global variables:
   MODE, META, WCOLS, W, ARCS, BG, DITYPES, COUNTY, and on the dashboard
   CASCOLS, CAS, CEMCOLS, CEM, TESTCOLS, TESTS.  On the dashboard,
   program.js is inlined first and draws the program pages; this file calls
   it through window.owpProgram.

   Nothing here estimates or fills in a value.  A blank in the tables is
   shown as a blank, with a label, and never as zero.  Ages are computed in
   the browser from the viewer's clock, so the generated page holds no
   build time. */
(function () {
  'use strict';

  var DASH = MODE === 'dashboard';
  var NOT_ON_CARD = 'not on the scout card';
  var NOT_REPORTED = 'not reported';
  var SCOUT_URL = 'https://ecmc.state.co.us/cogisdb/Facility/FacilityDetail?api=';
  var BH_URL = 'https://ecmc.state.co.us/cogisdb/Incidents/bradenheadScout.aspx?api=';
  var HALF_MILE_M = 804.672;
  var ONE_MILE_M = 1609.344;
  var MS_PER_DAY = 86400000;
  var README = META.repoUrl + '/blob/HEAD/README.md';

  var TIERS = [1, 2, 3, 4];
  var TIER_COLOR = {1: '#c00000', 2: '#ed7d31', 3: '#ffc000', 4: '#70ad47'};
  var TIER_RANGE = {
    1: META.tierCutoffs[0] + ' and above',
    2: META.tierCutoffs[1] + ' to under ' + META.tierCutoffs[0],
    3: META.tierCutoffs[2] + ' to under ' + META.tierCutoffs[1],
    4: 'under ' + META.tierCutoffs[2]
  };
  // The order is the README's convention for sorting, not an ECMC ranking.
  // The colors are categorical and avoid a red-to-green scale on purpose.
  var CLASSES = [
    'liquid flow',
    'pressure persists or rebuilds',
    'flow at end of test',
    'flow bled off',
    'no flow',
    'flow not reported',
    'no tests on file'
  ];
  var CLASS_COLOR = {
    'liquid flow': '#1f78b4',
    'pressure persists or rebuilds': '#ff7f00',
    'flow at end of test': '#c51b7d',
    'flow bled off': '#1b9e77',
    'no flow': '#f2f2f2',
    'flow not reported': '#8c8c8c',
    'no tests on file': '#ffffff'
  };
  var STATUS_NOTE =
    'Status is the code on the COGIS scout card.  It can differ from the ' +
    'well\u2019s place on ECMC\u2019s unplugged orphan list, so some wells on the list ' +
    'show PR (producing) or PA (plugged and abandoned).  ECMC’s code list governs.';
  var NOTICE =
    'This page compiles public ECMC records for reference.  It doesn’t ' +
    'replace ECMC’s files, the operator’s records, or a site-specific ' +
    'safety assessment, and it’s provided as is.';
  var SRA_NOTE =
    'Rank, tier, and score are Subsurface Risk Analytics’ priority score for ' +
    'this dataset.  ECMC sets its own plugging priorities, and the score isn’t ' +
    'ECMC’s ranking or a plugging order.';

  // ------------------------------------------------------------------
  // Data

  function toObjects(cols, rows) {
    return rows.map(function (r) {
      var o = {};
      for (var i = 0; i < cols.length; i++) { o[cols[i]] = r[i]; }
      return o;
    });
  }

  var wells = toObjects(WCOLS, W);
  var byApi = {};
  wells.forEach(function (w, i) {
    w.lat = parseFloat(w.Lat);
    w.lon = parseFloat(w.Lon);
    w.tier = parseInt(w.Tier, 10);
    w.idx = i;
    byApi[w.API_10] = w;
  });
  var TOTAL = wells.length;

  // ------------------------------------------------------------------
  // Helpers

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function blank(label) { return '<span class="blank">' + label + '</span>'; }

  // A value as recorded, or the blank label.  Never a zero for a blank.
  function show(v, label, unit) {
    if (v === '' || v === null || v === undefined) { return blank(label); }
    return esc(v) + (unit ? ' ' + unit : '');
  }

  function num(v) {
    if (v === '' || v === null || v === undefined) { return null; }
    var n = Number(String(v).replace(/,/g, ''));
    return isNaN(n) ? null : n;
  }

  function fmtInt(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

  // ECMC writes dates as M/D/YYYY.
  function parseMDY(s) {
    var m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(s || '');
    if (!m) { return null; }
    return new Date(Number(m[3]), Number(m[1]) - 1, Number(m[2]));
  }

  function wholeYearsSince(d, now) {
    var y = now.getFullYear() - d.getFullYear();
    var beforeAnniversary =
      now.getMonth() < d.getMonth() ||
      (now.getMonth() === d.getMonth() && now.getDate() < d.getDate());
    return beforeAnniversary ? y - 1 : y;
  }

  // Age in whole years from the spud date, or from the completion date when
  // the spud date is blank.  Dates are used as ECMC recorded them.  Nothing
  // is estimated when both are blank.
  function wellAge(w) {
    var now = new Date();
    var spud = parseMDY(w.spud_date);
    if (spud) {
      return {
        years: wholeYearsSince(spud, now),
        text: wholeYearsSince(spud, now) + ' yr (spud ' + w.spud_date + ')'
      };
    }
    var comp = parseMDY(w.completion_date);
    if (comp) {
      return {
        years: wholeYearsSince(comp, now),
        text: wholeYearsSince(comp, now) + ' yr (completed ' + w.completion_date +
          '; spud date ' + NOT_ON_CARD + ')'
      };
    }
    return {years: null, text: NOT_ON_CARD};
  }

  function yearsSinceText(mdy) {
    var d = parseMDY(mdy);
    return d ? String(wholeYearsSince(d, new Date())) : '';
  }

  function cogisId(api) { return api.slice(3, 6) + api.slice(7); }
  function scoutUrl(api) { return SCOUT_URL + cogisId(api); }
  function bhUrl(api) { return BH_URL + cogisId(api); }
  function sheetHref(api) { return (DASH ? '' : 'dashboard.html') + '#well=' + api; }
  function isoDay(s) { return (s || '').slice(0, 10); }

  function daysOld(iso) {
    var t = Date.parse(isoDay(iso) + 'T00:00:00Z');
    if (isNaN(t)) { return null; }
    return Math.max(0, Math.floor((Date.now() - t) / MS_PER_DAY));
  }

  function ageDaysText(iso) {
    var d = daysOld(iso);
    if (d === null) { return ''; }
    return d === 0 ? 'today' : d === 1 ? '1 day ago' : fmtInt(d) + ' days ago';
  }

  function el(id) { return document.getElementById(id); }

  function dot(color, hollow) {
    return '<span class="dot" style="background:' + color +
      (hollow ? ';border-color:#777' : '') + '"></span>';
  }

  function latestClassText(w) {
    if (w.bh_flow_class_latest === '') { return blank(NOT_REPORTED); }
    var when = w.bh_last_test_date ? ' (last test ' + esc(w.bh_last_test_date) + ')' : '';
    return esc(w.bh_flow_class_latest) + when;
  }

  // ------------------------------------------------------------------
  // Shared filters.  The map, the well list, and the summary rows all read
  // and write this one object.

  var F = {q: '', county: '', project: '', tier: '', cls: '', clsLatest: '', di: '', fed: ''};
  var FILTER_LABEL = {
    q: 'Search', county: 'County', project: 'Project', tier: 'SRA tier',
    cls: 'Flow class, all tests', clsLatest: 'Flow class, latest test',
    di: 'DI community', fed: 'Jurisdiction'
  };
  var FED_LABEL = {fed: 'Federal/Tribal only', nonfed: 'Federal/Tribal excluded'};

  function pass(w) {
    if (F.county && w.County !== F.county) { return false; }
    if (F.project && w.Project !== F.project) { return false; }
    if (F.tier && w.Tier !== F.tier) { return false; }
    if (F.cls && w.bh_flow_class !== F.cls) { return false; }
    if (F.clsLatest && w.bh_flow_class_latest !== F.clsLatest) { return false; }
    if (F.di && w.DI_Community_Nov2024 !== F.di) { return false; }
    if (F.fed === 'fed' && w.fed !== '1') { return false; }
    if (F.fed === 'nonfed' && w.fed === '1') { return false; }
    if (F.q) {
      var q = F.q.toLowerCase();
      var hay = (w.API_10 + ' ' + w.WellName + ' ' + w.Project).toLowerCase();
      if (hay.indexOf(q) < 0) { return false; }
    }
    return true;
  }

  function shownWells() { return wells.filter(pass); }

  function anyFilter() {
    for (var k in F) { if (F[k]) { return true; } }
    return false;
  }

  function clearFilters() {
    for (var k in F) { F[k] = ''; }
    filtersChanged();
  }

  function setFilter(key, value) {
    F[key] = value;
    filtersChanged();
  }

  function filtersChanged() {
    renderFilterBar();
    if (mapReady) { syncExclusionBoxes(); rebuildWells(); }
    if (DASH) {
      syncListControls();
      renderListBody();
      if (summaryBuilt) { summaryBuilt = false; buildSummary(); }
      if (recordsBuilt) { recordsBuilt = false; buildRecords(); }
      window.owpProgram.filtersChanged();
    }
  }

  function renderFilterBar() {
    var bar = el('filterbar');
    if (!DASH || !anyFilter()) { bar.className = ''; bar.innerHTML = ''; return; }
    var parts = [];
    for (var k in F) {
      if (!F[k]) { continue; }
      var v = k === 'fed' ? FED_LABEL[F[k]] : k === 'di' ? (F[k] === 'Yes' ? 'in a DI community' : 'outside DI communities') : F[k];
      parts.push(esc(FILTER_LABEL[k]) + ': <b>' + esc(v) + '</b>');
    }
    bar.className = 'on noprint';
    bar.innerHTML = 'Filters on the map and well list: ' + parts.join(' · ') +
      ' · showing ' + fmtInt(shownWells().length) + ' of ' + fmtInt(TOTAL) + ' wells' +
      '<button type="button" id="clearfilters">Clear filters</button>';
    el('clearfilters').onclick = clearFilters;
  }

  // ------------------------------------------------------------------
  // Frame: header, staleness banner, footer

  function renderFrame() {
    if (!DASH) { document.body.className = 'mapmode'; }
    el('pagetitle').textContent = DASH ? 'Colorado Orphaned Well Program' : 'Colorado unplugged orphaned wells';
    el('subtitle').innerHTML =
      fmtInt(TOTAL) + ' wells on ECMC’s Orphaned Well Program list as of ' +
      esc(isoDay(META.listRetrieved)) +
      ' · CDPHE EnviroScreen 2.0 block groups · DI communities as designated November 2024' +
      ' · Subsurface Risk Analytics' +
      (DASH ? '' : ' · <a style="color:#fff" href="dashboard.html">Open the dashboard</a>');
    el('notice').textContent = NOTICE;
    el('vintages').innerHTML =
      'Well list: ECMC OWP shapefile, retrieved ' + esc(isoDay(META.listRetrieved)) +
      ' · Block groups: CDPHE Colorado EnviroScreen 2.0, November 2024 DI designation, retrieved ' +
      esc(isoDay(META.bgRetrieved)) +
      ' · County outlines: ' + esc(META.countySource) +
      ' · Priority score: Subsurface Risk Analytics, not an ECMC ranking' +
      ' · Leaflet ' + esc(META.leafletVersion) + ' · Basemap tiles: Esri, USGS';
    renderStale();
  }

  // One banner entry per source.  A full refresh stamps every well with the
  // same date, so staleness is shown per source and not per well.
  function renderStale() {
    function source(label, oldest, newest, extra) {
      if (!oldest) { return '<span class="src">' + label + ': ' + blank('no date recorded') + '</span>'; }
      var d = daysOld(oldest);
      var range = newest && newest !== oldest ? esc(oldest) + ' to ' + esc(newest) + ', oldest ' : esc(oldest) + ', ';
      var old = d !== null && d > META.staleDays;
      return '<span class="src">' + label + ': ' +
        (old ? '<span class="old">' : '') + range + ageDaysText(oldest) +
        (old ? ', older than ' + META.staleDays + ' days</span>' : '') + (extra || '') + '</span>';
    }
    var missScout = META.scoutMissing ? ' (' + META.scoutMissing + ' not retrieved)' : '';
    var missBh = META.bhMissing ? ' (' + META.bhMissing + ' not retrieved)' : '';
    el('stale').innerHTML = 'Data as of → ' +
      source('ECMC well list retrieved', isoDay(META.listRetrieved), '', '') +
      (DASH
        ? source('COGIS scout cards saved', META.scoutOldest, META.scoutNewest, missScout) +
          source('COGIS bradenhead pages saved', META.bhOldest, META.bhNewest, missBh)
        : source('COGIS pages saved', META.scoutOldest < META.bhOldest ? META.scoutOldest : META.bhOldest, '', ''));
  }

  // ------------------------------------------------------------------
  // Map

  var map = null;
  var mapReady = false;
  var arcPts = null;
  var tierLayers = {};
  var bgLayer, diLayer, countyLayer, ringHalf, ringOne;
  var markers = [];
  var colorMode = 'tier';
  var legendDiv = null;
  var boxFed = null;
  var boxDI = null;
  // On a phone the layer list and legend start folded so the map is visible.
  var SMALL_SCREEN = window.innerWidth < 800 || window.innerHeight < 620;

  function esColor(p) {
    return p > 80 ? '#6a5fa8' : p > 60 ? '#8d84c0' : p > 40 ? '#b1abd5' : p > 20 ? '#d6d2e8' : '#ece9df';
  }

  // Coordinates arrive as integers in units of 0.00001 degree, each point
  // stored as its difference from the one before.
  function decodeLine(flat) {
    var lat = 0;
    var lon = 0;
    var pts = [];
    for (var i = 0; i < flat.length; i += 2) {
      lat += flat[i];
      lon += flat[i + 1];
      pts.push([lat / 1e5, lon / 1e5]);
    }
    return pts;
  }

  function decodeArcs() { arcPts = ARCS.map(decodeLine); }

  function ringLatLngs(refs) {
    var out = [];
    refs.forEach(function (ref) {
      var pts = ref >= 0 ? arcPts[ref] : arcPts[~ref].slice().reverse();
      for (var i = out.length ? 1 : 0; i < pts.length; i++) { out.push(pts[i]); }
    });
    return out;
  }

  function shapeLatLngs(polys) {
    return polys.map(function (rings) { return rings.map(ringLatLngs); });
  }

  function bgPopup(b) {
    var di = b[3] ? 'Yes · ' + esc(DITYPES[b[3]]) : 'No';
    return 'Block group ' + esc(b[0]) +
      '<br>EnviroScreen 2.0 percentile: ' + (b[1] === null ? blank('not published by CDPHE') : b[1].toFixed(1)) +
      '<br>Population: ' + (b[2] === null ? blank('not published by CDPHE') : fmtInt(b[2])) +
      '<br>DI community (November 2024): ' + di;
  }

  function wellTipLines(w) {
    return '<b>' + esc(w.WellName) + '</b><br>API ' + esc(w.API_10) +
      '<br>Age: ' + wellAge(w).text;
  }

  function wellPopup(w) {
    function row(k, v) { return '<tr><td>' + k + '</td><td>' + v + '</td></tr>'; }
    var html = '<div class="wellpop"><b class="name">' + esc(w.WellName) + '</b><br>API ' +
      esc(w.API_10) + '<br>Age: ' + wellAge(w).text + '<table>' +
      row('County', esc(w.County)) +
      row('OWP project', esc(w.Project)) +
      row('SRA rank', esc(w.Rank) + ' of ' + fmtInt(TOTAL)) +
      row('SRA score', esc(w.Priority_Score) + ' of 100') +
      row('SRA tier', esc(w.Tier)) +
      row('DI community', esc(w.DI_Community_Nov2024)) +
      row('Surface / minerals', esc(w.Surface) + ' / ' + esc(w.Minerals)) +
      row('Boundary flag', w.Boundary_Flag ? esc(w.Boundary_Flag) : 'none') +
      row('Flow class, all tests', esc(w.bh_flow_class)) +
      row('Flow class, latest test', latestClassText(w)) +
      '</table><span class="sra">The score is SRA’s, not an ECMC ranking.</span>' +
      '<div class="links">' +
      '<a href="' + sheetHref(w.API_10) + '"><b>Well sheet</b></a>' +
      '<a target="_blank" rel="noopener" href="' + scoutUrl(w.API_10) + '">COGIS scout card</a>' +
      '<a target="_blank" rel="noopener" href="' + bhUrl(w.API_10) + '">COGIS bradenhead page</a>' +
      '</div></div>';
    return html;
  }

  function markerStyle(w) {
    if (colorMode === 'tier') {
      var c = TIER_COLOR[w.tier];
      return {radius: 4.5, color: c, fillColor: c, fillOpacity: 0.7, opacity: 0.7, weight: 1};
    }
    var cls = colorMode === 'all' ? w.bh_flow_class : w.bh_flow_class_latest;
    return {
      radius: 4.5, color: '#333', weight: 1, opacity: 0.9,
      fillColor: CLASS_COLOR[cls] || '#ffffff', fillOpacity: 0.9
    };
  }

  // Redraw the wells that pass the filters, then the counts, rings, and
  // legend.  Everything that shows a count reads it from here.
  function rebuildWells() {
    var counts = {1: 0, 2: 0, 3: 0, 4: 0};
    TIERS.forEach(function (t) { tierLayers[t].clearLayers(); });
    markers = [];
    wells.forEach(function (w) {
      if (!pass(w)) { return; }
      counts[w.tier]++;
      var m = L.circleMarker([w.lat, w.lon], markerStyle(w));
      m.bindTooltip(wellTipLines(w), {sticky: true, className: 'welltip'});
      m.on('click', function () {
        L.popup({maxWidth: 340}).setLatLng([w.lat, w.lon]).setContent(wellPopup(w)).openOn(map);
      });
      m.well = w;
      m.addTo(tierLayers[w.tier]);
      markers.push(m);
    });
    TIERS.forEach(function (t) {
      var span = el('tiercnt' + t);
      if (span) { span.textContent = fmtInt(counts[t]); }
    });
    rebuildRings();
    renderLegend(counts);
  }

  // Rings follow what's on the map: a well hidden by a filter or by its
  // tier checkbox has no ring.  L.circle takes its radius in meters.
  function rebuildRings() {
    var specs = [
      [ringHalf, HALF_MILE_M, '6 5'],
      [ringOne, ONE_MILE_M, '1 5']
    ];
    specs.forEach(function (spec) {
      var group = spec[0];
      group.clearLayers();
      if (!map.hasLayer(group)) { return; }
      markers.forEach(function (m) {
        if (!map.hasLayer(tierLayers[m.well.tier])) { return; }
        L.circle([m.well.lat, m.well.lon], {
          radius: spec[1], color: '#444', weight: 1, opacity: 0.7, dashArray: spec[2],
          fillColor: '#444', fillOpacity: 0.05, interactive: false
        }).addTo(group);
      });
    });
    restack();
  }

  // Keep the shading under everything and the wells on top, whatever order
  // the layers were switched on in.
  function restack() {
    if (map.hasLayer(bgLayer)) { bgLayer.eachLayer(function (l) { l.bringToBack(); }); }
    markers.forEach(function (m) { if (map.hasLayer(m)) { m.bringToFront(); } });
  }

  function renderLegend(tierCounts) {
    if (!legendDiv) { return; }
    var shown = markers.length;
    var html =
      '<h4>EnviroScreen 2.0 percentile</h4>' +
      '<span class="swatch" style="background:#6a5fa8"></span>over 80 to 100<br>' +
      '<span class="swatch" style="background:#8d84c0"></span>over 60 to 80<br>' +
      '<span class="swatch" style="background:#b1abd5"></span>over 40 to 60<br>' +
      '<span class="swatch" style="background:#d6d2e8"></span>over 20 to 40<br>' +
      '<span class="swatch" style="background:#ece9df"></span>0 to 20<br>' +
      '<span class="swatch" style="background:#d9d9d9;border-style:dashed"></span>Tribal jurisdiction<br>' +
      '<span class="swatch" style="background:none;border:2px solid #c00000"></span>DI community, November 2024';
    if (colorMode === 'tier') {
      html += '<h4>Wells by SRA priority tier</h4>';
      TIERS.forEach(function (t) {
        html += dot(TIER_COLOR[t]) + 'Tier ' + t + ', ' + TIER_RANGE[t] +
          ' (<span>' + fmtInt(tierCounts[t]) + '</span>)<br>';
      });
    } else {
      var key = colorMode === 'all' ? 'bh_flow_class' : 'bh_flow_class_latest';
      var counts = {};
      markers.forEach(function (m) { counts[m.well[key]] = (counts[m.well[key]] || 0) + 1; });
      html += '<h4>Wells by bradenhead flow class, ' +
        (colorMode === 'all' ? 'all tests on file' : 'latest test only') + '</h4>';
      CLASSES.forEach(function (c) {
        html += dot(CLASS_COLOR[c], c === 'no tests on file') + esc(c) +
          ' (' + fmtInt(counts[c] || 0) + ')<br>';
      });
      html += '<span class="sra">The classes sort test records.  They aren’t an ECMC finding or a hazard rating.</span><br>';
    }
    html += 'Total on the map: <b id="legtot">' + fmtInt(shown) + '</b> of ' + fmtInt(TOTAL) + ' wells';
    html += '<h4>Distance from a well</h4>' +
      '<span class="ringkey" style="border:1px dashed #444"></span>Half-mile radius<br>' +
      '<span class="ringkey" style="border:1px dotted #444"></span>One-mile radius';
    if (colorMode === 'tier') {
      html += '<br><span class="sra">Tiers are SRA’s score, not an ECMC ranking.</span>';
    }
    var wasOpen = legendDiv.firstChild ? legendDiv.firstChild.open : !SMALL_SCREEN;
    legendDiv.innerHTML = '<details' + (wasOpen ? ' open' : '') + '><summary>Legend</summary>' + html + '</details>';
  }

  function syncExclusionBoxes() {
    if (boxFed) { boxFed.checked = F.fed === 'nonfed'; }
    if (boxDI) { boxDI.checked = F.di === 'Yes'; }
  }

  function addExclusionFilters(layerCtl) {
    var nFed = wells.filter(function (w) { return w.fed === '1'; }).length;
    var nNonDI = wells.filter(function (w) { return w.DI_Community_Nov2024 !== 'Yes'; }).length;
    // Inside the control's list, so the filters fold away with it when the
    // control is collapsed on a small screen.
    var host = layerCtl.getContainer().querySelector('.leaflet-control-layers-list') || layerCtl.getContainer();
    var d = document.createElement('div');
    d.className = 'exfilters';
    function box(text, onChange) {
      var label = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.addEventListener('change', function () { onChange(cb.checked); });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + text));
      d.appendChild(label);
      return cb;
    }
    boxFed = box('Exclude Federal/Tribal wells (' + fmtInt(nFed) + ')', function (on) {
      setFilter('fed', on ? 'nonfed' : '');
    });
    boxDI = box('Exclude wells outside DI communities (' + fmtInt(nNonDI) + ')', function (on) {
      setFilter('di', on ? 'Yes' : '');
    });
    host.appendChild(d);
    // disableClickPropagation lives on L.DomEvent.  The August build called
    // it on L.DomUtil, which threw and took the filters and legend with it.
    if (L.DomEvent && L.DomEvent.disableClickPropagation) {
      L.DomEvent.disableClickPropagation(d);
    }
  }

  function addColorModeControl() {
    var ctl = L.control({position: 'topleft'});
    ctl.onAdd = function () {
      var d = L.DomUtil.create('div', 'colormode');
      d.innerHTML = '<h4>Color wells by</h4>' +
        '<label><input type="radio" name="colormode" value="tier" checked> SRA priority tier</label>' +
        '<label><input type="radio" name="colormode" value="all"> Flow class, all tests on file</label>' +
        '<label><input type="radio" name="colormode" value="latest"> Flow class, latest test only</label>';
      Array.prototype.forEach.call(d.querySelectorAll('input'), function (input) {
        input.addEventListener('change', function () {
          if (input.checked) { colorMode = input.value; rebuildWells(); }
        });
      });
      if (L.DomEvent && L.DomEvent.disableClickPropagation) {
        L.DomEvent.disableClickPropagation(d);
      }
      return d;
    };
    ctl.addTo(map);
  }

  function initMap() {
    if (mapReady) { return; }
    decodeArcs();
    map = L.map('map', {preferCanvas: true}).setView([39.3, -105.5], 7);

    var esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
    var esriAttr = 'Tiles &copy; Esri';
    function tiles(url, attr) { return L.tileLayer(url, {attribution: attr, opacity: 0.55, maxZoom: 18}); }
    var baseMaps = {
      'Esri World Topo': tiles(esri + 'World_Topo_Map/MapServer/tile/{z}/{y}/{x}', esriAttr),
      'Esri Light Gray': tiles(esri + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', esriAttr),
      'Esri Street': tiles(esri + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}', esriAttr),
      'Esri Imagery': tiles(esri + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', esriAttr),
      'USGS Topo': L.tileLayer(
        'https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}',
        {attribution: 'Tiles: USGS The National Map', opacity: 0.55, maxZoom: 16})
    };
    baseMaps['Esri World Topo'].addTo(map);

    bgLayer = L.layerGroup();
    diLayer = L.layerGroup();
    BG.forEach(function (b) {
      var shape = shapeLatLngs(b[5]);
      var style = {color: '#8c8c8c', weight: 0.5, fillColor: esColor(b[1] === null ? 0 : b[1]), fillOpacity: 0.55};
      if (b[4]) { style.dashArray = '2 3'; style.color = '#555'; style.fillColor = '#d9d9d9'; }
      L.polygon(shape, style).bindPopup(function () { return bgPopup(b); }).addTo(bgLayer);
      if (b[3]) {
        L.polygon(shape, {color: '#c00000', weight: 1.4, fill: false, interactive: false}).addTo(diLayer);
      }
    });
    countyLayer = L.layerGroup();
    L.polyline(COUNTY.map(decodeLine),
      {color: '#333', weight: 1.6, fill: false, interactive: false}).addTo(countyLayer);

    TIERS.forEach(function (t) { tierLayers[t] = L.layerGroup(); });
    ringHalf = L.layerGroup();
    ringOne = L.layerGroup();

    bgLayer.addTo(map);
    diLayer.addTo(map);
    TIERS.forEach(function (t) { tierLayers[t].addTo(map); });

    var overlays = {};
    overlays['EnviroScreen 2.0 block groups'] = bgLayer;
    overlays['DI community outlines, November 2024'] = diLayer;
    overlays['County outlines'] = countyLayer;
    TIERS.forEach(function (t) {
      overlays['SRA tier ' + t + ' wells (<span id="tiercnt' + t + '"></span>)'] = tierLayers[t];
    });
    overlays['Half-mile radius'] = ringHalf;
    overlays['One-mile radius'] = ringOne;
    var layerCtl = L.control.layers(baseMaps, overlays, {collapsed: SMALL_SCREEN, position: 'topright'}).addTo(map);
    addExclusionFilters(layerCtl);

    var legend = L.control({position: 'bottomleft'});
    legend.onAdd = function () {
      legendDiv = L.DomUtil.create('div', 'maplegend');
      if (L.DomEvent && L.DomEvent.disableClickPropagation) {
        L.DomEvent.disableClickPropagation(legendDiv);
      }
      return legendDiv;
    };
    legend.addTo(map);
    if (DASH) { addColorModeControl(); }

    map.on('overlayadd overlayremove', function () { rebuildRings(); });
    mapReady = true;
    syncExclusionBoxes();
    rebuildWells();
    // For checks from the browser console, such as map.distance on a ring.
    window.orphanWellMap = {
      map: map, tierLayers: tierLayers, ringHalf: ringHalf, ringOne: ringOne,
      markers: function () { return markers; }
    };
  }

  // ------------------------------------------------------------------
  // Well list

  function scoutCell(v, unit) { return show(v, NOT_ON_CARD, unit); }
  function bhCell(v) { return show(v, NOT_REPORTED); }

  var LIST_COLS = [
    {key: 'Rank', label: 'SRA rank', num: true, html: function (w) { return esc(w.Rank); }},
    {key: 'Tier', label: 'SRA tier', num: true, html: function (w) { return esc(w.Tier); }},
    {key: 'Priority_Score', label: 'SRA score', num: true, html: function (w) { return esc(w.Priority_Score); }},
    {key: 'API_10', label: 'API', nw: true, html: function (w) { return '<a href="#well=' + esc(w.API_10) + '">' + esc(w.API_10) + '</a>'; }},
    {key: 'WellName', label: 'Well name', html: function (w) { return esc(w.WellName); }},
    {key: 'Project', label: 'OWP project', html: function (w) { return esc(w.Project); }},
    {key: 'County', label: 'County', html: function (w) { return esc(w.County); }},
    {key: 'well_status', label: 'Status', html: function (w) { return scoutCell(w.well_status); }},
    {key: 'age', label: 'Age', num: true, nw: true,
      value: function (w) { var a = wellAge(w).years; return a === null ? '' : String(a); },
      html: function (w) { var a = wellAge(w); return a.years === null ? blank(a.text) : esc(a.text); }},
    {key: 'measured_td_ft', label: 'Measured TD, ft', num: true, html: function (w) { return scoutCell(w.measured_td_ft); }},
    {key: 'pb_depth_ft', label: 'Plugback depth, ft', num: true, html: function (w) { return scoutCell(w.pb_depth_ft); }},
    {key: 'surf_casing_size_in', label: 'Surface casing size, in', num: true, html: function (w) { return scoutCell(w.surf_casing_size_in); }},
    {key: 'surf_casing_depth_ft', label: 'Surface casing depth, ft', num: true, html: function (w) { return scoutCell(w.surf_casing_depth_ft); }},
    {key: 'n_casing_strings', label: 'Casing strings run', num: true, html: function (w) { return scoutCell(w.n_casing_strings); }},
    {key: 'bh_last_test_date', label: 'Last bradenhead test', date: true, nw: true,
      html: function (w) { return w.bh_test_count === '0' ? blank('no tests on file') : bhCell(w.bh_last_test_date); }},
    {key: 'bh_flow_class_latest', label: 'Flow class, latest test', html: function (w) { return bhCell(w.bh_flow_class_latest); }},
    {key: 'bh_flow_class', label: 'Flow class, all tests', html: function (w) { return bhCell(w.bh_flow_class); }},
    {key: 'bh_max_surf_casing_psi', label: 'Highest surface casing pressure, psi', num: true,
      html: function (w) { return w.bh_test_count === '0' ? blank('no tests on file') : bhCell(w.bh_max_surf_casing_psi); }},
    {key: 'fetched_at', label: 'Scout card as of', html: function (w) { return show(w.fetched_at, 'not retrieved'); }},
    {key: 'bh_fetched_at', label: 'Bradenhead page as of', html: function (w) { return show(w.bh_fetched_at, 'not retrieved'); }}
  ];
  var listSort = {key: 'Rank', dir: 1};
  var listBuilt = false;

  function colValue(col, w) { return col.value ? col.value(w) : w[col.key]; }

  function sortKey(col, w) {
    var v = colValue(col, w);
    if (v === '' || v === null || v === undefined) { return null; }
    if (col.num) { return num(v); }
    if (col.date) { var d = parseMDY(v); return d ? d.getTime() : null; }
    return String(v).toLowerCase();
  }

  // Blanks sort last in either direction, so they never pose as the lowest value.
  function sortedShown() {
    var col = LIST_COLS.filter(function (c) { return c.key === listSort.key; })[0];
    var rows = shownWells().map(function (w) { return {w: w, k: sortKey(col, w)}; });
    rows.sort(function (a, b) {
      if (a.k === null && b.k === null) { return a.w.idx - b.w.idx; }
      if (a.k === null) { return 1; }
      if (b.k === null) { return -1; }
      if (a.k < b.k) { return -listSort.dir; }
      if (a.k > b.k) { return listSort.dir; }
      return a.w.idx - b.w.idx;
    });
    return rows.map(function (r) { return r.w; });
  }

  function uniqueSorted(key) {
    var seen = {};
    wells.forEach(function (w) { seen[w[key]] = true; });
    return Object.keys(seen).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
  }

  function options(values, labels) {
    return '<option value="">All</option>' + values.map(function (v, i) {
      return '<option value="' + esc(v) + '">' + esc(labels ? labels[i] : v) + '</option>';
    }).join('');
  }

  function buildList() {
    if (listBuilt) { return; }
    listBuilt = true;
    el('page-list').innerHTML =
      '<h2>Well list</h2>' +
      '<p class="note">' + esc(SRA_NOTE) + '</p>' +
      '<div class="controls noprint">' +
      '<label>Search API, name, or project<input type="search" id="f-q" size="26"></label>' +
      '<label>County<select id="f-county">' + options(uniqueSorted('County')) + '</select></label>' +
      '<label>OWP project<select id="f-project">' + options(uniqueSorted('Project')) + '</select></label>' +
      '<label>SRA tier<select id="f-tier">' + options(['1', '2', '3', '4']) + '</select></label>' +
      '<label>Flow class, all tests<select id="f-cls">' + options(CLASSES) + '</select></label>' +
      '<label>Flow class, latest test<select id="f-clsLatest">' + options(CLASSES) + '</select></label>' +
      '<label>DI community<select id="f-di">' + options(['Yes', 'No'], ['In a DI community', 'Outside DI communities']) + '</select></label>' +
      '<label>Federal/Tribal<select id="f-fed">' + options(['fed', 'nonfed'], ['Federal/Tribal only', 'Exclude Federal/Tribal']) + '</select></label>' +
      '<button type="button" id="f-clear">Clear filters</button>' +
      '<button type="button" id="f-export">Export these rows to CSV</button>' +
      '</div>' +
      '<p id="listcount"></p>' +
      '<p class="note">' + esc(STATUS_NOTE) + '  Blanks are shown as “' + NOT_ON_CARD +
      '” or “' + NOT_REPORTED + '” and sort last.  Age is whole years from the spud date, ' +
      'or from the completion date when the card has no spud date.  A latest-test flow class describes ' +
      'the test on the date in the column beside it, which can be years old.</p>' +
      '<div class="tablewrap"><table class="data" id="listtable"><thead></thead><tbody></tbody></table></div>';
    ['county', 'project', 'tier', 'cls', 'clsLatest', 'di', 'fed'].forEach(function (k) {
      el('f-' + k).addEventListener('change', function () { setFilter(k, this.value); });
    });
    el('f-q').addEventListener('input', function () { setFilter('q', this.value.trim()); });
    el('f-clear').onclick = clearFilters;
    el('f-export').onclick = exportCsv;
    renderListHead();
    renderListBody();
  }

  function syncListControls() {
    if (!listBuilt) { return; }
    ['county', 'project', 'tier', 'cls', 'clsLatest', 'di', 'fed'].forEach(function (k) {
      el('f-' + k).value = F[k];
    });
    if (el('f-q').value.trim() !== F.q) { el('f-q').value = F.q; }
  }

  function renderListHead() {
    var tr = '<tr>' + LIST_COLS.map(function (c) {
      var arrow = c.key === listSort.key ? ' <span class="arrow">' + (listSort.dir > 0 ? '▲' : '▼') + '</span>' : '';
      return '<th class="sortable' + (c.num ? ' num' : '') + '" data-key="' + c.key + '">' + esc(c.label) + arrow + '</th>';
    }).join('') + '</tr>';
    var thead = el('listtable').tHead;
    thead.innerHTML = tr;
    Array.prototype.forEach.call(thead.querySelectorAll('th'), function (th) {
      th.onclick = function () {
        var key = th.getAttribute('data-key');
        listSort = {key: key, dir: listSort.key === key ? -listSort.dir : 1};
        renderListHead();
        renderListBody();
      };
    });
  }

  function renderListBody() {
    if (!listBuilt) { return; }
    var rows = sortedShown();
    el('listcount').innerHTML = 'Showing <b>' + fmtInt(rows.length) + '</b> of ' + fmtInt(TOTAL) + ' wells.';
    el('listtable').tBodies[0].innerHTML = rows.map(function (w) {
      return '<tr>' + LIST_COLS.map(function (c) {
        return '<td class="' + (c.num ? 'num' : '') + (c.nw ? ' nw' : '') + '">' + c.html(w) + '</td>';
      }).join('') + '</tr>';
    }).join('');
  }

  function csvCell(v) {
    var s = v === null || v === undefined ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  // The export holds the same rows and columns as the table.  Blank cells
  // stay blank in the file.
  function listCsv() {
    var lines = [LIST_COLS.map(function (c) { return csvCell(c.label); }).join(',')];
    sortedShown().forEach(function (w) {
      lines.push(LIST_COLS.map(function (c) { return csvCell(colValue(c, w)); }).join(','));
    });
    return lines.join('\r\n') + '\r\n';
  }

  function exportCsv() {
    var blob = new Blob([listCsv()], {type: 'text/csv;charset=utf-8'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'colorado_orphan_wells_filtered.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  // ------------------------------------------------------------------
  // Well sheet

  function kv(k, v) { return '<div class="kv"><span class="k">' + k + '</span><span class="v">' + v + '</span></div>'; }

  function isRunString(c) {
    return (c.citings_type === 'ACTUAL' || c.citings_type === 'HISTORICAL') && c.is_casing_string === 'Y';
  }

  function casingTable(rows) {
    var head = ['#', 'Citings type', 'String', 'Hole size, in', 'Casing size, in', 'Top, ft', 'Depth, ft',
      'Weight', 'Cement top, ft', 'Cement bottom, ft', 'Cement sacks', 'Cement top method'];
    return '<div class="tablewrap short"><table class="data"><thead><tr>' +
      head.map(function (h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (c) {
        return '<tr><td class="num">' + esc(c.seq) + '</td><td>' + scoutCell(c.citings_type) + '</td><td>' +
          scoutCell(c.string_type) + '</td><td class="num">' + scoutCell(c.hole_size_in) + '</td><td class="num">' +
          scoutCell(c.casing_size_in) + '</td><td class="num">' + scoutCell(c.top_ft) + '</td><td class="num">' +
          scoutCell(c.depth_ft) + '</td><td>' + scoutCell(c.weight) + '</td><td class="num">' +
          scoutCell(c.cement_top_ft) + '</td><td class="num">' + scoutCell(c.cement_bottom_ft) + '</td><td class="num">' +
          scoutCell(c.cement_sacks) + '</td><td>' + scoutCell(c.cement_method) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function flagText(v, noTests) {
    if (noTests) { return blank('no tests on file'); }
    if (v === 'Y') { return 'Yes'; }
    if (v === 'N') { return 'No'; }
    if (v === 'U') { return 'Can’t be determined from the records'; }
    return blank(NOT_REPORTED);
  }

  function sheetPicker(current) {
    return '<div class="controls noprint">' +
      '<label>Open a well by API number or name' +
      '<input type="text" id="wellpick" list="welloptions" size="40" placeholder="05-125-02377 or a well name" value="' +
      esc(current || '') + '"></label>' +
      '<datalist id="welloptions">' + wells.map(function (w) {
        return '<option value="' + esc(w.API_10) + '">' + esc(w.WellName) + '</option>';
      }).join('') + '</datalist>' +
      '<button type="button" id="wellgo">Open</button>' +
      '<button type="button" id="wellprev">Previous by SRA rank</button>' +
      '<button type="button" id="wellnext">Next by SRA rank</button>' +
      '<button type="button" id="wellprint">Print this sheet</button>' +
      '</div>';
  }

  function findWell(text) {
    var t = text.trim();
    if (byApi[t]) { return byApi[t]; }
    var low = t.toLowerCase();
    var hits = wells.filter(function (w) {
      return w.WellName.toLowerCase() === low || w.API_10.replace(/-/g, '') === t.replace(/-/g, '');
    });
    if (hits.length === 1) { return hits[0]; }
    hits = wells.filter(function (w) { return w.WellName.toLowerCase().indexOf(low) >= 0; });
    return hits.length === 1 ? hits[0] : null;
  }

  function bindPicker(w) {
    function go() {
      var hit = findWell(el('wellpick').value);
      if (hit) { location.hash = '#well=' + hit.API_10; } else {
        el('pickmsg').textContent = 'No single well matches that.  Pick one from the list.';
      }
    }
    el('wellgo').onclick = go;
    el('wellpick').addEventListener('change', go);
    el('wellprev').disabled = !w || w.idx === 0;
    el('wellnext').disabled = !w || w.idx === wells.length - 1;
    el('wellprev').onclick = function () { location.hash = '#well=' + wells[w.idx - 1].API_10; };
    el('wellnext').onclick = function () { location.hash = '#well=' + wells[w.idx + 1].API_10; };
    el('wellprint').disabled = !w;
    el('wellprint').onclick = function () { window.print(); };
  }

  function renderSheet(api) {
    var page = el('page-well');
    var w = api ? byApi[api] : null;
    if (!w) {
      page.innerHTML = '<h2>Well sheet</h2>' + sheetPicker(api) +
        '<p id="pickmsg" class="note">' + (api ? 'No well on the current list has the API number ' + esc(api) + '.' :
        'Pick a well here, or click a well on the map or an API number in the well list.') + '</p>';
      bindPicker(null);
      window.owpProgram.wellBrowser(api);
      return;
    }
    var age = wellAge(w);
    var casing = toObjects(CASCOLS, CAS[w.API_10] || []);
    var run = casing.filter(isRunString);
    var other = casing.filter(function (c) { return !isRunString(c); });
    var cement = toObjects(CEMCOLS, CEM[w.API_10] || []);
    var tests = toObjects(TESTCOLS, TESTS[w.API_10] || []);
    var noTests = w.bh_test_count === '0' || w.bh_test_count === '';
    var html = sheetPicker(w.API_10) + '<p id="pickmsg" class="note noprint"></p><div class="sheet">';

    html += '<div class="sheethead"><h2>' + esc(w.WellName) + '</h2><span>API ' + esc(w.API_10) +
      '</span><span>' + esc(w.County) + ' County</span><span>' + esc(w.Project) + '</span></div>';
    html += '<p class="links">' +
      '<a class="printurl" target="_blank" rel="noopener" data-url="' + scoutUrl(w.API_10) + '" href="' + scoutUrl(w.API_10) + '">Live COGIS scout card</a>' +
      '<a class="printurl" target="_blank" rel="noopener" data-url="' + bhUrl(w.API_10) + '" href="' + bhUrl(w.API_10) + '">Live COGIS bradenhead page</a>' +
      '<span class="note">Check the live pages before acting on anything here.</span></p>';

    html += '<h3>Identity and location</h3><div class="grid">' +
      kv('API number', esc(w.API_10)) +
      kv('Well name', esc(w.WellName)) +
      kv('OWP project', esc(w.Project)) +
      kv('ECMC site ID', show(w.SiteID, NOT_REPORTED) + (w.TypeID ? ' (' + esc(w.TypeID) + ')' : '')) +
      kv('County', esc(w.County)) +
      kv('Latitude, NAD83', esc(w.Lat)) +
      kv('Longitude, NAD83', esc(w.Lon)) +
      kv('Surface', show(w.Surface, NOT_REPORTED)) +
      kv('Minerals', show(w.Minerals, NOT_REPORTED)) +
      kv('Tank battery', show(w.TankBattery, NOT_REPORTED)) +
      '</div><p class="note">Coordinates and ownership are as ECMC publishes them on the Orphaned Well Program list.</p>';

    html += '<h3>Priority (Subsurface Risk Analytics score, not an ECMC ranking)</h3><div class="grid">' +
      kv('SRA rank', esc(w.Rank) + ' of ' + fmtInt(TOTAL)) +
      kv('SRA tier', esc(w.Tier) + ' (score ' + TIER_RANGE[w.tier] + ')') +
      kv('SRA score', esc(w.Priority_Score) + ' of 100') +
      kv('Community burden', esc(w.Score_Community) + ' of 40') +
      kv('Population exposure', esc(w.Score_Exposure) + ' of 30') +
      kv('Deliverability', esc(w.Score_Deliverability) + ' of 30') +
      kv('DI community, November 2024', esc(w.DI_Community_Nov2024)) +
      kv('DI type', w.DI_Type ? esc(w.DI_Type) : (w.DI_Community_Nov2024 === 'Yes' ? blank(NOT_REPORTED) : 'not a DI community')) +
      kv('DI criteria met', w.DI_Criteria_Count ? esc(w.DI_Criteria_Count) + ' of 7' : (w.DI_Community_Nov2024 === 'Yes' ? blank(NOT_REPORTED) : 'not a DI community')) +
      kv('EnviroScreen 2.0 percentile', show(w.EnviroScreen2_Pctl, 'no block group')) +
      kv('Census block group', show(w.BG_GEOID, 'no block group')) +
      kv('Block group population', show(w.BG_Pop, 'no block group')) +
      kv('Same-project wells within 5 km', esc(w.Cluster_Size_5km)) +
      kv('Boundary flag', w.Boundary_Flag ? esc(w.Boundary_Flag) : 'none') +
      kv('Federal/Tribal for the map filter', w.fed === '1' ? 'Yes' : 'No') +
      '</div><p class="note">' + esc(SRA_NOTE) + '  <a href="' + README + '#ranked-well-list" target="_blank" rel="noopener">How the score is built</a>.</p>';

    html += '<h3>Wellbore, from the COGIS scout card</h3>';
    if (w.fetched !== 'True') {
      html += '<p class="gaps">The scout card for this well wasn’t retrieved, so the fields below are blank.</p>';
    }
    html += '<div class="grid">' +
      kv('Status', scoutCell(w.well_status)) +
      kv('Status date', scoutCell(w.status_date)) +
      kv('Spud date', scoutCell(w.spud_date)) +
      kv('Completion date', scoutCell(w.completion_date)) +
      kv('Age', age.years === null ? blank(age.text) : esc(age.text)) +
      kv('Measured TD', scoutCell(w.measured_td_ft, 'ft')) +
      kv('Vertical TD', scoutCell(w.vertical_td_ft, 'ft')) +
      kv('Plugback depth', scoutCell(w.pb_depth_ft, 'ft')) +
      kv('Elevation', scoutCell(w.elevation_ft, 'ft')) +
      kv('Casing strings run', scoutCell(w.n_casing_strings)) +
      kv('Deepest run surface casing, size', scoutCell(w.surf_casing_size_in, 'in')) +
      kv('Deepest run surface casing, depth', scoutCell(w.surf_casing_depth_ft, 'ft')) +
      '</div><p class="note">' + esc(STATUS_NOTE) + '  A plugback depth of 0 means the card lists 0.  Dates are as ECMC recorded them, including any spud date later than the completion date.</p>';

    html += '<h3>Casing and cement: strings run (citings type ACTUAL or HISTORICAL)</h3>';
    html += run.length ? casingTable(run) :
      '<p>' + blank(casing.length ? 'No run casing string is on the scout card.' : 'No casing records are on the scout card.') + '</p>';
    if (other.length) {
      html += '<h3>Planned strings and records that aren’t a string of pipe</h3>' +
        '<p class="note">PLANNED records come from the drilling permit and weren’t necessarily run.  OPEN HOLE, STAGE TOOL, and S.C. records aren’t strings of pipe.</p>' +
        casingTable(other);
    }
    html += '<h3>Additional cement</h3>';
    if (cement.length) {
      html += '<div class="tablewrap short"><table class="data"><thead><tr><th>#</th><th>String</th><th>Top, ft</th><th>Depth, ft</th><th>Bottom, ft</th><th>Sacks</th><th>Method</th></tr></thead><tbody>' +
        cement.map(function (c) {
          return '<tr><td class="num">' + esc(c.seq) + '</td><td>' + scoutCell(c.string_type) + '</td><td class="num">' +
            scoutCell(c.top_ft) + '</td><td class="num">' + scoutCell(c.depth_ft) + '</td><td class="num">' +
            scoutCell(c.bottom_ft) + '</td><td class="num">' + scoutCell(c.sacks) + '</td><td>' + scoutCell(c.method) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    } else {
      html += '<p>' + blank('No additional cement records are on the scout card.') + '</p>';
    }

    html += '<h3>Bradenhead tests, from the COGIS bradenhead page</h3>';
    if (noTests) {
      html += '<p>' + blank('No bradenhead tests are on file for this well.') + '</p>';
    } else {
      html += '<div class="grid">' +
        kv('Tests on file', esc(w.bh_test_count)) +
        kv('First test', bhCell(w.bh_first_test_date)) +
        kv('Latest test', bhCell(w.bh_last_test_date) + (yearsSinceText(w.bh_last_test_date) !== '' ? ' (' + yearsSinceText(w.bh_last_test_date) + ' yr ago)' : '')) +
        kv('Latest test, flow at start', bhCell(w.bh_last_flow_start)) +
        kv('Latest test, flow at end', bhCell(w.bh_last_flow_end)) +
        kv('Latest test, end surface casing pressure', show(w.bh_last_end_surf_casing_psi, NOT_REPORTED, 'psi')) +
        kv('Latest test, fluid', bhCell(w.bh_last_fluid)) +
        kv('Highest surface casing pressure on record', show(w.bh_max_surf_casing_psi, 'no numeric reading', 'psi')) +
        kv('Flow class, all tests', bhCell(w.bh_flow_class)) +
        kv('Flow class, latest test', latestClassText(w)) +
        '</div><h3>Flags across all tests on file</h3><div class="grid">' +
        kv('Any flow observed', flagText(w.bh_any_flow_observed)) +
        kv('Liquid flow', flagText(w.bh_liquid_flow)) +
        kv('Flow at end of a test', flagText(w.bh_flow_at_end)) +
        kv('Pressure not bled to zero', flagText(w.bh_not_bled_to_zero)) +
        kv('Pressure rebuilt between tests', flagText(w.bh_pressure_rebuild)) +
        '</div>';
    }
    html += '<p class="note">The flags and classes sort what the tests recorded.  The pressure flags use 0 psi, which is stricter than the Rule 419 action thresholds in most of the state, and no class is an ECMC compliance finding or a hazard rating.  <a href="#about=flags">Definitions and limits</a>.</p>';
    if (tests.length) {
      html += '<h3>Test history, in the order ECMC lists it</h3><div class="tablewrap short"><table class="data"><thead><tr>' +
        ['Test date', 'Submitted', 'Report', 'Document', 'Well status', 'Surface casing psi, start', 'Surface casing psi, end',
          'Production casing psi, start', 'Production casing psi, end', 'Flow, start', 'Flow, end', 'Fluid', 'Sample taken', 'Operator comments']
          .map(function (h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead><tbody>' +
        tests.map(function (t) {
          return '<tr><td>' + bhCell(t.test_date) + '</td><td>' + bhCell(t.submit_date) + '</td><td>' + bhCell(t.report_type) +
            '</td><td>' + bhCell(t.doc_number) + '</td><td>' + bhCell(t.well_status) + '</td><td class="num">' +
            bhCell(t.initial_surf_casing_psi) + '</td><td class="num">' + bhCell(t.end_surf_casing_psi) + '</td><td class="num">' +
            bhCell(t.initial_prod_casing_psi) + '</td><td class="num">' + bhCell(t.end_prod_casing_psi) + '</td><td>' +
            bhCell(t.bh_flow_start) + '</td><td>' + bhCell(t.bh_flow_end) + '</td><td>' + bhCell(t.fluid_type) + '</td><td>' +
            bhCell(t.sample_taken) + '</td><td class="comments">' + bhCell(t.comments) + '</td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<p class="note">Readings are shown as the page shows them.  “--” is ECMC’s mark for a blank field, and TSTM means too small to measure.</p>';
    }

    html += '<h3>As-of dates</h3><div class="grid">' +
      kv('Scout card saved', show(w.fetched_at, 'not retrieved') + (w.fetched_at ? ' (' + ageDaysText(w.fetched_at) + ')' : '')) +
      kv('Bradenhead page saved', show(w.bh_fetched_at, 'not retrieved') + (w.bh_fetched_at ? ' (' + ageDaysText(w.bh_fetched_at) + ')' : '')) +
      kv('ECMC well list retrieved', esc(isoDay(META.listRetrieved)) + ' (' + ageDaysText(META.listRetrieved) + ')') +
      '</div>';
    html += '<div class="gaps"><b>What these records don’t cover.</b>  The scout card and bradenhead tests say nothing about H2S, ' +
      'the current condition of the wellhead or surface equipment, site access, or anything since the last filing.  ' +
      esc(NOTICE) + '</div></div>';

    page.innerHTML = html;
    bindPicker(w);
    window.owpProgram.wellBrowser(w.API_10);
    page.scrollTop = 0;
  }

  // ------------------------------------------------------------------
  // County and project summary

  var summaryBuilt = false;

  function summarize(key) {
    var groups = {};
    var own = key === 'County' ? 'county' : 'project';
    var saved = F[own];
    F[own] = '';
    var pool = wells.filter(pass);
    F[own] = saved;
    pool.forEach(function (w) {
      var g = groups[w[key]];
      if (!g) {
        g = groups[w[key]] = {name: w[key], n: 0, tier: {1: 0, 2: 0, 3: 0, 4: 0}, di: 0, fed: 0, cls: {}};
      }
      g.n++;
      g.tier[w.tier]++;
      if (w.DI_Community_Nov2024 === 'Yes') { g.di++; }
      if (w.fed === '1') { g.fed++; }
      g.cls[w.bh_flow_class] = (g.cls[w.bh_flow_class] || 0) + 1;
    });
    return Object.keys(groups).map(function (k) { return groups[k]; }).sort(function (a, b) {
      return b.n - a.n || (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1);
    });
  }

  function summaryTable(id, label, groups, filterKey) {
    var head = '<tr><th>' + label + '</th><th class="num">Wells</th>' +
      TIERS.map(function (t) { return '<th class="num">SRA tier ' + t + '</th>'; }).join('') +
      '<th class="num">In a DI community</th><th class="num">Federal/Tribal</th>' +
      CLASSES.map(function (c) { return '<th class="num">' + esc(c) + '</th>'; }).join('') + '</tr>';
    function cells(g) {
      return '<td class="num">' + fmtInt(g.n) + '</td>' +
        TIERS.map(function (t) { return '<td class="num">' + g.tier[t] + '</td>'; }).join('') +
        '<td class="num">' + g.di + '</td><td class="num">' + g.fed + '</td>' +
        CLASSES.map(function (c) { return '<td class="num">' + (g.cls[c] || 0) + '</td>'; }).join('');
    }
    var total = {n: 0, tier: {1: 0, 2: 0, 3: 0, 4: 0}, di: 0, fed: 0, cls: {}};
    groups.forEach(function (g) {
      total.n += g.n; total.di += g.di; total.fed += g.fed;
      TIERS.forEach(function (t) { total.tier[t] += g.tier[t]; });
      CLASSES.forEach(function (c) { total.cls[c] = (total.cls[c] || 0) + (g.cls[c] || 0); });
    });
    return '<div class="tablewrap short"><table class="data" id="' + id + '"><thead>' + head + '</thead><tbody>' +
      '<tr><td><b>All ' + fmtInt(groups.length) + '</b></td>' + cells(total) + '</tr>' +
      groups.map(function (g) {
        return '<tr class="clickable" data-key="' + filterKey + '" data-value="' + esc(g.name) + '"><td>' + esc(g.name) + '</td>' + cells(g) + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function buildSummary() {
    if (summaryBuilt) { return; }
    summaryBuilt = true;
    var page = el('page-summary');
    page.innerHTML = '<h2>County and project summary</h2>' +
      '<p class="note">Counts follow the filters set here, on the map, or in the well list.  Each table leaves out its own filter, so every county or project stays listed.  Flow class columns use all tests on file.  ' +
      'Federal/Tribal means the surface or the minerals are Federal, Tribal, or Indian.  ' +
      'Click a row to filter the map and the well list to that county or project, and click it again to clear it.  ' + esc(SRA_NOTE) + '</p>' +
      '<h3>By county</h3>' + summaryTable('sumcounty', 'County', summarize('County'), 'county') +
      '<h3>By ECMC Orphaned Well Program project</h3>' + summaryTable('sumproject', 'OWP project', summarize('Project'), 'project');
    Array.prototype.forEach.call(page.querySelectorAll('tr.clickable'), function (tr) {
      tr.onclick = function () {
        var key = tr.getAttribute('data-key');
        var value = tr.getAttribute('data-value');
        setFilter(key, F[key] === value ? '' : value);
      };
    });
    markSummarySelection();
  }

  function markSummarySelection() {
    if (!summaryBuilt) { return; }
    Array.prototype.forEach.call(el('page-summary').querySelectorAll('tr.clickable'), function (tr) {
      var on = F[tr.getAttribute('data-key')] === tr.getAttribute('data-value');
      tr.className = 'clickable' + (on ? ' sel' : '');
    });
  }

  // ------------------------------------------------------------------
  // Bradenhead and casing records

  var recordsBuilt = false;

  function wellListTable(rows, cols) {
    if (!rows.length) { return '<p>' + blank('No wells on the current list fall here.') + '</p>'; }
    return '<div class="tablewrap short"><table class="data"><thead><tr>' +
      cols.map(function (c) { return '<th>' + c[0] + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (w) {
        return '<tr>' + cols.map(function (c) { return '<td>' + c[1](w) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  var COL_API = ['API', function (w) { return '<a class="nw" href="#well=' + esc(w.API_10) + '">' + esc(w.API_10) + '</a>'; }];
  var COL_NAME = ['Well name', function (w) { return esc(w.WellName); }];
  var COL_COUNTY = ['County', function (w) { return esc(w.County); }];
  var COL_PROJECT = ['OWP project', function (w) { return esc(w.Project); }];
  var BH_LIST_COLS = [COL_API, COL_NAME, COL_COUNTY, COL_PROJECT,
    ['Tests on file', function (w) { return esc(w.bh_test_count); }],
    ['Last test', function (w) { return bhCell(w.bh_last_test_date); }],
    ['Years since last test', function (w) { var y = yearsSinceText(w.bh_last_test_date); return y === '' ? blank(NOT_REPORTED) : y; }],
    ['Flow class, latest test', function (w) { return bhCell(w.bh_flow_class_latest); }],
    ['Highest surface casing pressure, psi', function (w) { return show(w.bh_max_surf_casing_psi, 'no numeric reading'); }]];
  var CASING_LIST_COLS = [COL_API, COL_NAME, COL_COUNTY, COL_PROJECT,
    ['Status', function (w) { return scoutCell(w.well_status); }],
    ['Casing strings run', function (w) { return scoutCell(w.n_casing_strings); }],
    ['Planned strings', function (w) { return scoutCell(w.n_planned_casing_strings); }],
    ['Surface casing size, in', function (w) { return scoutCell(w.surf_casing_size_in); }],
    ['Surface casing depth, ft', function (w) { return scoutCell(w.surf_casing_depth_ft); }]];

  function section(title, count, body, open) {
    return '<details' + (open ? ' open' : '') + '><summary>' + title + ': ' + fmtInt(count) + ' wells</summary>' + body + '</details>';
  }

  // The three surface casing cases, each well in one list only.
  function surfaceCasingCases(pool) {
    var cases = {none: [], noRunSurf: [], noDepth: [], noSize: []};
    pool.forEach(function (w) {
      var rows = toObjects(CASCOLS, CAS[w.API_10] || []);
      var runSurf = rows.filter(function (c) { return isRunString(c) && c.string_type === 'SURF'; });
      if (!rows.length) { cases.none.push(w); return; }
      if (!runSurf.length) { cases.noRunSurf.push(w); return; }
      if (!runSurf.some(function (c) { return c.depth_ft !== ''; })) { cases.noDepth.push(w); return; }
      if (w.surf_casing_size_in === '') { cases.noSize.push(w); }
    });
    return cases;
  }

  function buildRecords() {
    if (recordsBuilt) { return; }
    recordsBuilt = true;
    var all = {};
    var latest = {};
    var years = {};
    var pool = wells.filter(pass);
    var savedCls = F.cls, savedLatest = F.clsLatest;
    F.cls = ''; F.clsLatest = savedLatest;
    wells.filter(pass).forEach(function (w) { all[w.bh_flow_class] = (all[w.bh_flow_class] || 0) + 1; });
    F.cls = savedCls; F.clsLatest = '';
    wells.filter(pass).forEach(function (w) { latest[w.bh_flow_class_latest] = (latest[w.bh_flow_class_latest] || 0) + 1; });
    F.clsLatest = savedLatest;
    pool.forEach(function (w) {
      var d = parseMDY(w.bh_last_test_date);
      if (d) { years[d.getFullYear()] = (years[d.getFullYear()] || 0) + 1; }
    });
    function ofClass(c) { return pool.filter(function (w) { return w.bh_flow_class === c; }); }
    var noTests = pool.filter(function (w) { return w.bh_test_count === '0' || w.bh_test_count === ''; });
    var tested = pool.length - noTests.length;
    var cases = surfaceCasingCases(pool);

    var html = '<h2>Bradenhead and casing records</h2>' +
      '<p class="note">This page lists what the COGIS bradenhead pages and scout cards record for ' + (pool.length === TOTAL ? 'all ' + fmtInt(TOTAL) + ' wells on the list' : 'the ' + fmtInt(pool.length) + ' of ' + fmtInt(TOTAL) + ' wells that pass the filters') +
      '.  The flow class table leaves out the flow class filters, so every class stays listed.  It sorts records and doesn’t rate any well.  The classes and flags are a convention of this dataset: ' +
      'the pressure flags use 0 psi, which is stricter than the Rule 419 action thresholds in most of the state, and no class is an ECMC compliance finding.  ' +
      '<a href="#about=flags">Definitions and limits</a>.</p>';

    html += '<h3>Wells by flow class</h3><div class="tablewrap short"><table class="data"><thead><tr><th>Flow class</th>' +
      '<th class="num">All tests on file</th><th class="num">Latest test only</th></tr></thead><tbody>' +
      CLASSES.map(function (c) {
        return '<tr><td>' + esc(c) + '</td><td class="num"><a href="#list" data-f="cls" data-v="' + esc(c) + '">' + fmtInt(all[c] || 0) +
          '</a></td><td class="num"><a href="#list" data-f="clsLatest" data-v="' + esc(c) + '">' + fmtInt(latest[c] || 0) + '</a></td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="note">A count opens the well list filtered to that class.  “All tests” gives a well the first class any of its tests meets.  ' +
      '“Latest test only” describes one test, which can be years old: see the table below.</p>';

    html += '<h3>Year of the last bradenhead test</h3><div class="tablewrap short"><table class="data"><thead><tr><th>Year of last test</th><th class="num">Wells</th></tr></thead><tbody>' +
      Object.keys(years).sort().reverse().map(function (y) { return '<tr><td>' + y + '</td><td class="num">' + fmtInt(years[y]) + '</td></tr>'; }).join('') +
      '<tr><td>No tests on file</td><td class="num">' + fmtInt(noTests.length) + '</td></tr>' +
      '</tbody></table></div><p class="note">' + fmtInt(tested) + ' of ' + fmtInt(pool.length) + ' wells have at least one test on file.</p>';

    html += '<h3>Bradenhead lists</h3>' +
      section('Liquid flow on any test', ofClass('liquid flow').length, wellListTable(ofClass('liquid flow'), BH_LIST_COLS)) +
      section('Pressure persists or rebuilds, on any test', ofClass('pressure persists or rebuilds').length, wellListTable(ofClass('pressure persists or rebuilds'), BH_LIST_COLS)) +
      section('No bradenhead tests on file', noTests.length, wellListTable(noTests, [COL_API, COL_NAME, COL_COUNTY, COL_PROJECT,
        ['Status', function (w) { return scoutCell(w.well_status); }],
        ['Bradenhead page as of', function (w) { return show(w.bh_fetched_at, 'not retrieved'); }]]));

    html += '<h3>Surface casing records</h3>' +
      '<p class="note">These three lists don’t overlap.  A blank here means the scout card doesn’t show the record.  It doesn’t mean the well has no surface casing.  ' +
      'A run string is one ECMC lists with citings type ACTUAL or HISTORICAL.</p>' +
      section('No casing records on the scout card', cases.none.length, wellListTable(cases.none, CASING_LIST_COLS), true) +
      section('Casing records, but no run surface string', cases.noRunSurf.length, wellListTable(cases.noRunSurf, CASING_LIST_COLS), true) +
      section('A run surface string with no depth on the card', cases.noDepth.length, wellListTable(cases.noDepth, CASING_LIST_COLS), true) +
      '<h3>Surface casing size</h3>' +
      section('A run surface string with a depth and no size on the card', cases.noSize.length, wellListTable(cases.noSize, CASING_LIST_COLS));

    var page = el('page-records');
    page.innerHTML = html;
    Array.prototype.forEach.call(page.querySelectorAll('a[data-f]'), function (a) {
      a.onclick = function () { setFilter(a.getAttribute('data-f'), a.getAttribute('data-v')); };
    });
  }

  // ------------------------------------------------------------------
  // About the data

  var aboutBuilt = false;

  function buildAbout() {
    if (aboutBuilt) { return; }
    aboutBuilt = true;
    function link(href, text) { return '<a target="_blank" rel="noopener" href="' + href + '">' + text + '</a>'; }
    var html = '<h2>About the data</h2>' +
      '<p><b>' + esc(NOTICE) + '</b></p>' +
      '<p>The dashboard covers the ' + fmtInt(TOTAL) + ' wells ECMC’s Orphaned Well Program lists as unplugged.  ' +
      'Values are shown as ECMC recorded them, with ECMC’s units: feet, inches, and psi.  ' +
      'A blank is shown as “' + NOT_ON_CARD + '” or “' + NOT_REPORTED + '” and never as zero.  ' +
      'Nothing here is a safety or hazard rating.</p>' +

      '<h3>Sources and retrieval dates</h3><div class="tablewrap short"><table class="data"><thead><tr><th>Source</th><th>Retrieved</th><th>Record</th></tr></thead><tbody>' +
      '<tr><td>ECMC Orphaned Well Program shapefile (' + link(esc(META.listUrl), 'OWP_SHP.ZIP') + '), records with status Unplugged</td><td>' +
      esc(META.listRetrieved) + '</td><td>' + fmtInt(TOTAL) + ' wells · SHA-256 ' + esc(META.listSha256) + '</td></tr>' +
      '<tr><td>CDPHE Colorado EnviroScreen 2.0 block groups (' + link(esc(META.bgUrl), 'feature layer') + '), carrying the November 2024 DI designation</td><td>' +
      esc(META.bgRetrieved) + '</td><td>' + fmtInt(META.bgCount) + ' block groups, ' + fmtInt(META.bgDiCount) + ' DI · SHA-256 ' + esc(META.bgSha256) + '</td></tr>' +
      '<tr><td>County outlines: ' + esc(META.countySource) + ' (' + link(esc(META.countyUrl), 'zip') + ')</td><td>' +
      'recorded in docs/dashboard.sources.json</td><td>' + fmtInt(META.countyCount) + ' Colorado counties</td></tr>' +
      '<tr><td>COGIS scout cards, one per well</td><td>' + esc(META.scoutOldest) + (META.scoutNewest !== META.scoutOldest ? ' to ' + esc(META.scoutNewest) : '') +
      '</td><td>' + fmtInt(TOTAL - META.scoutMissing) + ' pages saved</td></tr>' +
      '<tr><td>COGIS bradenhead pages, one per well</td><td>' + esc(META.bhOldest) + (META.bhNewest !== META.bhOldest ? ' to ' + esc(META.bhNewest) : '') +
      '</td><td>' + fmtInt(TOTAL - META.bhMissing) + ' pages saved</td></tr>' +
      '</tbody></table></div>' +
      '<p class="note">ECMC updates well status, adds tests, and revises the orphan list, so the live COGIS pages can differ from what’s here.  ' +
      'Every well sheet links to its live scout card and bradenhead page.  The banner at the top marks any source older than ' + META.staleDays + ' days.</p>' +

      '<h3>Priority score</h3><p>' + esc(SRA_NOTE) + '  The score has three parts: community burden (0 to 40), population exposure (0 to 30), and deliverability (0 to 30).  ' +
      'Tier 1 is a score of ' + TIER_RANGE[1] + ', tier 2 is ' + TIER_RANGE[2] + ', tier 3 is ' + TIER_RANGE[3] + ', and tier 4 is ' + TIER_RANGE[4] + '.  ' +
      link(README + '#ranked-well-list', 'The README describes the method') + ', and the weights are constants at the top of build_ranked_wells.py.</p>' +
      '<p>A well counts as Federal/Tribal for the map filter when it scores less than the full 15 jurisdiction points, meaning its surface or its minerals are Federal, Tribal, or Indian.</p>' +

      '<h3 id="flags">Bradenhead flags and flow classes</h3>' +
      '<p>Form 17 records a flow code for the bradenhead annulus during a test, a fluid type, and surface casing pressures.  ECMC doesn’t rank the codes.  ' +
      'The summary reports what the tests recorded as five flags and adds one class per well for sorting and mapping.  Each flag is Yes, No, or “can’t be determined from the records.”</p>' +
      '<div class="tablewrap short"><table class="data"><thead><tr><th>Flag</th><th>Yes when any test shows</th></tr></thead><tbody>' +
      '<tr><td>Any flow observed</td><td>a start or end flow code other than No Flow, including Down to 0</td></tr>' +
      '<tr><td>Liquid flow</td><td>water in a flow field, or water or liquid hydrocarbon as the fluid type</td></tr>' +
      '<tr><td>Flow at end of a test</td><td>an end flow code other than No Flow or Down to 0</td></tr>' +
      '<tr><td>Pressure not bled to zero</td><td>end surface casing pressure above 0 psi, or TSTM (too small to measure)</td></tr>' +
      '<tr><td>Pressure rebuilt between tests</td><td>a test that ended at 0 psi, followed by a test that started above 0 psi or TSTM</td></tr>' +
      '</tbody></table></div>' +
      '<div class="tablewrap short"><table class="data"><thead><tr><th>Order</th><th>Class</th><th>A well is in the first class it meets</th></tr></thead><tbody>' +
      '<tr><td>1</td><td>liquid flow</td><td>Liquid flow is Yes</td></tr>' +
      '<tr><td>2</td><td>pressure persists or rebuilds</td><td>Pressure not bled to zero, or pressure rebuilt, is Yes</td></tr>' +
      '<tr><td>3</td><td>flow at end of test</td><td>Flow at end of a test is Yes</td></tr>' +
      '<tr><td>4</td><td>flow bled off</td><td>Any flow observed is Yes</td></tr>' +
      '<tr><td>5</td><td>no flow</td><td>Any flow observed is No</td></tr>' +
      '<tr><td>6</td><td>flow not reported</td><td>The flow fields are blank on every test</td></tr>' +
      '<tr><td>7</td><td>no tests on file</td><td>The well has no bradenhead tests on file</td></tr>' +
      '</tbody></table></div>' +
      '<p>“All tests” applies the classes to every test on file.  “Latest test” applies them to the most recent test alone, with rebuild judged from the last two tests.  ' +
      'The order is a convention of this dataset, not an ECMC ranking.  The pressure flags use 0 psi rather than the Rule 419 action thresholds, which depend on surface casing depth and area orders, ' +
      'so they’re stricter than the rule in most of the state.  The rebuild flag is an inference from ECMC’s testing procedure, not an ECMC finding.  No class is an ECMC compliance finding.  ' +
      link(README + '#bradenhead-flow-indicators', 'The README gives the full definitions, the reasoning, and the ECMC documents they rest on') + '.</p>' +

      '<h3>What the records don’t cover</h3>' +
      '<p>The scout cards and bradenhead tests say nothing about H2S, the current condition of a wellhead or surface equipment, site access, or anything since the last filing.</p>' +

      '<h3>Blank fields</h3><div class="tablewrap short"><table class="data"><thead><tr><th>Field</th><th class="num">Wells with a blank</th><th class="num">Share of ' + fmtInt(TOTAL) + '</th></tr></thead><tbody>' +
      META.blanks.map(function (b) {
        return '<tr><td>' + esc(b[0]) + '</td><td class="num">' + fmtInt(b[1]) + '</td><td class="num">' + (100 * b[1] / TOTAL).toFixed(1) + '%</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="note">A blank means ECMC’s page left the field empty or the scraper couldn’t find its label.  The scrapers read page text by label, so if ECMC changes a label the field comes back blank.</p>' +

      '<h3>Map notes</h3>' +
      '<p>The half-mile and one-mile rings measure straight-line distance (804.672 m and 1,609.344 m) from ECMC’s published coordinates, whose accuracy varies by well.  ' +
      'Block group boundaries are simplified for display, to within about ' + META.simplifyMeters + ' m.  Scoring uses the full-resolution boundaries.  ' +
      'County outlines are the ' + fmtInt(META.countyCount) + ' Colorado counties in the ' + esc(META.countySource) + '.  That file is generalized for mapping at its scale, so a county line can sit slightly off the block group boundaries.  ' +
      'CDPHE publishes no EnviroScreen percentile or population for block groups under tribal jurisdiction.</p>' +

      '<h3>Definitions and code</h3><p>' +
      link(README + '#output-tables', 'Output tables') + ' · ' +
      link(META.repoUrl + '/blob/HEAD/data_dictionary.md', 'Data dictionary') + ' · ' +
      link(META.repoUrl, 'Repository') + '</p>' +
      '<p>The pages are generated by build_dashboard.py from the repository’s committed tables.  The map uses Leaflet ' + esc(META.leafletVersion) +
      ', which is embedded in this page under its BSD 2-Clause license (the notice is in the page source).  Basemap tiles come from Esri and the USGS and need a connection.  Everything else works offline.</p>' +

      '<h3>Author</h3><p>Steven R. Klimowski, Subsurface Risk Analytics.  Questions and corrections are welcome through GitHub issues.</p>';
    el('page-about').innerHTML = html;
  }

  // ------------------------------------------------------------------
  // Routing

  // The standalone map has one page.  The dashboard has the program pages,
  // drawn by program.js, and the well pages drawn here.
  var PAGES = DASH ? [
    ['overview', 'Overview'],
    ['findings', 'Key findings'],
    ['finance', 'Funding and spending'],
    ['activity', 'Plugging and inventory'],
    ['federal', 'Federal funding'],
    ['map', 'Map'],
    ['list', 'Well list'],
    ['well', 'Well sheet'],
    ['profile', 'Well list in charts'],
    ['summary', 'County and project summary'],
    ['records', 'Bradenhead and casing records'],
    ['law', 'Legislation and rules'],
    ['states', 'State comparison'],
    ['policy', 'Bonding and fees by state'],
    ['sources', 'Sources'],
    ['about', 'About the data']
  ] : [['map', 'Map']];
  var WELL_PAGES = ['map', 'list', 'well', 'profile', 'summary', 'records', 'about'];
  var lastWell = '';

  function parseHash() {
    var h = location.hash.replace(/^#/, '');
    var eq = h.indexOf('=');
    var name = eq < 0 ? h : h.slice(0, eq);
    var arg = eq < 0 ? '' : decodeURIComponent(h.slice(eq + 1));
    var known = PAGES.some(function (p) { return p[0] === name; });
    return {name: known ? name : 'overview', arg: arg};
  }

  function renderTabs(current) {
    Array.prototype.forEach.call(document.querySelectorAll('#tabs a[data-page]'), function (a) {
      var name = a.getAttribute('data-page');
      if (name === current) { a.setAttribute('aria-current', 'page'); } else { a.removeAttribute('aria-current'); }
      if (name === 'well') { a.setAttribute('href', lastWell ? '#well=' + lastWell : '#well'); }
    });
    el('pagename').textContent = PAGES.filter(function (p) { return p[0] === current; })[0][1];
    document.body.className =
      (WELL_PAGES.indexOf(current) >= 0 ? 'wellpage' : 'programpage') + (current === 'map' ? ' maponly' : '');
    window.scrollTo(0, 0);
  }

  function route() {
    var r = DASH ? parseHash() : {name: 'map', arg: ''};
    if (r.name === 'well' && r.arg) { lastWell = r.arg; }
    if (r.name === 'well' && !r.arg && lastWell) { r.arg = lastWell; }
    PAGES.forEach(function (p) {
      el('page-' + p[0]).className = 'page' + (p[0] === r.name ? ' on' : '');
    });
    if (DASH) { renderTabs(r.name); }
    if (r.name === 'map') {
      initMap();
      map.invalidateSize();
    } else if (r.name === 'list') {
      buildList();
      syncListControls();
    } else if (r.name === 'well') {
      renderSheet(r.arg);
    } else if (r.name === 'summary') {
      buildSummary();
    } else if (r.name === 'records') {
      buildRecords();
    } else if (r.name === 'about') {
      buildAbout();
      var target = r.arg ? el(r.arg) : null;
      if (target) { target.scrollIntoView(); }
    } else if (DASH) {
      window.owpProgram.show(r.name);
    }
    document.title = (DASH ? 'Colorado Orphaned Well Program: ' : 'Colorado unplugged orphaned wells: map') +
      (DASH ? PAGES.filter(function (p) { return p[0] === r.name; })[0][1] : '');
  }

  // Exposed for checks from the console and the test suite's page checks.
  window.orphanWells = {
    wells: wells, filters: F, shown: shownWells, listCsv: DASH ? listCsv : null,
    wellAge: wellAge, setFilter: setFilter, clearFilters: clearFilters
  };

  renderFrame();
  renderFilterBar();
  window.addEventListener('hashchange', route);
  route();
})();
