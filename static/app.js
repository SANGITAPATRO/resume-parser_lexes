/* ═══════════════════════════════════════════════════════
   ResumeIQ — app.js
   Shared logic for upload.html and parse.html
═══════════════════════════════════════════════════════ */

/* ── Admin mode: true only on /admin ── */
const _isAdmin = (
  window.location.pathname === '/admin' ||
  new URLSearchParams(window.location.search).get('admin') === '1'
);

/* ═══════════════════════════════════════════════════════
   STATE
═══════════════════════════════════════════════════════ */
let _orig    = null;
let _file    = '';
let _fileUrl = '';
let _skills  = [];
let _parsed  = false;
let _timerIv = null;
let _t0      = 0;

/* ═══════════════════════════════════════════════════════
   AUTO-SAVE  (debounced 1 s)
═══════════════════════════════════════════════════════ */
let _autoSaveTimer = null;

function scheduleAutoSave() {
  if (!_parsed) return;
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(doSave, 1000);
}

function setAutoSaveStatus(state) {
  const el = document.getElementById('autosave-status');
  if (!el) return;
  el.className = 'autosave-status';
  el.innerHTML = '';
  el.removeAttribute('title');
  if (state === 'saving') {
    el.classList.add('saving');
    el.innerHTML = '<span class="spin-sm"></span>';
    el.title = 'Auto-saving…';
  } else if (state === 'saved') {
    el.classList.add('saved');
    el.textContent = '●';
    el.title = 'All changes saved';
    setTimeout(() => {
      if (el.classList.contains('saved')) { el.className = 'autosave-status'; el.textContent = ''; }
    }, 3000);
  } else if (state === 'error') {
    el.classList.add('error');
    el.textContent = '●';
    el.title = 'Auto-save failed';
  }
}

/* ═══════════════════════════════════════════════════════
   DRAG & DROP / FILE PICK
   pickFile() is called from upload.html
═══════════════════════════════════════════════════════ */
function initDropzone() {
  const dz = document.getElementById('dropzone');
  if (!dz) return;
  dz.addEventListener('dragover',  e => { e.preventDefault(); dz.classList.add('over'); });
  dz.addEventListener('dragleave', ()  => dz.classList.remove('over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('over');
    if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]);
  });
  const fi = document.getElementById('fi');
  if (fi) fi.addEventListener('change', e => { if (e.target.files[0]) pickFile(e.target.files[0]); });
}

function pickFile(f) {
  const fname = document.getElementById('fname');
  const fsize = document.getElementById('fsize');
  const frow  = document.getElementById('frow');
  if (fname) fname.textContent = f.name;
  if (fsize) fsize.textContent = fmtB(f.size);
  if (frow)  frow.style.display = 'flex';
  document.getElementById('fi')._f = f;
  doUpload();   // ← auto-parse immediately
}

function fmtB(b) {
  return b < 1024 ? b + ' B' : b < 1048576 ? (b/1024).toFixed(1)+' KB' : (b/1048576).toFixed(1)+' MB';
}

/* ═══════════════════════════════════════════════════════
   PROGRESS BAR  (visual — not real upload %)
═══════════════════════════════════════════════════════ */
let _progressIv = null;

function startProgress() {
  const fill  = document.getElementById('bar-fill');
  const label = document.getElementById('bar-label');
  const wrap  = document.getElementById('upload-progress');
  if (!fill || !label || !wrap) return;
  wrap.style.display = 'block';
  let pct = 0;
  const steps = [
    [0,  20, 800,  'Uploading file…'],
    [20, 55, 2000, 'Extracting text…'],
    [55, 80, 3000, 'Running NLP pipeline…'],
    [80, 92, 2000, 'Detecting entities…'],
    [92, 97, 1500, 'Structuring data…'],
  ];
  let si = 0;
  function tick() {
    if (si >= steps.length) return;
    const [from, to, dur, msg] = steps[si];
    label.textContent = msg;
    const step = (to - from) / (dur / 80);
    pct = from;
    _progressIv = setInterval(() => {
      pct = Math.min(pct + step, to);
      fill.style.width = pct + '%';
      if (pct >= to) { clearInterval(_progressIv); si++; tick(); }
    }, 80);
  }
  tick();
}

function finishProgress() {
  clearInterval(_progressIv);
  const fill  = document.getElementById('bar-fill');
  const label = document.getElementById('bar-label');
  const wrap  = document.getElementById('upload-progress');
  if (fill)  fill.style.width  = '100%';
  if (label) label.textContent = 'Done!';
  setTimeout(() => {
    if (wrap) wrap.style.display = 'none';
    if (fill) fill.style.width   = '0%';
  }, 600);
}

