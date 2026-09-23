// ============================================================================
// MÓDULO ÚNICO DE FILTROS  (Roberto 23/09/2026: "haz un módulo de filtros y que
// cada pestaña lo use en función de sus columnas; si cambias el filtro, cambia
// en todas; así normalizas dentro del ERP").
//
// Reutilizable en CUALQUIER app HTML (informe de rentabilidad, analizador de
// tarifas, paneles). Define UNA sola vez cómo se filtra una tabla:
//   - buscar por palabras sueltas, sin tildes ni mayúsculas (Y lógico)
//   - fecha desde / hasta
//   - mínimo / máximo por cada columna numérica, combinables
//   - chips de filtros activos y "quitar todos"
// parametrizado por las COLUMNAS de cada tabla.
//
// USO (cada tabla que no sea la principal):
//   import {crearFiltro, filtroToolsHTML, filtroAplica, filtroRefresca, wireFiltros} from './filtros.mjs';
//   wireFiltros();                                  // UNA vez al arrancar la app
//   const F = crearFiltro(cols, filas, redibujar);  // por tabla; redibujar() re-pinta la tabla
//   // al pintar:  filtroToolsHTML(F, filas) encima, y tu tabla con filtroAplica(F, filas)
//   // en redibujar():  const ft = filtroAplica(F, filas);  ...pinta ft...  filtroRefresca(F, ft.length);
//
// cols = [{label, key, filter?, numeric?, html?, dateLen?}]
//   filter: 'text' | 'date' | 'number' | 'select' | false  (si no se pone, se
//   deduce de las filas con filterKind: números -> number, AAAA-MM(-DD) -> date,
//   resto -> text). numeric:true fuerza 'number'. html:true no filtra.
// ============================================================================

// -- utilidades mínimas (autocontenidas; una app puede pasar su propio nf) -----
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const norm = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
export const nf = (v, d = 0) => (v == null || Number.isNaN(Number(v))) ? '' : Number(v).toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d });
export const numSet = v => v !== '' && v != null && !Number.isNaN(Number(v));

// -- qué filtro le toca a cada columna -----------------------------------------
export function filterKind(c, rows) {
  if (c.html) return false;
  if (c.numeric) return 'number';
  let n = 0, dateLike = true, sample = null;
  for (const r of rows) { const v = r[c.key]; if (v == null || v === '') continue; const s = String(v); n++; if (sample === null) sample = s; if (dateLike && !/^\d{4}-\d{2}(-\d{2})?$/.test(s)) { dateLike = false; break; } }
  if (!n) return false;
  if (dateLike) { c.dateLen = sample.length; return 'date'; }
  return 'text';
}

