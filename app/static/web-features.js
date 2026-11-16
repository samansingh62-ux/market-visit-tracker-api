/* Command Center: desktop pages for the field-app features.
   Uses the page's api(), esc(), $, user, token, managerMode and adminKey. */
(function () {
  const css = `
  .wf{display:flex;flex-direction:column;gap:18px}
  .wfHead{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
  .wfHead h2{margin:0;font-size:26px}.wfHead p{margin:4px 0 0;color:var(--muted)}
  .wfBar{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
  .wfBar label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted);font-weight:600}
  .wfBar select,.wfBar input{height:38px;border:1px solid var(--line);border-radius:10px;padding:0 10px;background:#fff;font:inherit;min-width:150px}
  .wfBtn{height:38px;border-radius:10px;border:1px solid var(--line);background:#fff;padding:0 14px;font-weight:700;cursor:pointer}
  .wfBtn.pri{background:#2F6BFF;color:#fff;border-color:#2F6BFF}.wfBtn:disabled{opacity:.6;cursor:wait}
  .wfKpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
  .wfKpi{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px}
  .wfKpi span{display:block;font-size:12px;color:var(--muted);font-weight:600}.wfKpi b{display:block;font-size:24px;margin-top:4px}
  .wfKpi small{color:var(--muted)}
  .wfCard{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px;overflow:auto}
  .wfCard h3{margin:0 0 10px;font-size:17px}
  table.wfT{width:100%;border-collapse:collapse;font-size:13.5px}
  .wfT th{position:sticky;top:0;background:#f4f7fc;text-align:right;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);padding:9px 10px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap;user-select:none}
  .wfT th:first-child,.wfT td:first-child{text-align:left}
  .wfT td{padding:9px 10px;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap}
  .wfT td.l{text-align:left;white-space:normal}
  .wfT tr.click{cursor:pointer}.wfT tr.click:hover td{background:#f8fbff}
  .wfT tr.sub td{background:#fbfcfe;font-size:12.5px}
  .wfT th.sorted::after{content:' ▾'}.wfT th.sorted.asc::after{content:' ▴'}
  .g{color:#16A34A;font-weight:700}.a{color:#B45309;font-weight:700}.r{color:#E11D48;font-weight:700}.mut{color:var(--muted)}
  .wfBarIn{height:6px;background:#E9EEF6;border-radius:3px;overflow:hidden;min-width:80px}.wfBarIn i{display:block;height:100%}
  .wfFlag{border-radius:12px;padding:10px 14px;font-weight:600;background:#FDECEA;border:1px solid #E11D48}
  .wfFlag.warn{background:#FEF3E2;border-color:#F59E0B}
  .wfActs{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:10px}
  .wfAct{display:flex;gap:12px;background:#0B1B3F;color:#fff;border-radius:14px;padding:12px 14px}
  .wfAct .n{flex:0 0 28px;height:28px;border-radius:50%;background:#2F6BFF;display:flex;align-items:center;justify-content:center;font-weight:800}
  .wfAct span{display:block;color:#B9C7E8;font-size:13px;margin-top:3px}
  .wfHero{background:#0B1B3F;color:#fff;border-radius:18px;padding:18px 20px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
  .wfHero .k{color:#7FA6FF;font-size:12px;letter-spacing:.16em;font-weight:700;text-transform:uppercase}
  .wfHero h2{margin:4px 0;font-size:30px}.wfHero p{margin:0;color:#B9C7E8}
  .wfMsg{padding:14px;color:var(--muted)}.wfErr{padding:14px;color:#E11D48;font-weight:600}
  .wfTabs{display:flex;gap:6px;flex-wrap:wrap}.wfTabs button{height:34px;border-radius:999px;border:1px solid var(--line);background:#fff;padding:0 14px;font-weight:700;cursor:pointer}
  .wfTabs button.on{background:#0B1B3F;color:#fff;border-color:#0B1B3F}
  .wfGrid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:1100px){.wfGrid2{grid-template-columns:1fr}}
  .heat td.h0{background:#FDE2E2}.heat td.h1{background:#FEF3C7}.heat td.h2{background:#DCF5E5}
  `;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  const fmt = (v) => Number(v || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  const pct = (v) => v == null ? '—' : `${Math.round(v)}%`;
  const money = (v) => { v = Number(v || 0); return v >= 1e7 ? '₹' + (v / 1e7).toFixed(2) + ' Cr' : v >= 1e5 ? '₹' + (v / 1e5).toFixed(1) + ' L' : '₹' + fmt(v); };
  const tone = (p, good = 100, ok = 50) => p == null ? 'mut' : p >= good ? 'g' : p >= ok ? 'a' : 'r';
  const bar = (p) => `<div class="wfBarIn"><i style="width:${Math.min(100, Math.max(0, p || 0))}%;background:${p >= 100 ? '#16A34A' : p >= 50 ? '#F59E0B' : '#E11D48'}"></i></div>`;
  const visit = (n) => n == null ? 'Never' : n === 0 ? 'Today' : n === 1 ? 'Yesterday' : n + 'd ago';
  const role = () => String((user && user.role) || '').toUpperCase();
  const zoneRole = () => ['CEO', 'ADMIN', 'MANAGER', 'VIEWER'].includes(role()) || managerMode;

  // sortable table: cols = [{k,label,fmt?,cls?,l?}], rows = objects
  function table(id, cols, rows, opt = {}) {
    const state = (table.st[id] = table.st[id] || { k: opt.sort || null, asc: !!opt.asc });
    const sorted = state.k ? [...rows].sort((a, b) => {
      const x = a[state.k], y = b[state.k];
      const c = (typeof x === 'number' || typeof y === 'number') ? (x ?? -Infinity) - (y ?? -Infinity) : String(x ?? '').localeCompare(String(y ?? ''));
      return state.asc ? c : -c;
    }) : rows;
    const th = cols.map((c) => `<th data-k="${c.k}" class="${state.k === c.k ? 'sorted' + (state.asc ? ' asc' : '') : ''}">${esc(c.label)}</th>`).join('');
    const body = sorted.map((r, i) => `<tr class="${opt.onRow ? 'click' : ''}" data-i="${rows.indexOf(r)}">${cols.map((c) => `<td class="${c.l ? 'l' : ''} ${c.cls ? c.cls(r) : ''}">${c.fmt ? c.fmt(r) : esc(r[c.k] ?? '')}</td>`).join('')}</tr>${opt.after ? opt.after(r) : ''}`).join('');
    setTimeout(() => {
      const el = document.getElementById(id); if (!el) return;
      el.querySelectorAll('th[data-k]').forEach((h) => h.onclick = () => { const k = h.dataset.k; state.asc = state.k === k ? !state.asc : false; state.k = k; opt.rerender && opt.rerender(); });
      if (opt.onRow) el.querySelectorAll('tbody tr[data-i]').forEach((tr) => tr.onclick = () => opt.onRow(rows[+tr.dataset.i]));
    });
    return `<table class="wfT" id="${id}"><thead><tr>${th}</tr></thead><tbody>${body || `<tr><td class="l mut" colspan="${cols.length}">Nothing to show.</td></tr>`}</tbody></table>`;
  }
  table.st = {};

  function authHeaders() { const h = {}; if (managerMode && typeof adminKey !== 'undefined' && adminKey && adminKey !== (typeof PIN_ADMIN !== 'undefined' ? PIN_ADMIN : null)) h['X-API-Key'] = adminKey; else if (token) h.Authorization = 'Bearer ' + token; return h; }
  async function download(path, fallbackName) {
    const r = await fetch(path, { headers: authHeaders() });
    if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch (e) { } throw new Error(d); }
    const blob = await r.blob();
    const cd = r.headers.get('content-disposition') || '';
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="([^"]+)"/.exec(cd);
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = m ? decodeURIComponent(m[1]) : fallbackName;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  }
  function csv(name, cols, rows) {
    const q = (v) => { v = String(v ?? ''); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    const text = [cols.map((c) => q(c.label)).join(',')].concat(rows.map((r) => cols.map((c) => q(c.raw ? c.raw(r) : r[c.k])).join(','))).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv' })); a.download = name; a.click();
  }

  let perfCache = null;
  async function perf(force) {
    if (!force && perfCache && Date.now() - perfCache.at < 120e3) return perfCache.d;
    const d = await api('/performance-dashboard'); perfCache = { at: Date.now(), d }; return d;
  }

  // ------------------------------------------------------------ pages
  const PAGES = {
    ftd: { label: '◔  TL-wise FTD', render: pageFtd },
    review: { label: '▦  Review cards & PPT', render: pageReview },
    schemes: { label: '₹  Schemes & stock payout', render: pageSchemes },
    focus: { label: '◎  Focus models', render: pageFocus },
    vreport: { label: '☑  Visit report', render: pageVisitReport, show: () => zoneRole() || role() === 'KAM' },
    punched: { label: '✎  Punched sales', render: pagePunched, show: () => zoneRole() || ['KAM', 'SS', 'TL'].includes(role()) },
    finder: { label: '⌕  Stock finder', render: pageFinder, show: () => zoneRole() || ['KAM', 'SS', 'TL'].includes(role()) },
  };
  let host, current = null;

  function mount() {
    const nav = document.querySelector('.sideNav'), main = document.querySelector('.dashMain');
    if (!nav || !main || document.getElementById('wfNav')) return;
    const box = document.createElement('div'); box.id = 'wfNav';
    box.innerHTML = '<div style="margin:10px 12px 4px;font-size:11px;letter-spacing:.12em;color:#9aa8bf;font-weight:700">FIELD APP FEATURES</div>' +
      Object.entries(PAGES).map(([k, p]) => `<button class="sideBtn" data-wf="${k}">${p.label}</button>`).join('') +
      '<a class="sideBtn" href="/api-guide" target="_blank" rel="noopener" style="text-decoration:none;display:block">⌘  API guide</a>';
    nav.appendChild(box);
    host = document.createElement('div'); host.id = 'wfPage'; host.className = 'wf hidden'; main.appendChild(host);
    box.querySelectorAll('[data-wf]').forEach((b) => b.onclick = () => open(b.dataset.wf));
    document.querySelectorAll('.sideBtn[data-target],.viewAll[data-target]').forEach((el) => el.addEventListener('click', close, true));
    refreshNav();
  }
  function refreshNav() {
    document.querySelectorAll('#wfNav [data-wf]').forEach((b) => { const p = PAGES[b.dataset.wf]; b.classList.toggle('hidden', !!(p.show && !p.show())); });
  }
  function open(k) {
    current = k;
    [...document.querySelector('.dashMain').children].forEach((c) => { if (c !== host) { if (!c.dataset.wfHidden) c.dataset.wfPrev = c.classList.contains('hidden') ? '1' : ''; c.dataset.wfHidden = '1'; c.classList.add('hidden'); } });
    host.classList.remove('hidden');
    document.querySelectorAll('.sideBtn').forEach((b) => b.classList.toggle('active', b.dataset.wf === k));
    host.innerHTML = '<div class="wfMsg">Loading…</div>';
    window.scrollTo({ top: 0 });
    Promise.resolve(PAGES[k].render()).catch((e) => { host.innerHTML = `<div class="wfErr">${esc(e.message)}</div>`; });
  }
  function close() {
    if (!host || host.classList.contains('hidden')) return;
    host.classList.add('hidden'); current = null;
    [...document.querySelector('.dashMain').children].forEach((c) => { if (c.dataset.wfHidden) { if (!c.dataset.wfPrev) c.classList.remove('hidden'); delete c.dataset.wfHidden; delete c.dataset.wfPrev; } });
  }
  window.wfOpen = open;

  // ---------------- TL-wise FTD
  const ftdState = { kam: '', q: '' };
  async function pageFtd(force) {
    const d = await perf(force);
    const left = Math.max((d.period || {}).days_remaining || 1, 1);
    const rets = d.retailers || [];
    const all = ((d.hierarchy || {}).tl || []).filter((t) => t.name && t.name !== 'Unassigned').map((t) => {
      const before = (t.sales || 0) - (t.ftd_sales || 0);
      const need = t.target ? Math.ceil(Math.max(t.target - before, 0) / left) : null;
      return { ...t, need, ftd_pct: need ? t.ftd_sales * 100 / need : null, ach: t.target ? t.sales * 100 / t.target : null };
    });
    const kams = [...new Set(all.map((t) => t.kam).filter(Boolean))].sort();
    const rows = all.filter((t) => (!ftdState.kam || t.kam === ftdState.kam) && (!ftdState.q || t.name.toLowerCase().includes(ftdState.q.toLowerCase())));
    const tot = rows.reduce((a, t) => (a.u += t.ftd_sales || 0, a.v += t.ftd_sales_value || 0, a.n += t.need || 0, a.z += t.ftd_sales ? 0 : 1, a), { u: 0, v: 0, n: 0, z: 0 });
    const open = ftdState.open || '';
    const cols = [
      { k: 'name', label: 'TL', l: true, fmt: (t) => `<b>${esc(t.name)}</b><div class="mut" style="font-size:12px">${esc([t.kam && 'KAM ' + t.kam, t.ss && 'SS ' + t.ss].filter(Boolean).join(' · '))}</div>`, raw: (t) => t.name },
      { k: 'ftd_sales', label: 'FTD units', fmt: (t) => `<b class="${t.ftd_sales ? '' : 'r'}">${fmt(t.ftd_sales)}</b>` },
      { k: 'need', label: 'Need today', fmt: (t) => t.need == null ? '—' : fmt(t.need) },
      { k: 'ftd_pct', label: '% of need', fmt: (t) => `<span class="${tone(t.ftd_pct, 100, 60)}">${pct(t.ftd_pct)}</span>` },
      { k: 'ftd_sales_value', label: 'FTD value', fmt: (t) => money(t.ftd_sales_value) },
      { k: 'ftd_counters', label: 'Counters sold', fmt: (t) => `${fmt(t.ftd_counters)} / ${fmt(t.retailers)}` },
      { k: 'sales', label: 'MTD', fmt: (t) => fmt(t.sales) },
      { k: 'target', label: 'Target', fmt: (t) => fmt(t.target) },
      { k: 'ach', label: 'MTD ach', fmt: (t) => `<span class="${tone(t.ach)}">${pct(t.ach)}</span>` },
    ];
    const rerender = () => pageFtd();
    host.innerHTML = `<div class="wfHead"><div><h2>TL-wise FTD</h2><p>Today’s sale by TL against the units each needs per day · ${left} days left incl. today · as of ${new Date(perfCache.at + 5.5 * 3600e3).toISOString().slice(11, 16)}</p></div>
      <div class="wfBar"><label>KAM<select id="wfFtdKam"><option value="">All KAM areas</option>${kams.map((k) => `<option ${k === ftdState.kam ? 'selected' : ''}>${esc(k)}</option>`).join('')}</select></label>
      <label>Search TL<input id="wfFtdQ" value="${esc(ftdState.q)}"></label><button class="wfBtn" id="wfFtdRef">↻ Refresh</button><button class="wfBtn" id="wfFtdCsv">Export CSV</button></div></div>
      <div class="wfKpis"><div class="wfKpi"><span>Sold today</span><b>${fmt(tot.u)}</b><small>${money(tot.v)}</small></div>
        <div class="wfKpi"><span>Need today</span><b>${fmt(tot.n)}</b><small>${tot.n ? pct(tot.u * 100 / tot.n) + ' done' : ''}</small></div>
        <div class="wfKpi"><span>TLs at zero</span><b class="${tot.z ? 'r' : ''}">${fmt(tot.z)}</b><small>of ${rows.length}</small></div></div>
      <div class="wfCard">${table('wfFtdT', cols, rows, { sort: 'ftd_sales', rerender, onRow: (t) => { ftdState.open = ftdState.open === t.name ? '' : t.name; rerender(); },
        after: (t) => t.name !== open ? '' : (() => {
          const list = rets.filter((r) => (r.assignments || []).some((a) => a.tl === t.name) || r.tl === t.name);
          const sold = list.filter((r) => r.ftd_sales > 0).sort((a, b) => b.ftd_sales - a.ftd_sales);
          return `<tr class="sub"><td class="l" colspan="9"><b>Counters that sold today:</b> ${sold.map((r) => `${esc(r.name)} <b>${r.ftd_sales}</b>`).join(' · ') || 'none yet'} &nbsp;·&nbsp; ${list.length - sold.length} with no sale today &nbsp; <a href="#" onclick="event.stopPropagation();wfReview('TL','${esc(t.name).replace(/'/g, '&#39;')}');return false">Open review card ›</a></td></tr>`;
        })() })}</div>`;
    $('wfFtdKam').onchange = (e) => { ftdState.kam = e.target.value; rerender(); };
    $('wfFtdQ').oninput = (e) => { ftdState.q = e.target.value; clearTimeout(pageFtd.t); pageFtd.t = setTimeout(() => { rerender(); const i = $('wfFtdQ'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); };
    $('wfFtdRef').onclick = () => pageFtd(true);
    $('wfFtdCsv').onclick = () => csv('TL-wise FTD.csv', cols, rows);
  }

  // ---------------- Review cards
  const rvState = { role: 'TL', name: '' };
  window.wfReview = (r, n) => { rvState.role = r; rvState.name = n; open('review'); };
  async function pageReview() {
    const d = await perf();
    const h = d.hierarchy || {}, skip = ['VBM-Vacant', 'SS Direct (NPO)', 'Vacant-Zone A', 'Unassigned'];
    const names = {
      TL: (h.tl || []).map((g) => g.name), SS: (h.ss || []).map((g) => g.name), RDS: (h.rds || []).map((g) => g.name),
      KAM: [...new Set((d.retailers || []).map((r) => r.kam).filter(Boolean))],
    };
    Object.keys(names).forEach((k) => names[k] = names[k].filter((n) => n && !skip.includes(n)).sort());
    if (['TL', 'SS', 'KAM', 'RDS'].includes(role()) && !names[role()].includes(user.name)) names[role()].unshift(user.name);
    if (!names[rvState.role].length) rvState.role = Object.keys(names).find((k) => names[k].length) || 'TL';
    if (!names[rvState.role].includes(rvState.name)) rvState.name = names[rvState.role][0] || '';
    host.innerHTML = `<div class="wfHead"><div><h2>Review cards &amp; PPT</h2><p>One-page review of any TL, SS, KAM or RDS, with downloads for the image and the PowerPoint deck</p></div>
      <div class="wfBar"><label>Role<select id="wfRvRole">${['TL', 'SS', 'KAM', 'RDS'].filter((k) => names[k].length).map((k) => `<option ${k === rvState.role ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
      <label>Name<select id="wfRvName">${names[rvState.role].map((n) => `<option ${n === rvState.name ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>
      <button class="wfBtn" id="wfRvPng">⬇ Image (PNG)</button><button class="wfBtn pri" id="wfRvPpt">⬇ PowerPoint</button></div></div><div id="wfRvBody"><div class="wfMsg">Loading…</div></div>`;
    $('wfRvRole').onchange = (e) => { rvState.role = e.target.value; rvState.name = ''; pageReview(); };
    $('wfRvName').onchange = (e) => { rvState.name = e.target.value; pageReview(); };
    const q = `role=${rvState.role}&name=${encodeURIComponent(rvState.name)}`;
    const dl = (btn, path, ext) => async () => { const b = $(btn), t = b.textContent; b.disabled = true; b.textContent = 'Preparing…'; try { await download(path + '?' + q, `${rvState.name} review.${ext}`); } catch (e) { alert(e.message); } b.disabled = false; b.textContent = t; };
    $('wfRvPng').onclick = dl('wfRvPng', '/review/image', 'png');
    $('wfRvPpt').onclick = dl('wfRvPpt', '/review/ppt', 'pptx');
    if (!rvState.name) { $('wfRvBody').innerHTML = '<div class="wfMsg">No one to review in your area.</div>'; return; }
    let r;
    try { r = await api('/review?' + q); } catch (e) { $('wfRvBody').innerHTML = `<div class="wfErr">${esc(e.message)}</div>`; return; }
    const S = r.summary, P = r.period, par = r.parents || {};
    const sub = [r.limited_to && 'Only ' + r.limited_to + ' area', par.towns && par.towns.join(', '), par.ss && 'SS ' + par.ss, par.kam && 'KAM ' + par.kam, `${S.counters} counters`].filter(Boolean).join(' · ');
    const ccols = [
      { k: 'name', label: 'Counter', l: true, fmt: (c) => `<b>${esc(c.name)}</b>${r.role !== 'TL' && c.tl ? `<div class="mut" style="font-size:12px">${esc(c.tl)}</div>` : c.club ? `<div class="mut" style="font-size:12px">${esc(c.club)}</div>` : ''}` },
      { k: 'sales', label: 'MTD', fmt: (c) => fmt(c.sales) }, { k: 'target', label: 'Target', fmt: (c) => c.target ? fmt(c.target) : '—' },
      { k: 'pct', label: 'Ach', fmt: (c) => `<span class="${tone(c.pct)}">${pct(c.pct)}</span>` }, { k: 'pct', label: '', fmt: (c) => bar(c.pct) },
      { k: 'gap', label: 'Gap', fmt: (c) => fmt(c.gap) }, { k: 'need', label: 'Need/day', fmt: (c) => fmt(c.need) }, { k: 'ftd_sales', label: 'FTD', fmt: (c) => fmt(c.ftd_sales) },
      { k: 'stock', label: 'Stock', fmt: (c) => fmt(c.stock) }, { k: 'dos', label: 'Days stock', fmt: (c) => c.chain ? '<span class="mut">main</span>' : c.dos == null ? '—' : `<span class="${c.dos >= 45 ? 'r' : ''}">${Math.round(c.dos)}</span>` },
      { k: 'days_since_visit', label: 'Last visit', fmt: (c) => `<span class="${c.days_since_visit == null || c.days_since_visit >= 20 ? 'r' : ''}">${visit(c.days_since_visit)}</span>` },
    ];
    const tcols = [
      { k: 'name', label: 'TL', l: true, fmt: (t) => `<a href="#" onclick="wfReview('TL','${esc(t.name).replace(/'/g, '&#39;')}');return false"><b>${esc(t.name)}</b></a>` },
      { k: 'sales', label: 'MTD', fmt: (t) => fmt(t.sales) }, { k: 'target', label: 'Target', fmt: (t) => fmt(t.target) },
      { k: 'pct', label: 'Ach', fmt: (t) => `<span class="${tone(t.pct)}">${pct(t.pct)}</span>` }, { k: 'pct', label: '', fmt: (t) => bar(t.pct) },
      { k: 'ftd', label: 'FTD', fmt: (t) => fmt(t.ftd) }, { k: 'need', label: 'Need/day', fmt: (t) => fmt(t.need) },
    ];
    const rerender = () => renderBody();
    function renderBody() {
      $('wfRvBody').innerHTML = `<div class="wf">
      <div class="wfHero"><div><div class="k">Zone A · ${esc(r.role)} review</div><h2>${esc(r.name)}</h2><p>${esc(sub)}</p></div><div style="text-align:right;color:#B9C7E8">${esc(P.end)}<br>${P.days_remaining} days left</div></div>
      <div class="wfKpis"><div class="wfKpi"><span>MTD sale</span><b>${fmt(S.sales)}</b><small>of ${fmt(S.target)}</small></div>
        <div class="wfKpi"><span>Achieved</span><b class="${tone(S.pct)}">${pct(S.pct)}</b><small>Gap ${fmt(S.gap)}</small></div>
        <div class="wfKpi"><span>Need per day</span><b>${fmt(S.need)}</b><small>to close the target</small></div>
        <div class="wfKpi"><span>Today (FTD)</span><b>${fmt(S.ftd)}</b><small>${S.ftd_counters} of ${S.counters} counters sold</small></div>
        <div class="wfKpi"><span>Stock</span><b>${fmt(S.stock)}</b><small>units at these counters</small></div></div>
      ${(r.flags || []).map((f) => `<div class="wfFlag ${f.kind === 'warn' ? 'warn' : ''}">${esc(f.text)}</div>`).join('')}
      ${(r.actions || []).length ? `<div class="wfCard" style="background:#F6F8FC"><h3>Action plan</h3><div class="wfActs">${r.actions.map((a, i) => `<div class="wfAct"><div class="n">${i + 1}</div><div><b>${esc(a.title)}</b><span>${esc(a.text)}</span></div></div>`).join('')}</div></div>` : ''}
      ${r.team.length ? `<div class="wfCard"><h3>TLs (${r.team.length})</h3>${table('wfRvTeam', tcols, r.team, { sort: 'pct', asc: true, rerender })}</div>` : ''}
      <div class="wfCard"><h3>All counters (${r.counters.length})</h3>${table('wfRvC', ccols, r.counters, { sort: r.role === 'TL' ? 'sales' : 'gap', rerender })}</div></div>`;
    }
    renderBody();
  }

  // ---------------- Schemes & stock payout
  const scState = { q: '', tl: '' };
  async function pageSchemes(force) {
    const d = await perf(force);
    const seen = new Set(), rows = [];
    let closedModels = true;
    for (const r of d.retailers || []) {
      const S = r.schemes; if (!S) continue;
      const key = S.shared ? S.shared.retailer_code : r.code;
      if (seen.has(key)) continue; seen.add(key);
      closedModels = closedModels && !!(S.periods && S.periods.models && S.periods.models.closed);
      const lines = ['focus', 'clearance', 'additional'].flatMap((g) => ((S[g] || {}).lines || []).map((l) => ({ ...l, group: g })));
      rows.push({ code: key, name: S.shared ? (S.shared.retailer_name || key) : r.name, stores: S.shared ? S.shared.stores : 1, tl: r.tl, kam: r.kam, club: r.club,
        total: S.total || 0, booster: (S.booster || {}).payout || 0, focus: (S.focus || {}).payout || 0, clearance: (S.clearance || {}).payout || 0,
        additional: (S.additional || {}).payout || 0, back: (S.back_support || {}).payable || 0, bs_pct: (S.back_support || {}).achievement_pct,
        stock_extra: S.stock_extra || 0, stock_units: S.stock_units || 0, lines, S });
    }
    const tls = [...new Set(rows.map((r) => r.tl).filter(Boolean))].sort();
    const q = scState.q.toLowerCase();
    const view = rows.filter((r) => (!scState.tl || r.tl === scState.tl) && (!q || r.name.toLowerCase().includes(q)));
    const sum = (k) => view.reduce((a, r) => a + (r[k] || 0), 0);
    const open = scState.open || '';
    const cols = [
      { k: 'name', label: 'Retailer', l: true, fmt: (r) => `<b>${esc(r.name)}</b>${r.stores > 1 ? ` <span class="mut">(${r.stores} stores)</span>` : ''}<div class="mut" style="font-size:12px">${esc([r.club, r.tl && 'TL ' + r.tl].filter(Boolean).join(' · '))}</div>`, raw: (r) => r.name },
      { k: 'total', label: 'Total', fmt: (r) => `<b>${money(r.total)}</b>` }, { k: 'booster', label: 'Booster', fmt: (r) => money(r.booster) },
      { k: 'focus', label: 'Focus', fmt: (r) => money(r.focus) }, { k: 'clearance', label: 'Clearance', fmt: (r) => money(r.clearance) },
      { k: 'additional', label: 'Additional', fmt: (r) => money(r.additional) }, { k: 'back', label: 'Back support', fmt: (r) => money(r.back) },
      { k: 'bs_pct', label: 'Value ach', fmt: (r) => `<span class="${tone(r.bs_pct, 100, 90)}">${pct(r.bs_pct)}</span>` },
      ...(closedModels ? [] : [{ k: 'stock_units', label: 'Scheme stock', fmt: (r) => fmt(r.stock_units) }, { k: 'stock_extra', label: 'If stock sold', fmt: (r) => r.stock_extra ? `<span class="g">+${money(r.stock_extra)}</span>` : '—' }]),
    ];
    const rerender = () => pageSchemes();
    const detail = (r) => {
      const ls = r.lines.filter((l) => l.units > 0 || (!closedModels && l.stock > 0));
      return `<tr class="sub"><td class="l" colspan="${cols.length}"><table class="wfT" style="margin:4px 0"><thead><tr><th>Series</th><th>Sold</th><th>Slab</th><th>Rate</th><th>Payout</th><th>Next slab</th>${closedModels ? '' : '<th>In stock</th><th>If all sold</th><th>Extra</th>'}</tr></thead><tbody>${ls.map((l) => `<tr><td class="l"><b>${esc(l.series)}</b> <span class="mut">${l.group}</span></td><td>${fmt(l.units)}</td><td>${esc(l.slab || 'below first')}</td><td>₹${fmt(l.rate)}</td><td><b>${money(l.payout)}</b></td>
        <td>${l.next ? `${l.next.units_more} more → ₹${fmt(l.next.rate)}/unit${!closedModels && l.next.stock_short > 0 ? ` <span class="a">(stock ${l.next.stock_short} short)</span>` : ''}` : 'Top slab'}</td>
        ${closedModels ? '' : `<td>${l.stock ? fmt(l.stock) : '<span class="a">No stock</span>'}</td><td>${l.if_all_sold ? money(l.if_all_sold.payout) + ' · ' + esc(l.if_all_sold.slab || '') : '—'}</td><td>${l.if_all_sold && l.if_all_sold.extra > 0 ? `<span class="g">+${money(l.if_all_sold.extra)}</span>` : '—'}</td>`}</tr>`).join('') || `<tr><td class="l mut" colspan="9">No model scheme sales${closedModels ? '' : ' or stock'}.</td></tr>`}</tbody></table></td></tr>`;
    };
    host.innerHTML = `<div class="wfHead"><div><h2>Schemes &amp; stock payout</h2><p>November retailer schemes, provisional · chain retailers counted once · ${closedModels ? 'model slabs closed on 15 Nov' : 'stock columns show the extra payout if the scheme-model stock on hand is sold'} · click a row for model detail</p></div>
      <div class="wfBar"><label>TL<select id="wfScTl"><option value="">All TLs</option>${tls.map((t) => `<option ${t === scState.tl ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>
      <label>Search retailer<input id="wfScQ" value="${esc(scState.q)}"></label><button class="wfBtn" id="wfScCsv">Export CSV</button></div></div>
      <div class="wfKpis"><div class="wfKpi"><span>Retailers</span><b>${fmt(view.length)}</b></div><div class="wfKpi"><span>Total payout</span><b>${money(sum('total'))}</b></div>
        <div class="wfKpi"><span>Focus + clearance + additional</span><b>${money(sum('focus') + sum('clearance') + sum('additional'))}</b></div><div class="wfKpi"><span>Back support</span><b>${money(sum('back'))}</b></div>
        ${closedModels ? '' : `<div class="wfKpi"><span>Extra if stock sold</span><b class="g">+${money(sum('stock_extra'))}</b><small>${fmt(sum('stock_units'))} scheme-model units</small></div>`}</div>
      <div class="wfCard">${table('wfScT', cols, view, { sort: 'total', rerender, onRow: (r) => { scState.open = scState.open === r.code ? '' : r.code; rerender(); }, after: (r) => r.code === open ? detail(r) : '' })}</div>`;
    $('wfScTl').onchange = (e) => { scState.tl = e.target.value; rerender(); };
    $('wfScQ').oninput = (e) => { scState.q = e.target.value; clearTimeout(pageSchemes.t); pageSchemes.t = setTimeout(() => { rerender(); const i = $('wfScQ'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); };
    $('wfScCsv').onclick = () => csv('Scheme payout.csv', cols, view);
  }

  // ---------------- Focus models
  const fmState = { variant: '' };
  async function pageFocus() {
    const d = await api('/focus-models' + (fmState.variant ? '?variant=' + encodeURIComponent(fmState.variant) : ''));
    if (!d.available) { host.innerHTML = `<div class="wfHead"><div><h2>Focus models</h2></div></div><div class="wfMsg">${esc(d.message || 'Not available.')}</div>`; return; }
    const cols = [{ k: 'variant', label: 'Model', l: true, fmt: (m) => `<b>${esc(m.variant)}</b>` }, { k: 'target', label: 'Target', fmt: (m) => fmt(m.target) }, { k: 'mtd', label: 'MTD', fmt: (m) => fmt(m.mtd) },
      { k: 'pct', label: 'Ach', fmt: (m) => `<span class="${m.pct >= d.expected_pct ? 'g' : m.pct >= d.expected_pct * 0.7 ? 'a' : 'r'}">${pct(m.pct)}</span>` }, { k: 'pct', label: '', fmt: (m) => bar(m.pct) },
      { k: 'ftd', label: 'FTD', fmt: (m) => fmt(m.ftd) }, { k: 'stock', label: 'Stock', fmt: (m) => fmt(m.stock) }, { k: 'per_day_needed', label: 'Need/day', fmt: (m) => m.per_day_needed == null ? '—' : fmt(m.per_day_needed) }];
    const rerender = () => pageFocus();
    const det = d.detail;
    host.innerHTML = `<div class="wfHead"><div><h2>Focus models</h2><p>Target vs achievement · on pace = ${pct(d.expected_pct)} · ${d.days_left} days left · click a model for counters not moving it and VBAs at zero</p></div></div>
      <div class="wfKpis"><div class="wfKpi"><span>Target</span><b>${fmt(d.total.target)}</b></div><div class="wfKpi"><span>MTD</span><b>${fmt(d.total.mtd)}</b><small>${pct(d.total.pct)}</small></div><div class="wfKpi"><span>Today</span><b>${fmt(d.total.ftd)}</b></div></div>
      <div class="wfCard">${table('wfFmT', cols, d.models, { rerender, onRow: (m) => { fmState.variant = fmState.variant === m.variant ? '' : m.variant; pageFocus(); } })}</div>
      ${det ? `<div class="wfGrid2"><div class="wfCard"><h3>${esc(det.variant)}: counters with stock but no sale (${det.not_moving.length})</h3>${table('wfFmNm', [{ k: 'name', label: 'Counter', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'stock', label: 'Stock' }, { k: 'target', label: 'Target' }], det.not_moving, { rerender })}
        <h3 style="margin-top:14px">No stock but has a target (${det.no_stock_with_target.length})</h3>${table('wfFmNs', [{ k: 'name', label: 'Counter', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'target', label: 'Target' }], det.no_stock_with_target, { rerender })}</div>
        <div class="wfCard"><h3>VBAs with zero ${esc(det.variant)} MTD and FTD (${det.vbas_zero.length} of ${det.vbas_in_area})</h3>${table('wfFmV', [{ k: 'name', label: 'VBA', l: true }, { k: 'type', label: 'Type' }, { k: 'store', label: 'Store', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'target', label: 'Target' }], det.vbas_zero, { rerender })}</div></div>` : ''}`;
  }

  // ---------------- Visit report
  const vrState = { from: '', to: '', kam: '', tab: 'people', role: '' };
  async function pageVisitReport() {
    const qs = new URLSearchParams(); if (vrState.from) qs.set('date_from', vrState.from); if (vrState.to) qs.set('date_to', vrState.to);
    const d = await api('/visit-report?' + qs);
    vrState.from = d.date_from; vrState.to = d.date_to;
    const people = d.people.filter((p) => (!vrState.kam || p.kam === vrState.kam || p.name === vrState.kam) && (!vrState.role || p.role === vrState.role));
    const rerender = () => draw();
    function draw() {
      const open = vrState.open || '';
      const pcols = [{ k: 'name', label: 'Name', l: true, fmt: (p) => `<b>${esc(p.name)}</b> <span class="mut">${esc(p.role)}</span><div class="mut" style="font-size:12px">${esc([p.kam && 'KAM ' + p.kam, p.ss && 'SS ' + p.ss].filter(Boolean).join(' · '))}</div>`, raw: (p) => p.name },
        { k: 'outlets', label: 'Outlets' }, { k: 'visit_count', label: 'Visits' }, { k: 'days_active', label: 'Days active' }, { k: 'with_remarks', label: 'With remarks' }, { k: 'in_vwork', label: 'In V-Work' }, { k: 'last_visit', label: 'Last visit' }];
      const dcols = [{ k: 'name', label: 'TL', l: true, fmt: (t) => `<b>${esc(t.name)}</b><div class="mut" style="font-size:12px">${esc(t.kam || '')}</div>`, raw: (t) => t.name }]
        .concat(d.dates.map((dt, i) => ({ k: 'd' + i, label: dt.slice(8), fmt: (t) => t.days[i] ? String(t.days[i]) : '<span class="r">0</span>', raw: (t) => t.days[i] })))
        .concat([{ k: 'total', label: 'Total' }, { k: 'zero_days', label: 'Zero days' }]);
      const tl = d.tl_daily.filter((t) => !vrState.kam || t.kam === vrState.kam).map((t) => ({ ...t, ...Object.fromEntries(t.days.map((v, i) => ['d' + i, v])) }));
      host.innerHTML = `<div class="wfHead"><div><h2>Visit report</h2><p>Outlets visited and remarks by TL, SS and KAM · ${esc(d.date_from)} to ${esc(d.date_to)}</p></div>
        <div class="wfBar"><label>From<input type="date" id="wfVrF" value="${esc(vrState.from)}"></label><label>To<input type="date" id="wfVrT" value="${esc(vrState.to)}"></label>
        <label>KAM<select id="wfVrK"><option value="">All</option>${d.kams.map((k) => `<option ${k === vrState.kam ? 'selected' : ''}>${esc(k)}</option>`).join('')}</select></label>
        <label>Role<select id="wfVrR"><option value="">All</option>${['TL', 'SS', 'KAM'].map((k) => `<option ${k === vrState.role ? 'selected' : ''}>${k}</option>`).join('')}</select></label>
        <button class="wfBtn" id="wfVrCsv">Export CSV</button></div></div>
        <div class="wfTabs"><button data-t="people" class="${vrState.tab === 'people' ? 'on' : ''}">People &amp; remarks</button><button data-t="daily" class="${vrState.tab === 'daily' ? 'on' : ''}">TL day by day</button></div>
        <div class="wfCard">${vrState.tab === 'people' ? table('wfVrP', pcols, people, { sort: 'outlets', rerender, onRow: (p) => { vrState.open = vrState.open === p.name ? '' : p.name; draw(); },
          after: (p) => p.name !== open ? '' : `<tr class="sub"><td class="l" colspan="7"><table class="wfT"><thead><tr><th>Date</th><th>Outlet</th><th>Town</th><th>Feedback</th><th>Follow-up</th><th>Photos</th><th>V-Work</th></tr></thead><tbody>${p.visits.map((v) => `<tr><td class="l">${esc(v.date)}</td><td class="l"><b>${esc(v.retailer)}</b></td><td class="l">${esc(v.town || '')}</td><td class="l">${esc(v.feedback)}</td><td class="l">${esc(v.follow_up)}</td><td>${v.photos}</td><td>${v.vwork ? '✓' : ''}</td></tr>`).join('')}</tbody></table></td></tr>` })
          : `<div class="heat">${table('wfVrD', dcols, tl, { sort: 'total', rerender })}</div>`}</div>`;
      $('wfVrF').onchange = (e) => { vrState.from = e.target.value; pageVisitReport(); };
      $('wfVrT').onchange = (e) => { vrState.to = e.target.value; pageVisitReport(); };
      $('wfVrK').onchange = (e) => { vrState.kam = e.target.value; pageVisitReport(); };
      $('wfVrR').onchange = (e) => { vrState.role = e.target.value; pageVisitReport(); };
      host.querySelectorAll('.wfTabs [data-t]').forEach((b) => b.onclick = () => { vrState.tab = b.dataset.t; draw(); });
      $('wfVrCsv').onclick = () => vrState.tab === 'people' ? csv('Visit report.csv', pcols, people) : csv('TL day by day.csv', dcols, tl);
    }
    draw();
  }

  // ---------------- Punched sales
  const psState = { tab: 'vba', type: '', kam: '' };
  async function pagePunched() {
    const d = await api('/punched-sales');
    const rerender = () => draw();
    function draw() {
      if (!d.as_of) { host.innerHTML = `<div class="wfHead"><div><h2>Punched sales</h2></div>${up()}</div><div class="wfMsg">No dashboard loaded for this month yet.</div>`; bindUp(); return; }
      const vb = d.vbas.filter((v) => (!psState.type || (psState.type === 'Zero' ? !v.units : v.type === psState.type)) && (!psState.kam || v.kam === psState.kam));
      const own = d.own.filter((o) => !psState.kam || o.kam === psState.kam);
      const vcols = [{ k: 'name', label: 'Name', l: true, fmt: (v) => `<b>${esc(v.name)}</b> <span class="mut">${esc(v.type)}</span>`, raw: (v) => v.name }, { k: 'store', label: 'Store', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'ss', label: 'SS', l: true },
        { k: 'units', label: 'Units', fmt: (v) => `<b class="${v.units ? '' : 'r'}">${fmt(v.units)}</b>` }, { k: 'vol_target', label: 'Target', fmt: (v) => v.vol_target ? fmt(v.vol_target) : '—' },
        { k: 'pct', label: 'Ach', fmt: (v) => `<span class="${tone(v.pct)}">${pct(v.pct)}</span>` }, { k: 'value', label: 'Value', fmt: (v) => money(v.value) }, { k: 'days', label: 'Days' }, { k: 'last', label: 'Last punch', fmt: (v) => esc(v.last || '—') }];
      const ocols = [{ k: 'name', label: 'Name', l: true, fmt: (o) => `<b>${esc(o.name)}</b> <span class="mut">${esc(o.role)}</span>`, raw: (o) => o.name }, { k: 'kam', label: 'KAM', l: true },
        { k: 'units', label: 'Own units', fmt: (o) => `<b>${fmt(o.units)}</b>` }, { k: 'value', label: 'Value', fmt: (o) => money(o.value) }, { k: 'outlets', label: 'Outlets' }, { k: 'days', label: 'Days' },
        { k: 'area_units', label: 'All punching at their outlets' }, { k: 'share', label: 'Own share', fmt: (o) => pct(o.share) }, { k: 'last', label: 'Last', fmt: (o) => esc(o.last || '—') }];
      host.innerHTML = `<div class="wfHead"><div><h2>Punched sales</h2><p>VBA / RVBA / FVBA sales against target, and what TLs and SSs punched themselves · from the tertiary dashboard till ${esc(d.as_of)}</p></div>
        <div class="wfBar"><label>KAM<select id="wfPsK"><option value="">All</option>${(d.kams || []).map((k) => `<option ${k === psState.kam ? 'selected' : ''}>${esc(k)}</option>`).join('')}</select></label>${psState.tab === 'vba' ? `<label>Type<select id="wfPsT">${['', 'VBA', 'RVBA', 'FVBA', 'Zero'].map((k) => `<option value="${k}" ${k === psState.type ? 'selected' : ''}>${k === '' ? 'Everyone' : k === 'Zero' ? 'Zero sale' : k}</option>`).join('')}</select></label>` : ''}
        <button class="wfBtn" id="wfPsCsv">Export CSV</button>${up()}</div></div>
        <div class="wfKpis">${d.totals.map((t) => `<div class="wfKpi"><span>${esc(t.kind)}</span><b>${fmt(t.units)}</b><small>${t.share}% of ${fmt(d.total_units)}</small></div>`).join('')}</div>
        <div class="wfTabs"><button data-t="vba" class="${psState.tab === 'vba' ? 'on' : ''}">VBA / FVBA (${vb.length})</button><button data-t="own" class="${psState.tab === 'own' ? 'on' : ''}">TL &amp; SS own (${own.length})</button></div>
        <div class="wfCard">${psState.tab === 'vba' ? table('wfPsV', vcols, vb, { sort: 'pct', asc: true, rerender }) : table('wfPsO', ocols, own, { sort: 'units', rerender })}</div>`;
      host.querySelectorAll('.wfTabs [data-t]').forEach((b) => b.onclick = () => { psState.tab = b.dataset.t; draw(); });
      $('wfPsK').onchange = (e) => { psState.kam = e.target.value; draw(); };
      if ($('wfPsT')) $('wfPsT').onchange = (e) => { psState.type = e.target.value; draw(); };
      $('wfPsCsv').onclick = () => psState.tab === 'vba' ? csv('VBA punched sales.csv', vcols, vb) : csv('TL SS own punching.csv', ocols, own);
      bindUp();
    }
    const up = () => d.can_upload ? `<label style="justify-content:flex-end">&nbsp;<span><input type="file" id="wfPsF" accept=".xlsx,.xlsm" hidden><button class="wfBtn pri" id="wfPsU">Upload latest dashboard</button></span></label>` : '';
    function bindUp() {
      if (!$('wfPsU')) return;
      $('wfPsU').onclick = () => $('wfPsF').click();
      $('wfPsF').onchange = async () => {
        const f = $('wfPsF').files[0]; if (!f) return; const b = $('wfPsU'); b.disabled = true; b.textContent = 'Reading…';
        try { const fd = new FormData(); fd.append('file', f, f.name); const r = await fetch('/admin/tertiary-dashboard', { method: 'POST', headers: authHeaders(), body: fd }); const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); alert(`Loaded ${fmt(j.units)} units till ${j.as_of}`); pagePunched(); }
        catch (e) { alert(e.message); b.disabled = false; b.textContent = 'Upload latest dashboard'; }
      };
    }
    draw();
  }

  // ---------------- Stock finder
  const sfState = { model: '', days: 30 };
  async function pageFinder() {
    const qs = new URLSearchParams({ days: sfState.days }); if (sfState.model) qs.set('model', sfState.model);
    const d = await api('/stock/finder?' + qs);
    const rerender = () => pageFinder();
    const mcols = [{ k: 'model', label: 'Model', l: true, fmt: (m) => `<b>${esc(m.model)}</b>` }, { k: 'stock', label: 'Stock' }, { k: 'counters', label: 'Counters' },
      { k: 'not_moving_units', label: 'Not moving (units)', fmt: (m) => `<span class="${m.not_moving_units ? 'r' : ''}">${fmt(m.not_moving_units)}</span>` }, { k: 'not_moving_counters', label: 'Not moving (counters)' }, { k: 'slow_units', label: 'Slow units' }];
    let detail = '';
    if (d.variants) {
      detail = d.variants.map((v, i) => `<div class="wfCard"><h3>${esc(v.variant)} · stock ${fmt(v.stock)} · sold ${fmt(v.sold)} in ${d.days} days · not moving ${fmt(v.not_moving_units)}</h3>
        ${table('wfSfH' + i, [{ k: 'name', label: 'Counter', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'stock', label: 'Stock' }, { k: 'sold', label: `Sold ${d.days}d` },
          { k: 'cover_days', label: 'Cover days', fmt: (h) => h.cover_days == null ? '∞' : fmt(h.cover_days) }, { k: 'status', label: 'Status', fmt: (h) => `<span class="${h.status === 'Not moving' ? 'r' : h.status === 'Slow' ? 'a' : 'g'}">${esc(h.status)}</span>` },
          { k: 'last_sold', label: 'Last sold', fmt: (h) => esc(h.last_sold || '—') }, { k: 'colours', label: 'Colours', l: true, fmt: (h) => esc((h.colours || []).map((c) => `${c.colour} ${c.qty}`).join(', ')) }], v.holders, { sort: 'stock', rerender })}
        ${v.short && v.short.length ? `<h3 style="margin-top:12px">Selling it but low on stock</h3>${table('wfSfS' + i, [{ k: 'name', label: 'Counter', l: true }, { k: 'tl', label: 'TL', l: true }, { k: 'sold', label: 'Sold' }, { k: 'stock', label: 'Stock' }, { k: 'cover_days', label: 'Cover days' }], v.short, { rerender })}` : ''}</div>`).join('');
    }
    host.innerHTML = `<div class="wfHead"><div><h2>Stock finder</h2><p>Stock at each counter against what it sold · find sale-return candidates and where stock can move · as of ${esc(d.as_of)}</p></div>
      <div class="wfBar"><label>Model<select id="wfSfM"><option value="">All models (summary)</option>${(d.models || []).map((m) => `<option ${m.model === sfState.model ? 'selected' : ''}>${esc(m.model)}</option>`).join('')}${sfState.model && !(d.models || []).some((m) => m.model === sfState.model) ? `<option selected>${esc(sfState.model)}</option>` : ''}</select></label>
      <label>Sales look-back<select id="wfSfD">${[15, 30, 45, 60].map((n) => `<option value="${n}" ${n === sfState.days ? 'selected' : ''}>${n} days</option>`).join('')}</select></label></div></div>
      <div class="wfKpis"><div class="wfKpi"><span>Stock</span><b>${fmt(d.summary.stock)}</b></div><div class="wfKpi"><span>Not moving</span><b class="r">${fmt(d.summary.not_moving_units)}</b><small>${fmt(d.summary.not_moving_counters)} counters</small></div><div class="wfKpi"><span>Slow (over ${d.slow_days} days cover)</span><b class="a">${fmt(d.summary.slow_units)}</b></div></div>
      ${d.variants ? detail : `<div class="wfCard">${table('wfSfT', mcols, d.models || [], { sort: 'not_moving_units', rerender, onRow: (m) => { sfState.model = m.model; pageFinder(); } })}</div>`}`;
    $('wfSfM').onchange = (e) => { sfState.model = e.target.value; pageFinder(); };
    $('wfSfD').onchange = (e) => { sfState.days = +e.target.value; pageFinder(); };
  }

  // mount once the app shell is on the page; re-check menu visibility after login
  const tryMount = () => { mount(); refreshNav(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', tryMount); else tryMount();
  const appEl = document.getElementById('app');
  if (appEl) new MutationObserver(() => { if (!appEl.classList.contains('hidden')) tryMount(); }).observe(appEl, { attributes: true, attributeFilter: ['class'] });
  window.addEventListener('wf:logout', close);
})();