/* ═══════════════════════════════════════════════════════
   UPLOAD  — posts to /upload, then navigates to /parse
═══════════════════════════════════════════════════════ */
async function doUpload() {
  const fi = document.getElementById('fi');
  const f  = fi._f || fi.files[0];
  if (!f) { toast('No file selected', 'err'); return; }
  _file = f.name;

  startProgress();
  showSection('sec-load');
  _t0 = performance.now();
  const timerEl = document.getElementById('timer');
  if (timerEl) {
    _timerIv = setInterval(() => {
      timerEl.textContent = ((performance.now() - _t0) / 1000).toFixed(1) + 's';
    }, 100);
  }

  const stepTimes = [0, 1500, 3500, 6000];
  const stepMsgs  = ['Extracting text…', 'Running NLP pipeline…', 'Detecting entities…', 'Building structured output…'];
  stepTimes.forEach((ms, i) => setTimeout(() => {
    const st = document.getElementById('st' + (i + 1));
    const ls = document.getElementById('lstep');
    if (st) st.classList.add('active');
    if (ls) ls.textContent = stepMsgs[i];
  }, ms));

  try {
    const fd = new FormData(); fd.append('file', f);
    const res  = await fetch('/upload', { method: 'POST', body: fd });
    const json = await res.json();
    clearInterval(_timerIv);
    finishProgress();
    if (!res.ok) throw new Error(json.detail || 'Upload failed');

    // Store result in sessionStorage so parse.html can read it
    sessionStorage.setItem('resumeData',    JSON.stringify(json.data));
    sessionStorage.setItem('resumeFile',    json.filename);
    sessionStorage.setItem('resumeFileUrl', json.file_url);
    sessionStorage.setItem('resumeElapsed', ((performance.now() - _t0) / 1000).toFixed(2));

    // Navigate to parse page (admin keeps ?admin=1)
    const dest = _isAdmin ? '/parse?admin=1' : '/parse';
    window.location.href = dest;

  } catch (err) {
    clearInterval(_timerIv);
    finishProgress();
    hideSection('sec-load');
    showSection('sec-upload');
    toast('Error: ' + err.message, 'err');
  }
}

/* ═══════════════════════════════════════════════════════
   PARSE PAGE INIT  — reads sessionStorage, fills form
═══════════════════════════════════════════════════════ */
function initParsePage() {
  const raw = sessionStorage.getItem('resumeData');
  if (!raw) { window.location.href = _isAdmin ? '/admin' : '/'; return; }

  _orig    = JSON.parse(raw);
  _file    = sessionStorage.getItem('resumeFile')    || '';
  _fileUrl = sessionStorage.getItem('resumeFileUrl') || '';
  const elapsed = sessionStorage.getItem('resumeElapsed') || '?';
  _parsed  = true;

  fillForm(_orig);
  setupViewer(_fileUrl, _file);

  // Admin controls
  if (_isAdmin) {
    const ra = document.getElementById('result-actions');
    const pi = document.getElementById('parsed-indicator');
    const rm = document.getElementById('rmeta');
    const jb = document.getElementById('btn-json');
    if (ra) ra.style.display = 'flex';
    if (pi) pi.style.display = 'none';
    if (rm) rm.textContent   = _file + ' · ' + elapsed + 's';
    if (jb) { jb.disabled = false; jb.style.opacity = '1'; jb.style.cursor = 'pointer'; }
  } else {
    const ra  = document.getElementById('result-actions');
    const pi  = document.getElementById('parsed-indicator');
    const rm2 = document.getElementById('rmeta2');
    if (ra)  ra.style.display  = 'none';
    if (pi)  pi.style.display  = 'flex';
    if (rm2) rm2.textContent   = _file + ' · ' + elapsed + 's';
  }

  toast('Parsed in ' + elapsed + 's', 'ok');
  setTimeout(doSave, 300);

  // Resizer
  initResizer();

  // Ctrl+S
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeJson();
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); if (_parsed) doManualSave(); }
  });
}

/* ═══════════════════════════════════════════════════════
   PDF VIEWER
═══════════════════════════════════════════════════════ */
function setupViewer(fileUrl, filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const lbl = document.getElementById('pdf-label');
  const lnk = document.getElementById('pdf-open');
  const dl  = document.getElementById('dl-link');
  const msg = document.getElementById('no-preview-msg');
  if (lbl) lbl.textContent  = filename;
  if (lnk) lnk.href         = fileUrl;
  if (dl)  { dl.href = fileUrl; dl.download = filename; }
  if (msg) msg.textContent   = ext === 'pdf' ? 'Loading PDF…' : `Preview not available for .${ext} files.`;
  const frame   = document.getElementById('pdf-frame');
  const noPreview = document.getElementById('pdf-no-preview');
  if (ext === 'pdf') {
    if (frame) { frame.src = fileUrl; frame.style.display = 'block'; }
    if (noPreview) noPreview.style.display = 'none';
    if (frame) frame.onerror = () => {
      frame.style.display = 'none';
      if (noPreview) noPreview.style.display = 'flex';
    };
  } else {
    if (frame) frame.style.display = 'none';
    if (noPreview) noPreview.style.display = 'flex';
  }
}

/* ═══════════════════════════════════════════════════════
   RESIZER
═══════════════════════════════════════════════════════ */
function initResizer() {
  const resizer    = document.getElementById('resizer');
  const pdfPanel   = document.getElementById('pdf-panel');
  const splitLayout = document.getElementById('split-layout');
  if (!resizer || !pdfPanel || !splitLayout) return;
  let isResizing = false;
  resizer.addEventListener('mousedown', () => {
    isResizing = true; resizer.classList.add('dragging');
    document.body.style.userSelect = 'none'; document.body.style.cursor = 'col-resize';
  });
  document.addEventListener('mousemove', e => {
    if (!isResizing) return;
    const rect = splitLayout.getBoundingClientRect();
    pdfPanel.style.width = Math.max(240, Math.min(e.clientX - rect.left, rect.width - 240)) + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!isResizing) return;
    isResizing = false; resizer.classList.remove('dragging');
    document.body.style.userSelect = ''; document.body.style.cursor = '';
  });
}