// -- barra de filtros (por columna) --------------------------------------------
export function filterBarHtml(columns, rows, filters, scope) {
  const f = filters, out = [], sc = scope || '';
  for (const c of columns) {
    if (!c.filter || c.filter === 'number') continue;
    const v = f[c.key];
    if (c.filter === 'date') { const t = c.dateLen === 7 ? 'month' : 'date'; out.push(`<label class="fctl"><span>${esc(c.label)} desde</span><input type="${t}" data-fscope="${sc}" data-tfilter="${esc(c.key)}" data-part="from" value="${esc(v?.from || '')}"></label><label class="fctl"><span>${esc(c.label)} hasta</span><input type="${t}" data-fscope="${sc}" data-tfilter="${esc(c.key)}" data-part="to" value="${esc(v?.to || '')}"></label>`); continue; }
    const freq = new Map(); for (const r of rows) { const x = r[c.key]; if (x == null || x === '') continue; const s = String(x); freq.set(s, (freq.get(s) || 0) + 1); }
    if (c.filter === 'select') { const opts = [...freq.keys()].sort((a, b) => a.localeCompare(b, 'es', { numeric: true })); out.push(`<label class="fctl"><span>${esc(c.label)}</span><select data-fscope="${sc}" data-tfilter="${esc(c.key)}"><option value="">Todos</option>${opts.map(o => `<option value="${esc(o)}"${v === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select></label>`); }
    else { const opts = [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 300).map(e => e[0]).sort((a, b) => a.localeCompare(b, 'es')); const lid = 'dl_' + sc + '_' + String(c.key).replace(/\W/g, '_'); out.push(`<label class="fctl"><span>${esc(c.label)}</span><input type="search" list="${lid}" data-fscope="${sc}" data-tfilter="${esc(c.key)}" placeholder="escribe (varias palabras)…" autocomplete="off" value="${esc(v || '')}"><datalist id="${lid}">${opts.map(o => `<option value="${esc(o)}">`).join('')}</datalist></label>`); }
  }
  const nums = columns.filter(c => c.filter === 'number'), N = f.__num || {};
  if (nums.length) {
    out.push(`<div class="fctl fnumhead"><span>Filtrar por cifra: mínimo y máximo de cada columna (se combinan)</span></div>`);
    for (const c of nums) { const r = N[c.key] || {}; out.push(`<label class="fctl fnum"><span>${esc(c.label)}</span><span class="fnumrow"><input type="number" step="any" data-fscope="${sc}" data-tnumk="${esc(c.key)}" data-part="min" placeholder="mín." aria-label="${esc(c.label)} mínimo" value="${esc(r.min ?? '')}"><input type="number" step="any" data-fscope="${sc}" data-tnumk="${esc(c.key)}" data-part="max" placeholder="máx." aria-label="${esc(c.label)} máximo" value="${esc(r.max ?? '')}"></span></label>`); }
  }
  out.push(`<div class="fctl fact"><span>&nbsp;</span><button type="button" data-fclear="${sc}">Quitar todos los filtros</button></div>`);
  return out.join('');
}

export function filterCount(filters) { let k = 0; for (const [key, v] of Object.entries(filters)) { if (key === '__num') { for (const kk in (v || {})) { const r = v[kk]; if (r && (numSet(r.min) || numSet(r.max))) k++; } } else if (v && typeof v === 'object') { if (v.from) k++; if (v.to) k++; } else if (v != null && v !== '') k++; } return k; }

// -- ¿pasa una fila los filtros por columna? (sin la búsqueda por palabras) -----
export function rowPasses(r, columns, filters) {
  const f = filters;
  for (const c of columns) {
    const v = f[c.key]; if (v == null || v === '' || !c.filter || c.filter === 'number') continue;
    const raw = r[c.key];
    if (c.filter === 'select') { if (String(raw ?? '') !== v) return false; }
    else if (c.filter === 'date') { if (!v.from && !v.to) continue; const s = String(raw ?? '').slice(0, c.dateLen); if (v.from && s < v.from.slice(0, c.dateLen)) return false; if (v.to && s > v.to.slice(0, c.dateLen)) return false; }
    else { const s = norm(raw); for (const t of norm(v).split(/\s+/)) if (t && !s.includes(t)) return false; }
  }
  const N = f.__num;
  if (N) for (const key in N) { const n = N[key]; if (!n || !(numSet(n.min) || numSet(n.max))) continue; const x = r[key]; if (typeof x !== 'number') return false; if (numSet(n.min) && x < Number(n.min)) return false; if (numSet(n.max) && x > Number(n.max)) return false; }
  return true;
}

export function chipsHtml(columns, filters, scope) {
  const f = filters, out = [], sc = scope || '', lab = k => columns.find(c => c.key === k)?.label || k;
  for (const [key, v] of Object.entries(f)) {
    if (key === '__num') { for (const kk in (v || {})) { const r = v[kk]; if (r && (numSet(r.min) || numSet(r.max))) out.push(`<button class="chip" data-fscope="${sc}" data-tremove="__num" data-part="${esc(kk)}" title="Quitar filtro">${esc(lab(kk))}${numSet(r.min) ? ' ≥ ' + esc(r.min) : ''}${numSet(r.max) ? ' ≤ ' + esc(r.max) : ''} ×</button>`); } }
    else if (v && typeof v === 'object') { if (v.from) out.push(`<button class="chip" data-fscope="${sc}" data-tremove="${esc(key)}" data-part="from" title="Quitar filtro">${esc(lab(key))} desde ${esc(v.from)} ×</button>`); if (v.to) out.push(`<button class="chip" data-fscope="${sc}" data-tremove="${esc(key)}" data-part="to" title="Quitar filtro">${esc(lab(key))} hasta ${esc(v.to)} ×</button>`); }
    else if (v != null && v !== '') out.push(`<button class="chip" data-fscope="${sc}" data-tremove="${esc(key)}" title="Quitar filtro">${esc(lab(key))}: ${esc(v)} ×</button>`);
  }
  return out.join('');
}

export function applyFilterTo(filters, el) {
  if (el.dataset.tfilter !== undefined) { const k = el.dataset.tfilter, p = el.dataset.part; if (p) { const cur = filters[k] && typeof filters[k] === 'object' ? filters[k] : {}; filters[k] = { ...cur, [p]: el.value }; } else filters[k] = el.value; return true; }
  if (el.dataset.tnumk !== undefined) { const k = el.dataset.tnumk, box = el.closest('.filterbar') || document, g = p => box.querySelector(`[data-tnumk="${CSS.escape(k)}"][data-part="${p}"]`)?.value ?? ''; filters.__num = { ...(filters.__num || {}), [k]: { min: g('min'), max: g('max') } }; return true; }
  return false;
}

export function removeFilterFrom(filters, key, part, bar) {
  const q = s => bar ? bar.querySelector(s) : null;
  if (key === '__num') { if (part) { if (filters.__num) delete filters.__num[part]; if (bar) bar.querySelectorAll(`[data-tnumk="${CSS.escape(part)}"]`).forEach(el => { el.value = ''; }); if (filters.__num && !Object.keys(filters.__num).length) delete filters.__num; } else { delete filters.__num; if (bar) bar.querySelectorAll('[data-tnumk]').forEach(el => { el.value = ''; }); } }
  else if (part) { if (filters[key] && typeof filters[key] === 'object') { delete filters[key][part]; if (!filters[key].from && !filters[key].to) delete filters[key]; } const el = q(`[data-tfilter="${CSS.escape(key)}"][data-part="${part}"]`); if (el) el.value = ''; }
  else { delete filters[key]; const el = q(`[data-tfilter="${CSS.escape(key)}"]`); if (el) el.value = ''; }
}

// -- una instancia de filtro por tabla -----------------------------------------
export const _filtros = new Map(); let _filtroSeq = 0;
export function crearFiltro(cols, rows, redibujar) {
  const id = 'f' + (++_filtroSeq);
  for (const c of cols) if (c.filter === undefined) c.filter = filterKind(c, rows);
  const F = { id, cols, redibujar, st: { query: '', filters: {}, showFilters: false } };
  _filtros.set(id, F);
  return F;
}
// barra de herramientas (buscar + botón Filtros) + barra de filtros + chips
export function filtroToolsHTML(F, rows) {
  const k = filterCount(F.st.filters), open = F.st.showFilters || k > 0;
  return `<div class="tabletools"><div class="tabletools-l"><input type="search" data-fsearch="${F.id}" placeholder="Buscar palabras (da igual tildes o mayúsculas)…" value="${esc(F.st.query)}"><button type="button" data-ftoggle="${F.id}" class="${open ? 'on' : ''}" aria-expanded="${open}">Filtros${k ? ' · ' + k : ''}</button></div><span data-fcount="${F.id}"></span></div><div class="filterbar" data-fbar="${F.id}" ${open ? '' : 'hidden'}>${filterBarHtml(F.cols, rows, F.st.filters, F.id)}</div><div class="active-filters tchips" data-fchips="${F.id}">${chipsHtml(F.cols, F.st.filters, F.id)}</div>`;
}
// filas que pasan la búsqueda por palabras + los filtros por columna
export function filtroAplica(F, rows) {
  const terms = norm(F.st.query).split(/\s+/).filter(Boolean);
  return rows.filter(r => rowPasses(r, F.cols, F.st.filters) && (!terms.length || terms.every(t => norm(F.cols.map(c => c.html ? '' : r[c.key]).join('\u0001')).includes(t))));
}
// actualiza contador, chips y botón tras un cambio (sin re-pintar la barra)
export function filtroRefresca(F, total) {
  const cnt = document.querySelector(`[data-fcount="${F.id}"]`), k = filterCount(F.st.filters);
  if (cnt) cnt.textContent = `${nf(total)} filas${(F.st.query || k) ? ' encontradas' : ''}`;
  const ch = document.querySelector(`[data-fchips="${F.id}"]`); if (ch) ch.innerHTML = chipsHtml(F.cols, F.st.filters, F.id);
  const bt = document.querySelector(`[data-ftoggle="${F.id}"]`); if (bt) { bt.textContent = 'Filtros' + (k ? ' · ' + k : ''); bt.classList.toggle('on', k > 0 || F.st.showFilters); }
}

// -- cableado: UNA vez; enruta los eventos a la instancia por data-* -----------
let _wired = false;
export function wireFiltros() {
  if (_wired) return; _wired = true;
  document.addEventListener('input', e => {
    const t = e.target;
    if (t.dataset.fsearch !== undefined) { const F = _filtros.get(t.dataset.fsearch); if (F) { F.st.query = t.value; F.redibujar(); } return; }
    if (t.dataset.tfilter === undefined && t.dataset.tnumk === undefined) return;
    const F = _filtros.get(t.dataset.fscope || ''); if (F && applyFilterTo(F.st.filters, t)) F.redibujar();
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.ftoggle !== undefined) { const F = _filtros.get(b.dataset.ftoggle); if (F) { F.st.showFilters = !F.st.showFilters; const bar = document.querySelector(`[data-fbar="${F.id}"]`); if (bar) bar.hidden = !F.st.showFilters; b.setAttribute('aria-expanded', String(F.st.showFilters)); b.classList.toggle('on', F.st.showFilters || filterCount(F.st.filters) > 0); } return; }
    if (b.dataset.fclear !== undefined) { const F = _filtros.get(b.dataset.fclear); if (F) { F.st.filters = {}; const bar = document.querySelector(`[data-fbar="${F.id}"]`); if (bar) bar.querySelectorAll('input,select').forEach(el => { el.value = ''; }); F.redibujar(); } return; }
    if (b.dataset.tremove !== undefined) { const F = _filtros.get(b.dataset.fscope || ''); if (F) { removeFilterFrom(F.st.filters, b.dataset.tremove, b.dataset.part, document.querySelector(`[data-fbar="${b.dataset.fscope || ''}"]`)); F.redibujar(); } return; }
  });
}