/* ═══════════════════════════════════════════════════════
   SALARY VALIDATION
═══════════════════════════════════════════════════════ */
function validateSalary(inp, errId) {
  const raw     = inp.value;
  const errEl   = document.getElementById(errId);
  const cleaned = raw.replace(/[^0-9]/g, '');
  if (cleaned !== raw) inp.value = cleaned;
  if (!cleaned) { inp.classList.remove('err'); errEl.style.display='none'; errEl.textContent=''; return true; }
  const n = parseInt(cleaned, 10);
  if (n <= 0) { inp.classList.add('err'); errEl.textContent='Salary must be greater than 0.'; errEl.style.display='block'; return false; }
  inp.classList.remove('err'); errEl.style.display='none'; errEl.textContent=''; return true;
}

function getSalaryValue(id) {
  const v = (document.getElementById(id)?.value || '').replace(/[^0-9]/g, '');
  const n = parseInt(v, 10);
  return (!v || n <= 0) ? null : n;
}

function clearFieldErr(inputId, errId) {
  const inp = document.getElementById(inputId), err = document.getElementById(errId);
  if (inp && inp.value.replace(/[^0-9]/g, '').length > 0) {
    inp.classList.remove('err');
    if (err) { err.style.display = 'none'; err.textContent = ''; }
  }
}

/* ═══════════════════════════════════════════════════════
   URL VALIDATION
═══════════════════════════════════════════════════════ */
function validateUrl(inp, errId, linkId, requiredDomain) {
  const val      = inp.value.trim();
  const errEl    = document.getElementById(errId);
  const linkEl   = document.getElementById(linkId);
  const statusEl = document.getElementById(errId.replace('-err', '-status'));
  if (!val) {
    inp.classList.remove('err');
    if (errEl)   { errEl.style.display='none'; errEl.textContent=''; }
    if (linkEl)  { linkEl.style.display='none'; linkEl.innerHTML=''; }
    if (statusEl)  statusEl.textContent='';
    return true;
  }
  let url = val;
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  let parsed;
  try { parsed = new URL(url); } catch(_) { _setUrlErr(inp,errEl,linkEl,statusEl,'Not a valid URL.'); return false; }
  if (!parsed.hostname.includes(requiredDomain)) {
    _setUrlErr(inp, errEl, linkEl, statusEl, `URL must be a ${requiredDomain} link.`); return false;
  }
  inp.value = url; inp.classList.remove('err');
  if (errEl)   { errEl.style.display='none'; errEl.textContent=''; }
  if (statusEl){ statusEl.textContent='✓'; statusEl.style.color='#38A169'; }
  if (linkEl)  { linkEl.innerHTML=`<a href="${url}" target="_blank" rel="noopener">Open ↗</a>`; linkEl.style.display='block'; }
  return true;
}

function _setUrlErr(inp, errEl, linkEl, statusEl, msg) {
  inp.classList.add('err');
  if (errEl)   { errEl.textContent=msg; errEl.style.display='block'; }
  if (linkEl)  { linkEl.style.display='none'; linkEl.innerHTML=''; }
  if (statusEl){ statusEl.textContent='✗'; statusEl.style.color='#E53E3E'; }
}

/* ═══════════════════════════════════════════════════════
   NOTICE PERIOD
═══════════════════════════════════════════════════════ */
function setNotice(value) {
  document.querySelectorAll('input[name="notice"]').forEach(r => r.checked = (r.value === value));
}
function getNotice() {
  const c = document.querySelector('input[name="notice"]:checked'); return c ? c.value : null;
}
function clearNotice()    { document.querySelectorAll('input[name="notice"]').forEach(r => r.checked=false); clearNoticeErr(); }
function clearNoticeErr() { const el=document.getElementById('notice-required-msg'); if(el) el.style.display='none'; }

/* ═══════════════════════════════════════════════════════
   CURRENT POSITION HELPERS
═══════════════════════════════════════════════════════ */
const _TITLE_ADJ_PREFIX = /^(?:experienced|dynamic|motivated|seasoned|dedicated|strategic|accomplished|passionate|proactive|innovative|skilled|qualified|certified|driven|oriented|focused|committed|enthusiastic|creative|analytical|diligent|hardworking|versatile|resourceful|competent|proficient|talented|ambitious|goal[\s-]oriented|result[s]?[\s-]oriented|result[s]?[\s-]driven|results[\s-]oriented|results[\s-]driven|detail[\s-]oriented|self[\s-]motivated|self[\s-]driven|customer[\s-]focused|customer[\s-]centric|highly\s+motivated|highly\s+skilled|highly\s+experienced|well[\s-]experienced|well[\s-]versed|process[\s-]oriented|solution[\s-]oriented|quality[\s-]driven|data[\s-]driven|team[\s-]oriented|people[\s-]oriented)[\s,;:\-]+/gi;

function cleanPositionTitle(raw) {
  if (!raw) return raw;
  let t = raw.trim();
  for (let i = 0; i < 3; i++) {
    const s = t.replace(_TITLE_ADJ_PREFIX, '').trim().replace(/^[,;:\-\s]+/, '').trim();
    if (s === t) break; t = s; _TITLE_ADJ_PREFIX.lastIndex = 0;
  }
  return t.replace(/\s{2,}/g, ' ').trim();
}

function fillCurrentPosition(cpData) {
  const posInp   = document.getElementById('p-pos');
  const badgeDiv = document.getElementById('p-pos-badge');
  const srcNote  = document.getElementById('p-pos-src');
  if (!cpData || cpData.source==='none' || !cpData.current_position || cpData.current_position==='Not clearly identifiable') {
    if (badgeDiv) badgeDiv.style.display='none';
    if (posInp)   posInp.value='';
    if (srcNote)  srcNote.textContent='';
    return;
  }
  const cleanTitle = cleanPositionTitle(cpData.current_position);
  if (posInp) posInp.value = cleanTitle;
  const srcLabel = {'summary':'From summary','work_experience':'From work history'}[cpData.source] || 'Auto-detected';
  const yrsText  = cpData.years_of_experience ? ` · ${cpData.years_of_experience}` : '';
  if (badgeDiv) {
    badgeDiv.innerHTML = `<div class="pos-badge">
      <svg class="pos-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>
      </svg>
      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${x(cleanTitle)}${x(yrsText)}</span>
      <span class="pos-src">${x(srcLabel)}</span>
    </div>`;
    badgeDiv.style.display = 'block';
  }
  if (srcNote) srcNote.textContent = cpData.years_of_experience ? `Experience mentioned: ${cpData.years_of_experience}` : '';
}

/* ═══════════════════════════════════════════════════════
   FILL FORM
═══════════════════════════════════════════════════════ */
function fillForm(d) {
  const n = d.candidate_name || {};
  sv('p-fn', n.first_name||''); sv('p-ln', n.family_name||'');
  const mid = n.middle_name || '';
  if (mid) { sv('p-mn', mid); const r=document.getElementById('p-mn-row'); if(r) r.style.display='block'; }
  else      { sv('p-mn', ''); const r=document.getElementById('p-mn-row'); if(r) r.style.display='none';  }

  const emails = d.email || [];
  sv('p-em', Array.isArray(emails) ? (emails[0]||'') : emails);
  const phones = d.phone_number || d.phone || [];
  if (phones.length) { const p0=phones[0]; sv('p-ph', typeof p0==='string' ? p0 : (p0.raw||p0.e164||'')); }
  const loc = d.location || {};
  sv('p-cy', loc.city||''); sv('p-cn', [loc.state, loc.country].filter(Boolean).join(', '));
  const ws = d.websites || [];
  sv('p-li', (ws.find(w=>(w.domain||'').includes('linkedin'))||{}).url||'');
  sv('p-gh', (ws.find(w=>(w.domain||'').includes('github'))||{}).url||'');
  setTimeout(() => {
    validateUrl(document.getElementById('p-li'), 'p-li-err', 'p-li-link', 'linkedin.com');
    validateUrl(document.getElementById('p-gh'), 'p-gh-err', 'p-gh-link', 'github.com');
  }, 0);
  sv('p-ex',  d.total_years_experience||'');
  sv('p-nat', d.nationality||'');
  fillCurrentPosition(d.current_position||null);
  sv('p-csal', d.current_salary  ? String(d.current_salary)  : '');
  sv('p-esal', d.expected_salary ? String(d.expected_salary) : '');
  if (d.notice_period) setNotice(d.notice_period);
  drawSummary(d.summary||[]);
  sv('p-int', Array.isArray(d.interests) ? (d.interests||[]).join(', ') : (d.interests||''));
  drawExp(d.work_experience||[]);
  drawEdu(d.education||[]);
  const raw = d.skills || [];
  _skills = raw
    .map(s => typeof s==='string' ? s : (s.name||s.skill_name||''))
    .map(s => s.trim()).filter(Boolean)
    .filter((s,i,arr) => arr.findIndex(t=>t.toLowerCase()===s.toLowerCase())===i);
  drawSkills();
  drawProj(d.projects||[]);
  drawCert(d.certifications||[]);
  drawLang(d.languages||[]);
  drawAch(d.achievements||[]);
}

function sv(id, v) { const e=document.getElementById(id); if(e) e.value=v??''; }
function gv(id)    { return (document.getElementById(id)?.value||'').trim(); }

/* ═══════════════════════════════════════════════════════
   SUMMARY
═══════════════════════════════════════════════════════ */
function drawSummary(raw) {
  const list=document.getElementById('sum-list'), empty=document.getElementById('sum-empty');
  if (!list) return;
  list.innerHTML = '';
  let sentences = Array.isArray(raw) ? raw.filter(s=>s&&s.trim())
    : typeof raw==='string' && raw.trim()
      ? raw.replace(/\n+/g,' ').split(/(?<=[.!?])\s+/).map(s=>s.trim()).filter(s=>s.length>8)
      : [];
  if (!sentences.length) { if(empty) empty.style.display='block'; return; }
  if (empty) empty.style.display='none';
  sentences.forEach((s,i) => {
    const row = document.createElement('div');
    row.setAttribute('data-text', s);
    row.style.cssText = 'display:flex;align-items:flex-start;gap:10px;padding:2px 0;';
    row.innerHTML = `<span style="flex-shrink:0;font-size:.825rem;font-weight:600;color:#4A5568;min-width:18px;line-height:1.6;">${i+1}.</span>
      <p style="margin:0;font-size:.825rem;color:#2D3748;line-height:1.6;flex:1;">${x(s)}</p>`;
    list.appendChild(row);
  });
}

/* ═══════════════════════════════════════════════════════
   EXPERIENCE
═══════════════════════════════════════════════════════ */
function drawExp(items) {
  const c = document.getElementById('exp-list'); if (!c) return; c.innerHTML='';
  if (!items.length) { addExp(); return; }
  items.forEach((it,i) => {
    const sd=it.work_experience_start_date||{}, ed=it.work_experience_end_date||{};
    c.appendChild(expCard(i,
      it.work_experience_job_title||'', it.work_experience_organization||'',
      it.work_experience_location||'',
      sd.date||(sd.year?String(sd.year):'')||'',
      ed.is_current?'':(ed.date||(ed.year?String(ed.year):'')||''),
      ed.is_current||false, it.work_experience_description||''
    ));
  });
}
function expCard(i, title, org, loc, start, end, cur, desc) {
  const d = document.createElement('div'); d.className='ecard';
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <span style="font-size:.68rem;font-weight:700;color:#4F6EF7;background:#EEF2FF;padding:1px 7px;border-radius:4px;">Exp ${i+1}</span>
      <button class="btn-del" onclick="rmCard(this)">Remove</button>
    </div>
    <div class="g2">
      <div><label class="lbl">Title</label>  <input name="t" class="inp" value="${x(title)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Company</label><input name="o" class="inp" value="${x(org)}" oninput="scheduleAutoSave()" /></div>
      <div class="span2"><label class="lbl">Location</label><input name="l" class="inp" value="${x(loc)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Start</label>  <input name="s" class="inp" value="${x(start)}" placeholder="YYYY or YYYY-MM" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">End</label>
        <div style="display:flex;align-items:center;gap:6px;">
          <input name="e" class="inp" style="flex:1;" value="${x(end)}" ${cur?'disabled':''} placeholder="YYYY or Present" oninput="scheduleAutoSave()" />
          <label style="display:flex;align-items:center;gap:3px;font-size:.7rem;color:#718096;white-space:nowrap;cursor:pointer;">
            <input type="checkbox" name="cur" ${cur?'checked':''} onchange="this.closest('.ecard').querySelector('[name=e]').disabled=this.checked;scheduleAutoSave()" /> Present
          </label>
        </div>
      </div>
    </div>
    <div style="margin-top:8px;"><label class="lbl">Description</label>
      <textarea name="d" class="inp" rows="3" oninput="scheduleAutoSave()">${x(desc)}</textarea></div>`;
  return d;
}
function addExp() {
  const c = document.getElementById('exp-list'); if(!c) return;
  c.appendChild(expCard(c.children.length,'','','','','',false,'')); scheduleAutoSave();
}

/* ═══════════════════════════════════════════════════════
   EDUCATION
═══════════════════════════════════════════════════════ */
function drawEdu(items) {
  const c=document.getElementById('edu-list'); if(!c) return; c.innerHTML='';
  if (!items.length) { addEdu(); return; }
  items.forEach((it,i) => c.appendChild(eduCard(i,
    it.education_degree||'', it.education_organization||'',
    it.education_field_of_study||'', it.education_level||'',
    (it.education_grade||{}).score||(it.education_grade||{}).gradeScore||'',
    it.education_start_year||'', it.education_end_year||''
  )));
}
function eduCard(i, deg, org, fos, lvl, grade, sy, ey) {
  const d=document.createElement('div'); d.className='ecard';
  const lvls=['','bachelor','master','doctoral','diploma','associate','12th','10th'];
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <span style="font-size:.68rem;font-weight:700;color:#38A169;background:#F0FFF4;padding:1px 7px;border-radius:4px;">Edu ${i+1}</span>
      <button class="btn-del" onclick="rmCard(this)">Remove</button>
    </div>
    <div class="g2">
      <div class="span2"><label class="lbl">Degree</label>     <input name="deg" class="inp" value="${x(deg)}" oninput="scheduleAutoSave()" /></div>
      <div class="span2"><label class="lbl">Institution</label><input name="org" class="inp" value="${x(org)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Field / Major</label><input name="fos" class="inp" value="${x(fos)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Level</label>
        <select name="lvl" class="inp" onchange="scheduleAutoSave()">
          ${lvls.map(v=>`<option value="${v}" ${v===(lvl||'').toLowerCase()?'selected':''}>${v||'— select —'}</option>`).join('')}
        </select>
      </div>
      <div><label class="lbl">Grade/CGPA</label><input name="gr" class="inp" value="${x(grade)}" oninput="scheduleAutoSave()" /></div>
      <div style="display:flex;gap:6px;">
        <div style="flex:1;"><label class="lbl">Start Year</label><input name="sy" class="inp" value="${x(sy)}" oninput="scheduleAutoSave()" /></div>
        <div style="flex:1;"><label class="lbl">End Year</label>  <input name="ey" class="inp" value="${x(ey)}" oninput="scheduleAutoSave()" /></div>
      </div>
    </div>`;
  return d;
}
function addEdu() {
  const c=document.getElementById('edu-list'); if(!c) return;
  c.appendChild(eduCard(c.children.length,'','','','','','','')); scheduleAutoSave();
}

/* ═══════════════════════════════════════════════════════
   SKILLS
═══════════════════════════════════════════════════════ */
function drawSkills() {
  const cloud=document.getElementById('skill-tag-cloud');
  const empty=document.getElementById('skill-empty');
  const badge=document.getElementById('skill-count-badge');
  if (!cloud) return;
  cloud.innerHTML = '';
  if (!_skills.length) { if(empty) empty.style.display='block'; if(badge) badge.textContent=''; return; }
  if (empty) empty.style.display='none';
  if (badge) badge.textContent=_skills.length+' skills';
  _skills.forEach((name,idx) => {
    const tag=document.createElement('span'); tag.className='stag';
    tag.dataset.idx=idx; tag.dataset.name=name.toLowerCase();
    tag.innerHTML=`${x(name)}<span class="x" onclick="rmSkill(${idx})">&times;</span>`;
    cloud.appendChild(tag);
  });
  const q=(document.getElementById('skill-search')?.value||'').trim();
  if (q) filterSkills(q);
}
function rmSkill(idx) {
  _skills.splice(idx,1);
  const ss=document.getElementById('skill-search'); if(ss) ss.value='';
  drawSkills(); scheduleAutoSave();
}
function addSkill() {
  const inp=document.getElementById('skill-in'); if(!inp) return;
  const v=inp.value.trim(); if(!v) return;
  if (_skills.some(s=>s.toLowerCase()===v.toLowerCase())) { toast('Skill already exists','inf'); inp.value=''; return; }
  _skills.push(v); drawSkills(); inp.value=''; inp.focus(); scheduleAutoSave();
}
function filterSkills(q) {
  const tags=document.querySelectorAll('#skill-tag-cloud .stag');
  if (!q.trim()) { tags.forEach(t=>t.classList.remove('dim','match')); return; }
  const lower=q.toLowerCase();
  tags.forEach(t => {
    const name=t.dataset.name||'';
    if (name.includes(lower)) { t.classList.add('match'); t.classList.remove('dim'); }
    else                      { t.classList.add('dim');   t.classList.remove('match'); }
  });
}

/* ═══════════════════════════════════════════════════════
   PROJECTS
═══════════════════════════════════════════════════════ */
function drawProj(items) {
  const c=document.getElementById('proj-list'); if(!c) return; c.innerHTML='';
  items.forEach((it,i) => c.appendChild(projCard(i, it.project_title||'', it.project_description||'', it.project_role||'', (it.project_technologies||[]).join(', '))));
}
function projCard(i, title, desc, role, tech) {
  const d=document.createElement('div'); d.className='ecard';
  d.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <span style="font-size:.68rem;font-weight:700;color:#D97706;background:#FFFBEB;padding:1px 7px;border-radius:4px;">Project ${i+1}</span>
      <button class="btn-del" onclick="rmCard(this)">Remove</button>
    </div>
    <div class="g2">
      <div class="span2"><label class="lbl">Title</label><input name="t" class="inp" value="${x(title)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Role</label>         <input name="r"    class="inp" value="${x(role)}" oninput="scheduleAutoSave()" /></div>
      <div><label class="lbl">Technologies</label> <input name="tech" class="inp" value="${x(tech)}" placeholder="Python, FastAPI…" oninput="scheduleAutoSave()" /></div>
      <div class="span2"><label class="lbl">Description</label>
        <textarea name="d" class="inp" rows="3" oninput="scheduleAutoSave()">${x(desc)}</textarea></div>
    </div>`;
  return d;
}
function addProj() {
  const c=document.getElementById('proj-list'); if(!c) return;
  c.appendChild(projCard(c.children.length,'','','','')); scheduleAutoSave();
}

/* ═══════════════════════════════════════════════════════
   CERTIFICATIONS
═══════════════════════════════════════════════════════ */
function drawCert(items) {
  const c=document.getElementById('cert-list'); if(!c) return; c.innerHTML='';
  items.forEach(it=>addCertRow(c, typeof it==='string'?it:(it.name||'')));
}
function addCertRow(container, val='') {
  const div=document.createElement('div'); div.style.cssText='display:flex;align-items:center;gap:6px;';
  div.innerHTML=`<input class="inp" style="flex:1;" value="${x(val)}" placeholder="Certification name" oninput="scheduleAutoSave()" />
    <button class="btn-del" onclick="this.parentElement.remove();scheduleAutoSave()">×</button>`;
  container.appendChild(div);
}
function addCert() { addCertRow(document.getElementById('cert-list')); scheduleAutoSave(); }

/* ═══════════════════════════════════════════════════════
   LANGUAGES
═══════════════════════════════════════════════════════ */
function drawLang(items) {
  const c=document.getElementById('lang-list'); if(!c) return; c.innerHTML='';
  items.forEach((it,i)=>c.appendChild(langCard(i,(it.language_name||{}).label||it.language||'',(it.language_proficiency||{}).value||it.proficiency||'')));
}
function langCard(i, name, prof) {
  const d=document.createElement('div'); d.className='ecard';
  const opts=['','Native or bilingual proficiency','Full professional proficiency','Professional working proficiency','Limited working proficiency','Elementary proficiency'];
  d.innerHTML=`<div style="display:flex;align-items:center;gap:8px;">
    <div style="flex:1;"><label class="lbl">Language</label><input name="lang" class="inp" value="${x(name)}" oninput="scheduleAutoSave()" /></div>
    <div style="flex:1;"><label class="lbl">Proficiency</label>
      <select name="prof" class="inp" onchange="scheduleAutoSave()">
        ${opts.map(v=>`<option value="${v}" ${v===prof?'selected':''}>${v||'— select —'}</option>`).join('')}
      </select></div>
    <button class="btn-del" style="margin-top:17px;" onclick="rmCard(this)">×</button>
  </div>`;
  return d;
}
function addLang() {
  const c=document.getElementById('lang-list'); if(!c) return;
  c.appendChild(langCard(c.children.length,'','')); scheduleAutoSave();
}

/* ═══════════════════════════════════════════════════════
   ACHIEVEMENTS
═══════════════════════════════════════════════════════ */
function drawAch(items) {
  const c=document.getElementById('ach-list'); if(!c) return; c.innerHTML='';
  items.forEach(it=>addAchRow(c, typeof it==='string'?it:(it.text||'')));
}
function addAchRow(container, val='') {
  const d=document.createElement('div'); d.style.cssText='display:flex;align-items:center;gap:6px;';
  d.innerHTML=`<input class="inp" style="flex:1;" value="${x(val)}" placeholder="Achievement or award" oninput="scheduleAutoSave()" />
    <button class="btn-del" onclick="this.parentElement.remove();scheduleAutoSave()">×</button>`;
  container.appendChild(d);
}
function addAch() { addAchRow(document.getElementById('ach-list')); scheduleAutoSave(); }

function rmCard(btn) {
  const c=btn.closest('.ecard');
  c.style.opacity='0'; c.style.transform='translateY(-4px)'; c.style.transition='all .15s';
  setTimeout(()=>{ c.remove(); scheduleAutoSave(); }, 150);
}

/* ═══════════════════════════════════════════════════════
   COLLECT FORM
═══════════════════════════════════════════════════════ */
function collect(silent=false) {
  let hasError = false;

  const csalEl=document.getElementById('p-csal'), csalErr=document.getElementById('p-csal-err');
  const csalOk=validateSalary(csalEl,'p-csal-err'), csalVal=getSalaryValue('p-csal');
  if (!silent) {
    if (!csalVal) { csalEl.classList.add('err'); csalErr.textContent='Current salary is required.'; csalErr.style.display='block'; hasError=true; }
    else if (!csalOk) hasError=true;
  }

  const esalEl=document.getElementById('p-esal'), esalErr=document.getElementById('p-esal-err');
  const esalOk=validateSalary(esalEl,'p-esal-err'), esalVal=getSalaryValue('p-esal');
  if (!silent) {
    if (!esalVal) { esalEl.classList.add('err'); esalErr.textContent='Expected salary is required.'; esalErr.style.display='block'; hasError=true; }
    else if (!esalOk) hasError=true;
  }

  const noticeVal=getNotice(), noticeWrap=document.getElementById('notice-required-msg');
  if (!silent && !noticeVal) { if(noticeWrap) noticeWrap.style.display='block'; hasError=true; }
  else { if(noticeWrap) noticeWrap.style.display='none'; }

  if (!silent && hasError) {
    toast('Please fill in all required fields (salary & notice period).','err');
    document.querySelector('#form-panel')?.scrollTo({top:0,behavior:'smooth'});
    return null;
  }

  const midVal=(document.getElementById('p-mn')?.value||'').trim();
  const candidateName={first_name:gv('p-fn'), family_name:gv('p-ln')};
  if (midVal) candidateName.middle_name=midVal;

  const summaryItems=[...document.querySelectorAll('#sum-list [data-text]')]
    .map(el=>el.getAttribute('data-text').trim()).filter(Boolean);

  const d = {
    candidate_name: candidateName,
    email:          [gv('p-em')].filter(Boolean),
    phone_number:   gv('p-ph') ? [{raw:gv('p-ph')}] : [],
    location:       {city:gv('p-cy'), country:gv('p-cn')},
    websites:       [],
    total_years_experience: parseFloat(gv('p-ex'))||null,
    nationality:    gv('p-nat')||null,
    summary:        summaryItems.length ? summaryItems : null,
    interests:      gv('p-int') ? gv('p-int').split(',').map(s=>s.trim()).filter(Boolean) : null,
    current_position_title: gv('p-pos')||null,
    current_salary:         csalVal||null,
    expected_salary:        esalVal||null,
    notice_period:          noticeVal||null,
  };

  const li=gv('p-li'), gh=gv('p-gh');
  if (li) d.websites.push({url:li, domain:'linkedin.com'});
  if (gh) d.websites.push({url:gh, domain:'github.com'});

  d.work_experience=[...document.querySelectorAll('#exp-list .ecard')].map(c=>({
    work_experience_job_title:    c.querySelector('[name=t]')?.value||'',
    work_experience_organization: c.querySelector('[name=o]')?.value||'',
    work_experience_location:     c.querySelector('[name=l]')?.value||'',
    work_experience_start_date:   {date:c.querySelector('[name=s]')?.value||null},
    work_experience_end_date:     {date:c.querySelector('[name=cur]')?.checked?null:(c.querySelector('[name=e]')?.value||null), is_current:c.querySelector('[name=cur]')?.checked||false},
    work_experience_description:  c.querySelector('[name=d]')?.value||'',
  }));
  d.education=[...document.querySelectorAll('#edu-list .ecard')].map(c=>({
    education_degree:         c.querySelector('[name=deg]')?.value||'',
    education_organization:   c.querySelector('[name=org]')?.value||'',
    education_field_of_study: c.querySelector('[name=fos]')?.value||'',
    education_level:          c.querySelector('[name=lvl]')?.value||'',
    education_grade:          {score:parseFloat(c.querySelector('[name=gr]')?.value)||null},
    education_start_year:     parseInt(c.querySelector('[name=sy]')?.value)||null,
    education_end_year:       parseInt(c.querySelector('[name=ey]')?.value)||null,
  }));
  d.skills        = [..._skills];
  d.projects      = [...document.querySelectorAll('#proj-list .ecard')].map(c=>({
    project_title:        c.querySelector('[name=t]')?.value||'',
    project_role:         c.querySelector('[name=r]')?.value||'',
    project_technologies: (c.querySelector('[name=tech]')?.value||'').split(',').map(s=>s.trim()).filter(Boolean),
    project_description:  c.querySelector('[name=d]')?.value||'',
  }));
  d.certifications = [...document.querySelectorAll('#cert-list input')].map(i=>i.value).filter(Boolean);
  d.languages      = [...document.querySelectorAll('#lang-list .ecard')].map(c=>({
    language_name:        {label:c.querySelector('[name=lang]')?.value||'', value:''},
    language_proficiency: {value:c.querySelector('[name=prof]')?.value||''},
  }));
  d.achievements   = [...document.querySelectorAll('#ach-list input')].map(i=>i.value).filter(Boolean);
  return d;
}

/* ═══════════════════════════════════════════════════════
   SAVE
═══════════════════════════════════════════════════════ */
async function doSave() {
  // Auto-save: JSON only, no Excel write (manual=false)
  const payload = collect(true);
  if (!payload) return;
  setAutoSaveStatus('saving');
  try {
    const res  = await fetch('/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filename: _file, data: payload, manual: false}),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Save failed');
    setAutoSaveStatus('saved');
  } catch(err) { setAutoSaveStatus('error'); }
}

async function doManualSave() {
  // Manual save: validates required fields, writes JSON + Excel (manual=true)
  if (!_parsed) return;
  clearTimeout(_autoSaveTimer);
  let hasError = false;

  const csalEl  = document.getElementById('p-csal');
  const csalErr = document.getElementById('p-csal-err');
  const csalVal = getSalaryValue('p-csal');
  if (!csalVal) {
    csalEl.classList.add('err');
    csalErr.textContent   = 'Current salary is required.';
    csalErr.style.display = 'block';
    hasError = true;
  } else { validateSalary(csalEl, 'p-csal-err'); }

  const esalEl  = document.getElementById('p-esal');
  const esalErr = document.getElementById('p-esal-err');
  const esalVal = getSalaryValue('p-esal');
  if (!esalVal) {
    esalEl.classList.add('err');
    esalErr.textContent   = 'Expected salary is required.';
    esalErr.style.display = 'block';
    hasError = true;
  } else { validateSalary(esalEl, 'p-esal-err'); }

  const noticeVal = getNotice();
  const noticeMsg = document.getElementById('notice-required-msg');
  if (!noticeVal) {
    if (noticeMsg) noticeMsg.style.display = 'block';
    hasError = true;
  } else {
    if (noticeMsg) noticeMsg.style.display = 'none';
  }

  if (hasError) {
    toast('Current salary, expected salary and notice period are required.', 'err');
    document.getElementById('form-panel')?.scrollTo({top: 0, behavior: 'smooth'});
    return;
  }

  const btn = document.getElementById('btn-save-manual');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  setAutoSaveStatus('saving');

  try {
    const payload = collect(true);
    const res = await fetch('/save', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({filename: _file, data: payload, manual: true}),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Save failed');
    setAutoSaveStatus('saved');
    // Tell user whether Excel was updated or just JSON
    const msg = json.excel_updated ? 'Saved! Excel updated.' : 'Saved! (JSON only)';
    toast(msg, 'ok');
  } catch(err) {
    setAutoSaveStatus('error');
    toast('Save failed: ' + err.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 Save'; }
  }
}

/* ═══════════════════════════════════════════════════════
   JSON MODAL  (admin only)
═══════════════════════════════════════════════════════ */
function openJson() {
  if (!_isAdmin) { toast('Not available','err'); return; }
  if (!_parsed||!_orig) { toast('No data loaded','inf'); return; }
  document.getElementById('jcode').textContent=JSON.stringify(_orig,null,2);
  document.getElementById('jmodal').style.display='flex';
  document.body.style.overflow='hidden';
}
function closeJson(e) {
  if (!e||e.target===document.getElementById('jmodal')||e.target.tagName==='BUTTON') {
    document.getElementById('jmodal').style.display='none';
    document.body.style.overflow='';
  }
}
function copyJson() {
  navigator.clipboard.writeText(document.getElementById('jcode').textContent).then(()=>toast('Copied!','inf'));
}

/* ═══════════════════════════════════════════════════════
   BACK / NEW  (admin only — clears session and goes home)
═══════════════════════════════════════════════════════ */
function goBack() {
  if (!_isAdmin) return;
  sessionStorage.removeItem('resumeData');
  sessionStorage.removeItem('resumeFile');
  sessionStorage.removeItem('resumeFileUrl');
  sessionStorage.removeItem('resumeElapsed');
  window.location.href = '/admin';
}

/* ═══════════════════════════════════════════════════════
   SECTION HELPERS  (used on upload page only)
═══════════════════════════════════════════════════════ */
function showSection(id) { const el=document.getElementById(id); if(el) el.style.display='flex'; }
function hideSection(id) { const el=document.getElementById(id); if(el) el.style.display='none'; }

/* ═══════════════════════════════════════════════════════
   UTILITIES
═══════════════════════════════════════════════════════ */
function x(s) {
  return String(s??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function toast(msg, type) {
  const c=document.getElementById('toasts'), t=document.createElement('div');
  t.className='toast '+(type||'inf');
  t.innerHTML=`<span>${{ok:'✓',err:'✗',inf:'ℹ'}[type]||'ℹ'}</span><span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(()=>{ t.style.opacity='0'; t.style.transition='opacity .3s'; setTimeout(()=>t.remove(),300); }, 4000);
}