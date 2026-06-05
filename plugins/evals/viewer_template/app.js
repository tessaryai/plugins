(() => {
  const DATA = JSON.parse(document.getElementById('data').textContent);
  const CONFIG = JSON.parse(document.getElementById('config').textContent);
  const CTA_URL = CONFIG.cta_url;
  const CTA_LABEL = CONFIG.cta_label || 'Open destination';

  const pipeline = DATA.pipeline || {};
  const graders = DATA.graders || [];

  const callSites = pipeline.call_sites || [];
  const failureModes = pipeline.failure_modes || [];
  const taxonomy = pipeline.taxonomy || [];
  const invariants = pipeline.implicit_invariants || [];
  const profile = pipeline.product_profile || {};
  // Failure-mode lookup retained for backlinks (e.g. resolving a grader's
  // taxonomy node via its failure mode). Pack / compliance / Layer data is
  // not rendered in the viewer chrome.
  const fmById = new Map(failureModes.map(fm => [fm.id, fm]));

  // Taxonomy comes in two shapes: flat (each node has parent_id) and nested
  // (each top-level has children[]). Walk both into a single flat list +
  // children map keyed by parent.
  const taxonomyFlat = [];
  const taxonomyChildren = new Map(); // parent_id -> [child, …]
  function walkTaxonomy(node, parentId) {
    taxonomyFlat.push(node);
    const pid = parentId || node.parent_id || '__root__';
    if (!taxonomyChildren.has(pid)) taxonomyChildren.set(pid, []);
    taxonomyChildren.get(pid).push(node);
    (node.children || []).forEach(c => walkTaxonomy(c, node.id));
  }
  taxonomy.forEach(t => walkTaxonomy(t, null));

  const gradersById = new Map(graders.map(g => [g.id, g]));
  const callSitesById = new Map(callSites.map(cs => [cs.id, cs]));
  const taxonomyById = new Map(taxonomyFlat.map(t => [t.id, t]));
  const fmsByCallSite = groupBy(failureModes, f => f.call_site_id);
  const qualityDimensions = pipeline.quality_dimensions || [];
  const qdByCallSite = groupBy(qualityDimensions, q => q.call_site_id);
  const fmsByTaxonomy = groupBy(failureModes, f => f.taxonomy_node_id);
  const fmsByGrader = groupBy(failureModes, f => f.grader_id);

  // v3: invariants render inside the Graders table as "global" rows, so the
  // sidebar Graders count is the union.
  const totalGraders = graders.length + invariants.length;

  function plural(n, singular, pluralForm) {
    return `${n} ${n === 1 ? singular : (pluralForm || singular + 's')}`;
  }
  const progress = pipeline.progress || {};
  const sitesCompleted = Number(progress.sites_completed) || 0;
  const sitesTotal = Number(progress.sites_total) || callSites.length;
  const deferredCount = Number(progress.deferred_failure_count) || 0;
  const subParts = [`${plural(callSites.length, 'LLM call')}`,
                    `${plural(totalGraders, 'grader')}`];
  if (sitesTotal && sitesCompleted < sitesTotal) {
    subParts.push(`${sitesCompleted}/${sitesTotal} complete`);
  }
  if (deferredCount > 0) {
    subParts.push(`${deferredCount} deferred`);
  }
  document.getElementById('brand-sub').textContent = subParts.join(' · ');

  // v3 sidebar: exactly three sections.
  const views = [
    { id: 'overview', label: 'Overview',  count: null },
    { id: 'llmcalls', label: 'LLM Calls', count: callSites.length },
    { id: 'graders',  label: 'Graders',   count: totalGraders },
  ];

  const nav = document.getElementById('nav');
  views.forEach((v, i) => {
    const a = document.createElement('a');
    a.href = '#' + v.id;
    a.dataset.view = v.id;
    a.innerHTML = `
      <span class="nav-num">${pad2(i + 1)}</span>
      <span class="nav-label">${escapeHtml(v.label)}</span>
      ${v.count != null ? `<span class="count">${v.count}</span>` : '<span></span>'}
    `;
    a.addEventListener('click', e => { e.preventDefault(); show(v.id); });
    nav.appendChild(a);
  });
  const navRule = document.createElement('div');
  navRule.className = 'nav-rule';
  nav.appendChild(navRule);
  const navFoot = document.createElement('div');
  navFoot.className = 'nav-foot';
  navFoot.textContent = pipeline.version
    ? `synthesize-graders · schema ${pipeline.version}`
    : 'synthesize-graders';
  nav.appendChild(navFoot);

  // ---------- utilities ----------

  function groupBy(arr, keyFn) {
    const m = new Map();
    arr.forEach(x => {
      const k = keyFn(x);
      if (k == null) return;
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(x);
    });
    return m;
  }
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function pad2(n) { return String(n).padStart(2, '0'); }
  function humanize(s) {
    if (s == null || s === '') return '';
    return String(s)
      .replace(/[_\-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b([a-z])/g, (_, c) => c.toUpperCase());
  }
  function stripIdPrefix(id) {
    if (id == null || id === '') return '';
    const parts = String(id).split('::');
    return parts[parts.length - 1];
  }
  function titleFor() {
    for (const c of arguments) {
      if (c != null && c !== '') return humanize(c);
    }
    return '';
  }
  function chip(text, cls = '') {
    if (text == null || text === '') return '';
    return `<span class="chip ${cls}">${escapeHtml(humanize(text))}</span>`;
  }
  function rawChip(text, cls = '') {
    if (text == null || text === '') return '';
    return `<span class="chip ${cls}">${escapeHtml(text)}</span>`;
  }
  function invocationLabel(inv) {
    switch (inv) {
      case 'cli_agent': return 'Agent CLI';
      case 'http': return 'Raw HTTP';
      case 'sandbox_agent': return 'Sandbox';
      case 'sdk': return 'SDK';
      default: return '';
    }
  }
  function scopeChip(scope) {
    if (!scope) return '';
    const label = scope === 'trace' ? 'multi-turn (trace)' : humanize(scope);
    return `<span class="chip scope" title="Grader scope: ${escapeHtml(scope)}">${escapeHtml(label)}</span>`;
  }
  // Only indirect invocations get a chip — SDK is the default and stays unmarked.
  function invocationChip(inv) {
    if (!inv || inv === 'sdk') return '';
    return `<span class="chip invocation" title="Indirect LLM call (${escapeHtml(inv)}) — reached outside an in-process SDK">${escapeHtml(invocationLabel(inv))}</span>`;
  }
  // Multi-turn sites graded once per conversation get a chip — per_turn is the default and stays unmarked.
  function gradeModeChip(mode) {
    if (mode !== 'per_conversation') return '';
    return `<span class="chip scope" title="Multi-turn site — graded once per conversation (its cross-turn graders use scope: trace)">per conversation</span>`;
  }
  function dot(cls) { return `<span class="dot ${cls}"></span>`; }
  function jumpLink(viewId, anchorId, label) {
    return `<a href="#${escapeHtml(viewId)}" data-jump="${escapeHtml(viewId)}|${escapeHtml(anchorId)}">${escapeHtml(label)}</a>`;
  }
  function unique(arr) {
    const seen = new Set(); const out = [];
    for (const v of arr) { if (v != null && v !== '' && !seen.has(v)) { seen.add(v); out.push(v); } }
    return out;
  }

  // ---------- routing ----------

  function show(viewId) {
    document.querySelectorAll('section.view').forEach(s => s.classList.toggle('active', s.id === 'view-' + viewId));
    document.querySelectorAll('nav.side a').forEach(a => a.classList.toggle('active', a.dataset.view === viewId));
    try { history.replaceState(null, '', '#' + viewId); } catch (_) {}
    window.scrollTo(0, 0);
  }
  function jumpTo(viewId, anchorId) {
    show(viewId);
    requestAnimationFrame(() => {
      const el = document.getElementById(anchorId);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('highlight');
      setTimeout(() => el.classList.remove('highlight'), 1400);
    });
  }

  // ---------- Modal ----------

  const modalRoot = document.createElement('div');
  modalRoot.id = 'modal-root';
  modalRoot.innerHTML = `
    <div class="modal-backdrop" data-close-modal></div>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title-el">
      <div class="modal-head">
        <div class="modal-kicker" id="modal-kicker-el"></div>
        <h3 class="modal-title" id="modal-title-el"></h3>
        <div class="modal-chips" id="modal-chips-el"></div>
        <button class="modal-close" type="button" data-close-modal aria-label="Close">×</button>
      </div>
      <div class="modal-body" id="modal-body-el"></div>
    </div>`;
  document.body.appendChild(modalRoot);

  function openModal({ kicker, title, chips = '', body }) {
    document.getElementById('modal-kicker-el').textContent = kicker;
    document.getElementById('modal-title-el').textContent = title;
    document.getElementById('modal-chips-el').innerHTML = chips;
    document.getElementById('modal-body-el').innerHTML = body;
    document.getElementById('modal-body-el').scrollTop = 0;
    document.body.classList.add('modal-open');
    modalRoot.classList.add('open');
  }
  function closeModal() {
    modalRoot.classList.remove('open');
    document.body.classList.remove('modal-open');
  }
  modalRoot.addEventListener('click', e => {
    if (e.target.matches('[data-close-modal]')) closeModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && modalRoot.classList.contains('open')) closeModal();
  });

  const main = document.getElementById('main');
  function appendSection(id, render) { main.appendChild(buildSection(id, render)); }
  function buildSection(id, htmlStr) {
    const s = document.createElement('section');
    s.id = 'view-' + id;
    s.className = 'view';
    try {
      s.innerHTML = typeof htmlStr === 'function' ? htmlStr() : htmlStr;
    } catch (err) {
      s.innerHTML = `<header class="section-head"><div class="kicker">Error</div><h2>${escapeHtml(id)}</h2></header>
        <div class="empty" style="color:var(--bad);text-align:left;padding:14px;border-color:var(--bad)">
          Render error. Other sections are unaffected.<br>
          <pre style="margin-top:8px;background:transparent;border:0;padding:0;color:var(--bad);font-size:11px">${escapeHtml(String(err && err.stack || err))}</pre>
        </div>`;
    }
    return s;
  }

  function sectionHead(num, title, intro) {
    return `<header class="section-head">
      <div class="kicker">${escapeHtml(pad2(num))} / ${escapeHtml(title)}</div>
      <h2>${escapeHtml(title)}</h2>
      ${intro ? `<p class="view-intro">${escapeHtml(intro)}</p>` : ''}
    </header>`;
  }

  // ---------- 01 Overview ----------

  appendSection('overview', () => `
    ${sectionHead(1, 'Overview', 'A synthesized evaluation pipeline for this product’s LLM surface. The cards below are the two destinations; click either one to drill in.')}

    <div class="stats stats-2col">
      <div class="stat stat-nav" data-nav="llmcalls">
        <div class="l">LLM Calls</div>
        <div class="n">${callSites.length}</div>
        <div class="stat-affordance">View calls →</div>
      </div>
      <div class="stat stat-nav" data-nav="graders">
        <div class="l">Graders</div>
        <div class="n">${totalGraders}</div>
        <div class="stat-affordance">View graders →</div>
      </div>
    </div>

    ${pipeline.product_hint ? `
      <h3>What this product is</h3>
      <div class="card"><div class="desc">${escapeHtml(pipeline.product_hint)}</div></div>
    ` : ''}

    ${renderProfile()}
  `);

  // Packs are present in pipeline.yaml (and survive into the embedded JSON
  // blob so the platform's import path can consume them), but the viewer
  // does not render them — this HTML is a gist of the run, not a curation UI.

  // v3 trims the profile to the five fields that actually shape eval scope.
  function renderProfile() {
    if (!profile || !Object.keys(profile).length) return '';
    const rows = [];
    if (profile.one_line) rows.push(['Summary', escapeHtml(profile.one_line)]);
    if (profile.domain)   rows.push(['Domain', escapeHtml(humanize(profile.domain))]);
    if (typeof profile.regulatory_context === 'string') {
      rows.push(['Regulatory context', escapeHtml(profile.regulatory_context)]);
    } else if (Array.isArray(profile.regulatory_context) && profile.regulatory_context.length) {
      rows.push(['Regulatory context',
        `<div class="chips">${profile.regulatory_context.map(r => rawChip(humanize(r.regime || r), 'muted')).join('')}</div>`]);
    }
    if (Array.isArray(profile.user_types) && profile.user_types.length) {
      rows.push(['User types', renderRoleList(profile.user_types)]);
    }
    if (Array.isArray(profile.user_constraints) && profile.user_constraints.length) {
      rows.push(['User constraints',
        `<ul style="margin:0;padding-left:18px">${profile.user_constraints.map(c => `<li>${escapeHtml(c)}</li>`).join('')}</ul>`]);
    }
    if (!rows.length) return '';
    return `<h3>Product profile</h3>
      <div class="profile-grid">
        ${rows.map(([k, v]) => `<div class="profile-row">
          <div class="pf-key">${escapeHtml(k)}</div>
          <div class="pf-val">${v}</div>
        </div>`).join('')}
      </div>`;
  }

  function renderRoleList(arr) {
    if (!Array.isArray(arr) || !arr.length) return '';
    return `<div class="role-list">${arr.map(u => {
      const name = humanize(u.role || u.kind || 'User');
      const bits = [];
      if (u.surface)     bits.push(`Surface — ${escapeHtml(u.surface)}`);
      if (u.constraints) bits.push(`Constraints — ${escapeHtml(u.constraints)}`);
      const body = bits.join(' &nbsp;·&nbsp; ');
      const ev = Array.isArray(u.evidence) ? u.evidence : (u.evidence ? [u.evidence] : []);
      const fallback = !body && !ev.length ? '<span style="color:var(--muted-2)">—</span>' : '';
      return `<div class="role-line">
        <div class="role-name">${escapeHtml(name)}</div>
        <div class="role-body">${body}${ev.length ? renderEvidence(ev) : ''}${fallback}</div>
      </div>`;
    }).join('')}</div>`;
  }

  function renderEvidence(ev) {
    const items = Array.isArray(ev) ? ev : (ev ? [ev] : []);
    if (!items.length) return '';
    return `<details>
      <summary>Evidence (${items.length})</summary>
      <ul>${items.map(e => `<li><code>${escapeHtml(e)}</code></li>`).join('')}</ul>
    </details>`;
  }

  // ---------- 02 LLM Calls ----------

  appendSection('llmcalls', () => `
    ${sectionHead(2, 'LLM Calls', 'Every place in the product that calls an LLM. Click a row to see failure modes, constraints, and the system prompt for that call.')}
    ${callSites.length > 4 ? `
      <div class="search-bar">
        <div class="search-wrap">
          <input class="search" placeholder="Filter LLM calls…" data-filter="llmcall" />
        </div>
        <span class="search-count">${callSites.length} total</span>
      </div>` : ''}
    ${callSites.length === 0 ? '<div class="empty">No LLM calls found.</div>' : `
      <table class="data-table" id="llmcall-list">
        <thead><tr>
          <th></th>
          <th>Name</th>
          <th>File</th>
          <th>Provider</th>
          <th class="cell-count">Failures</th>
        </tr></thead>
        <tbody>${callSites.map((cs, i) => renderCallSiteRow(cs, i + 1)).join('')}</tbody>
      </table>`}
  `);

  function renderCallSiteRow(cs, n) {
    const filePath = cs.file_hint || cs.file || '';
    const fileLine = cs.line_hint || cs.line || '';
    const fileLoc = filePath ? filePath + (fileLine ? ':' + fileLine : '') : '';
    const title = titleFor(cs.use_case, cs.name, stripIdPrefix(cs.id)) || 'LLM call';
    const searchText = `${cs.id} ${cs.use_case || ''} ${cs.name || ''} ${cs.intent || ''} ${filePath}`.toLowerCase();
    const fms = fmsByCallSite.get(cs.id) || [];
    return `<tr id="cs-${escapeHtml(cs.id)}" data-modal-open="cs:${escapeHtml(cs.id)}" data-search="${escapeHtml(searchText)}">
      <td class="cell-num">${pad2(n)}</td>
      <td class="cell-title">${escapeHtml(title)}${invocationChip(cs.invocation)}${gradeModeChip(cs.default_grade_mode)}</td>
      <td class="cell-file" title="${escapeHtml(fileLoc)}">${escapeHtml(fileLoc || '—')}</td>
      <td class="cell-mono">${escapeHtml(cs.provider || '—')}${cs.model ? ` <span style="color:var(--muted-2)">·</span> ${escapeHtml(cs.model)}` : ''}</td>
      <td class="cell-count">${fms.length}</td>
    </tr>`;
  }

  function openCallSiteModal(cs) {
    if (!cs) return;
    const filePath = cs.file_hint || cs.file || '';
    const fileLine = cs.line_hint || cs.line || '';
    const fileLoc = filePath ? filePath + (fileLine ? ':' + fileLine : '') : '';
    const title = titleFor(cs.use_case, cs.name, stripIdPrefix(cs.id)) || 'LLM call';
    const fms = fmsByCallSite.get(cs.id) || [];
    const hasConstraints = Array.isArray(cs.constraints) && cs.constraints.length;
    const chips = [
      chip(cs.shape, 'kind'),
      invocationChip(cs.invocation),
      gradeModeChip(cs.default_grade_mode),
      cs.provider ? rawChip(cs.provider, 'muted') : '',
      cs.model ? rawChip(cs.model, 'muted') : '',
    ].filter(Boolean).join('');
    const body = `
      ${cs.intent ? `<div class="field cs-narrative">${escapeHtml(cs.intent)}</div>` : ''}
      <div class="cs-meta">
        ${fileLoc ? `<span><span class="cs-meta-label">file</span><code>${escapeHtml(fileLoc)}</code></span>` : ''}
        ${cs.model ? `<span><span class="cs-meta-label">model</span><code>${escapeHtml(cs.model)}</code></span>` : ''}
        ${hasConstraints ? `<span><span class="cs-meta-label">constraints</span>${cs.constraints.length}</span>` : ''}
        ${cs.dataset_path ? `<span><span class="cs-meta-label">dataset</span><code>${escapeHtml(cs.dataset_path)}</code></span>` : ''}
      </div>
      ${renderObservedBlock(cs.observed)}
      ${renderSourceSpans(cs.source_spans)}
      <div class="field">
        <div class="field-label">Failure modes (${fms.length})</div>
        ${fms.length ? renderFMList(fms) : '<div class="empty">No failure modes mapped to this call.</div>'}
      </div>
      ${hasConstraints || cs.system_prompt ? `
        <div class="field cs-references">
          <div class="field-label">Reference</div>
          ${hasConstraints ? `<details>
            <summary>Constraints (${cs.constraints.length})</summary>
            <table>
              <thead><tr><th>Kind</th><th>Description</th><th>Enforcement</th></tr></thead>
              <tbody>${cs.constraints.map(c => `
                <tr>
                  <td>${escapeHtml(humanize(c.kind))}</td>
                  <td>${escapeHtml(c.description || '')}</td>
                  <td>${chip(c.enforcement, 'kind')}</td>
                </tr>`).join('')}</tbody>
            </table>
          </details>` : ''}
          ${cs.system_prompt ? `<details>
            <summary>System prompt</summary>
            <pre>${escapeHtml(cs.system_prompt)}</pre>
          </details>` : ''}
        </div>` : ''}
      ${(() => {
        const qds = qdByCallSite.get(cs.id) || [];
        if (!qds.length) return '';
        return `<div class="field">
          <div class="field-label">Quality dimensions (1–5 score, tracked over time)</div>
          ${qds.map(qd => {
            const g = gradersById.get(qd.grader_id);
            return `<div class="qd-row">
              <span class="qd-name">${escapeHtml(humanize(qd.name || stripIdPrefix(qd.id)))}</span>
              <span class="qd-desc">${escapeHtml(qd.description || '')}</span>
              ${g ? `<span><a href="#" data-modal-open="g:${escapeHtml(g.id)}">Score grader →</a></span>` : ''}
            </div>`;
          }).join('')}
        </div>`;
      })()}
    `;
    openModal({ kicker: 'LLM call', title, chips, body });
  }

  // v0.2: observed production stats block. Only renders when at least one
  // field is populated (Path A — traces ingested).
  function renderObservedBlock(observed) {
    if (!observed) return '';
    const fmtPct = x => (x == null ? null : `${(x * 100).toFixed(2)}%`);
    const cells = [
      ['error rate',         fmtPct(observed.error_rate)],
      ['refusal rate',       fmtPct(observed.refusal_rate)],
      ['p50 / p95 latency',  (observed.p50_latency_ms != null && observed.p95_latency_ms != null)
                                ? `${observed.p50_latency_ms} ms / ${observed.p95_latency_ms} ms` : null],
      ['p95 tokens in / out',(observed.p95_tokens_in != null && observed.p95_tokens_out != null)
                                ? `${observed.p95_tokens_in} / ${observed.p95_tokens_out}` : null],
      ['cost (USD)',         observed.cost_estimate_usd != null ? `$${Number(observed.cost_estimate_usd).toFixed(4)}` : null],
      ['redaction',          (observed.redaction_state && observed.redaction_state !== 'none') ? observed.redaction_state : null],
      ['sample window',      (observed.first_seen && observed.last_seen)
                                ? `${String(observed.first_seen).slice(0, 10)} → ${String(observed.last_seen).slice(0, 10)}` : null],
    ].filter(([, v]) => v != null);
    if (!cells.length) return '';
    return `<div class="field"><div class="field-label">Observed production stats</div>
      <dl class="op-grid">${cells.map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd></div>`).join('')}</dl>
    </div>`;
  }

  // v0.2: representative source spans collapsed into a <details>. Truncate
  // trace/span ids so the row stays scannable.
  function renderSourceSpans(spans) {
    if (!Array.isArray(spans) || !spans.length) return '';
    return `<div class="field"><details>
      <summary><span class="field-label-inline">Source spans <span style="color:var(--muted-2);font-weight:400">· ${spans.length}</span></span></summary>
      <ul class="op-refs-list">${spans.map(s => `<li>
        trace=<code>${escapeHtml(String(s.trace_id || '').slice(0, 16))}…</code>
        span=<code>${escapeHtml(String(s.span_id || '').slice(0, 16))}…</code>
        ${s.service_name ? ` <span style="color:var(--muted-2)">(${escapeHtml(s.service_name)})</span>` : ''}
      </li>`).join('')}</ul>
    </details></div>`;
  }

  // ---------- 03 Graders (with invariants folded as "global" rows) ----------

  // Pre-compute filter values present in the data so the chip strip only
  // shows options that will actually return rows.
  const graderKinds = unique([
    ...graders.map(g => g.kind),
    ...(invariants.length ? ['global'] : []),
  ]);
  const graderConfs = unique([
    ...graders.map(g => g.confidence),
    ...invariants.map(i => i.confidence),
  ]).filter(c => ['high', 'medium', 'low'].includes(c));
  const graderScopes = unique(graders.map(g => {
    const fms = fmsByGrader.get(g.id) || [];
    const cs = fms.length ? callSitesById.get(fms[0].call_site_id) : null;
    return cs ? (titleFor(cs.use_case, cs.name, stripIdPrefix(cs.id)) || 'LLM call') : '';
  }));

  // Pack + compliance + Layer fields are present in the underlying data but
  // intentionally not surfaced in the viewer chrome. They survive into the
  // embedded JSON blob so the platform's import path can still consume them.

  function filterChips(key, values, labels) {
    return `<div class="filter-row">
      <span class="filter-label">${escapeHtml(key)}</span>
      <div class="filter-chips">
        <button class="filter-chip active" data-fkey="${escapeHtml(key)}" data-fval="">All</button>
        ${values.map((v, i) => `<button class="filter-chip" data-fkey="${escapeHtml(key)}" data-fval="${escapeHtml(v)}">${escapeHtml(labels ? labels[i] : humanize(v))}</button>`).join('')}
      </div>
    </div>`;
  }

  // LLM Call uses a dropdown rather than a chip strip — call-site lists run
  // long on real products, and a 30+ chip rail is unusable.
  function filterDropdown(key, values, labels) {
    return `<div class="filter-row">
      <span class="filter-label">${escapeHtml(key)}</span>
      <div class="filter-select-wrap">
        <select class="filter-select" data-fkey="${escapeHtml(key)}">
          <option value="">All (${values.length})</option>
          ${values.map((v, i) => `<option value="${escapeHtml(v)}">${escapeHtml(labels ? labels[i] : humanize(v))}</option>`).join('')}
        </select>
      </div>
    </div>`;
  }

  appendSection('graders', () => {
    const specificCount = graders.length;
    const globalCount = invariants.length;

    const filterPills = `
      <div class="grader-filters" id="grader-filter-panel">
        ${graderKinds.length >= 1 ? filterChips('Kind', graderKinds) : ''}
        ${graderConfs.length >= 1 ? filterChips('Confidence', graderConfs) : ''}
        ${graderScopes.length >= 1 ? filterDropdown('LLM Call', graderScopes) : ''}
      </div>`;

    const graderRows = graders.map((g, i) => renderGraderRow(g, i + 1)).join('');
    const invariantRows = invariants.map((inv, i) => renderInvariantAsGraderRow(inv, specificCount + i + 1)).join('');

    const tableHtml = (specificCount + globalCount) === 0
      ? '<div class="empty">No graders.</div>'
      : `<table class="data-table" id="grader-list">
          <thead><tr>
            <th></th>
            <th>Name</th>
            <th>Kind</th>
            <th>LLM Call</th>
            <th>Taxonomy</th>
            <th>Confidence</th>
          </tr></thead>
          <tbody>${graderRows}${invariantRows}</tbody>
        </table>`;

    const taxonomyLink = taxonomyFlat.length ? `
      <button id="btn-taxonomy-all" class="taxonomy-all-btn">
        Failure taxonomy
        <span class="taxonomy-all-btn-hint">${taxonomyFlat.length} nodes ↗</span>
      </button>` : '';

    return `
      ${sectionHead(3, 'Graders', 'One grader per failure mode. Global graders apply to every LLM call. Click a row to inspect the judge prompt, rubric, and applies-when gate.')}
      <div class="grader-toolbar">
        <div class="grader-toolbar-filters">${filterPills}</div>
        <div class="grader-toolbar-aside">
          ${taxonomyLink}
          <div class="search-wrap"><input class="search" id="grader-text-search" placeholder="Search graders…" /></div>
          <span class="filter-count" id="grader-count">${specificCount + globalCount} graders</span>
        </div>
      </div>
      ${tableHtml}
    `;
  });

  function renderGraderRow(g, n) {
    const title = titleFor(g.name, stripIdPrefix(g.id)) || 'Grader';
    const linkedFms = fmsByGrader.get(g.id) || [];
    const linkedCS = linkedFms.length ? callSitesById.get(linkedFms[0].call_site_id) : null;
    const linkedTax = linkedFms.length ? taxonomyById.get(linkedFms[0].taxonomy_node_id) : null;
    const conf = g.confidence || '';
    const csLabel = linkedCS ? (titleFor(linkedCS.use_case, linkedCS.name, stripIdPrefix(linkedCS.id)) || 'LLM call') : '';
    const csCell = linkedCS
      ? `<span data-modal-open="cs:${escapeHtml(linkedCS.id)}" class="scope-link">${escapeHtml(csLabel)}</span>`
      : '<span style="color:var(--muted-2)">—</span>';
    const taxCell = linkedTax
      ? `<span data-modal-open="tax:${escapeHtml(linkedTax.id)}" class="tax-link">${escapeHtml(titleFor(linkedTax.name, stripIdPrefix(linkedTax.id)) || 'Node')}</span>`
      : '<span style="color:var(--muted-2)">—</span>';
    const searchText = `${g.id} ${g.name || ''} ${g.kind || ''} ${g.rationale || ''}`.toLowerCase();
    const meta = g._meta || null;
    const indicators = [
      meta && meta.human_edited ? '<span class="grader-indicator" title="Human-edited — re-syntheses preserve">✎</span>' : '',
      meta && meta.locked_fields && meta.locked_fields.length ? `<span class="grader-indicator" title="Locked: ${escapeHtml(meta.locked_fields.join(', '))}">🔒</span>` : '',
    ].filter(Boolean).join('');
    return `<tr id="g-${escapeHtml(g.id)}" data-modal-open="g:${escapeHtml(g.id)}" data-search="${escapeHtml(searchText)}" data-fkind="${escapeHtml(g.kind || '')}" data-fconf="${escapeHtml(g.confidence || '')}" data-fscope="${escapeHtml(csLabel)}">
      <td class="cell-num">${pad2(n)}</td>
      <td class="cell-title"><span class="cell-title-with-dot">${conf ? dot('conf-' + conf) : ''}<span>${escapeHtml(title)}</span>${indicators}</span></td>
      <td class="cell-chips">${chip(g.kind, 'kind')}${g._validation_error ? rawChip('error', 'warn') : ''}</td>
      <td class="cell-mono">${csCell}</td>
      <td class="cell-mono">${taxCell}</td>
      <td class="cell-chips">${conf ? chip(conf, 'conf-' + conf) : '—'}</td>
    </tr>`;
  }

  function renderInvariantAsGraderRow(inv, n) {
    const title = titleFor(inv.name, stripIdPrefix(inv.id)) || 'Global grader';
    const anchor = inv.name || stripIdPrefix(inv.id) || `inv-${n}`;
    const conf = inv.confidence || '';
    const searchText = `${anchor} ${inv.description || ''} ${inv.applies_to || ''}`.toLowerCase();
    return `<tr id="inv-${escapeHtml(anchor)}" data-modal-open="inv:${escapeHtml(anchor)}" data-search="${escapeHtml(searchText)}" data-fkind="global" data-fconf="${escapeHtml(conf)}" data-fscope="">
      <td class="cell-num">${pad2(n)}</td>
      <td class="cell-title"><span class="cell-title-with-dot">${conf ? dot('conf-' + conf) : ''}<span>${escapeHtml(title)}</span></span></td>
      <td class="cell-chips">${rawChip('global', 'kind')}</td>
      <td class="cell-mono"><span class="scope-all-calls">All calls</span></td>
      <td class="cell-mono"><span style="color:var(--muted-2)">—</span></td>
      <td class="cell-chips">${conf ? chip(conf, 'conf-' + conf) : '—'}</td>
    </tr>`;
  }

  function openGraderModal(g) {
    if (!g) return;
    const title = titleFor(g.name, stripIdPrefix(g.id)) || 'Grader';
    const linkedFms = fmsByGrader.get(g.id) || [];
    const linkedCS = linkedFms.length ? callSitesById.get(linkedFms[0].call_site_id) : null;
    const linkedTax = linkedFms.length ? taxonomyById.get(linkedFms[0].taxonomy_node_id) : null;
    const conf = g.confidence || '';

    // Chip strip in the header: kind, confidence, and load/validation errors
    // when present. Pack / compliance / Layer are deliberately not surfaced
    // — this HTML is a gist of the run, not a curation UI.
    const chips = [
      chip(g.kind, 'kind'),
      (g.scope && g.scope !== 'single_call') ? scopeChip(g.scope) : '',
      conf ? chip(conf + ' confidence', 'conf-' + conf) : '',
      g._validation_error ? rawChip('validation error', 'warn') : '',
      g._load_error ? rawChip('load error', 'warn') : '',
    ].filter(Boolean).join('');

    function collapsibleField(label, content, sizeHint) {
      if (!content) return '';
      const hint = sizeHint != null ? ` <span style="color:var(--muted-2);font-weight:400">· ${sizeHint}</span>` : '';
      return `<div class="field"><details>
        <summary><span class="field-label-inline">${escapeHtml(label)}${hint}</span></summary>
        <pre>${escapeHtml(content)}</pre>
      </details></div>`;
    }
    const charHint = s => s ? `${Math.round(s.length / 100) / 10}k chars` : '';
    const body = `
      ${g.rationale ? `<div class="field"><div class="field-label">Rationale</div><div class="field-val">${escapeHtml(g.rationale)}</div></div>` : ''}
      ${g.applies_when ? `<div class="field"><div class="field-label">Applies when</div><div class="field-val">${escapeHtml(g.applies_when)}</div></div>` : ''}
      ${(linkedCS || linkedTax) ? `<div class="field"><div class="field-label">Links</div>
        <div class="backlinks" style="margin:0;padding:0;border:0">
          ${linkedCS ? `<span><span class="bl-label">LLM call</span><a href="#" data-modal-open="cs:${escapeHtml(linkedCS.id)}">${escapeHtml(titleFor(linkedCS.use_case, linkedCS.name, stripIdPrefix(linkedCS.id)) || 'LLM call')}</a></span>` : ''}
          ${linkedTax ? `<span><span class="bl-label">taxonomy</span><a href="#" data-modal-open="tax:${escapeHtml(linkedTax.id)}">${escapeHtml(titleFor(linkedTax.name, stripIdPrefix(linkedTax.id)) || 'Node')}</a></span>` : ''}
        </div></div>` : ''}
      ${renderOperationalBlock(g)}
      ${renderProvenanceBlock(g)}
      ${collapsibleField('Judge prompt', g.judge_prompt, charHint(g.judge_prompt))}
      ${collapsibleField('Rubric', g.rubric, charHint(g.rubric))}
      ${g.rubric_levels && typeof g.rubric_levels === 'object' ? `<div class="field">
        <div class="field-label">Score rubric${g.score_scale ? ` (${g.score_scale.min}–${g.score_scale.max})` : ''}</div>
        <table class="rubric-table"><tbody>${Object.keys(g.rubric_levels)
          .sort((a, b) => Number(b) - Number(a))
          .map(lvl => `<tr><td class="rubric-lvl">${escapeHtml(lvl)}</td><td>${escapeHtml(g.rubric_levels[lvl])}</td></tr>`)
          .join('')}</tbody></table>
      </div>` : ''}
      ${collapsibleField('Deterministic check', g.deterministic_check, charHint(g.deterministic_check))}
      ${collapsibleField('Execution spec', g.execution_spec, charHint(g.execution_spec))}
      ${renderAgentSpec(g.agent_spec)}
      ${g._validation_error ? `<div class="field"><div class="field-label" style="color:var(--bad)">Validation error</div><pre style="color:var(--bad)">${escapeHtml(g._validation_error)}</pre></div>` : ''}
      ${g._load_error ? `<div class="field"><div class="field-label" style="color:var(--bad)">Load error</div><pre style="color:var(--bad)">${escapeHtml(g._load_error)}</pre></div>` : ''}
    `;
    openModal({ kicker: 'Grader', title, chips, body });
  }

  // Operational fields (block_on_fail, dataset refs). v9 removed owner and the
  // cost/latency budgets. All optional — render only when any field is populated.
  function renderOperationalBlock(g) {
    const refs = Array.isArray(g.dataset_refs) ? g.dataset_refs : [];
    const cells = [
      ['block on fail',          g.block_on_fail == null ? null : String(g.block_on_fail)],
    ].filter(([, v]) => v !== null && v !== undefined);
    if (!cells.length && !refs.length) return '';
    const cellsHtml = cells.length ? `<dl class="op-grid">${cells.map(([k, v]) => `
      <div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd></div>`).join('')}</dl>` : '';
    const refsHtml = refs.length ? `<div class="op-refs">
      <div class="field-label-inline">dataset refs · ${refs.length}</div>
      <ul class="op-refs-list">${refs.slice(0, 5).map(d => {
        if (d.trace_id && d.span_id) return `<li>trace=<code>${escapeHtml(String(d.trace_id).slice(0, 16))}…</code> span=<code>${escapeHtml(String(d.span_id).slice(0, 16))}…</code>${d.label ? ` <span style="color:var(--muted-2)">— ${escapeHtml(d.label)}</span>` : ''}</li>`;
        if (d.file) return `<li>📂 <code>${escapeHtml(d.file)}</code>${d.label ? ` <span style="color:var(--muted-2)">— ${escapeHtml(d.label)}</span>` : ''}</li>`;
        if (d.jsonl_path) return `<li>📦 <code>${escapeHtml(d.jsonl_path)}</code></li>`;
        return '<li><span style="color:var(--muted-2)">(unknown ref shape)</span></li>';
      }).join('')}${refs.length > 5 ? `<li style="color:var(--muted-2)">+${refs.length - 5} more…</li>` : ''}</ul>
    </div>` : '';
    return `<div class="field"><div class="field-label">Operational</div>
      <div class="op-block">${cellsHtml}${refsHtml}</div>
    </div>`;
  }

  // _meta provenance — author, contract version, timestamp, digest, locks.
  function renderProvenanceBlock(g) {
    const m = g._meta;
    if (!m) return '';
    return `<div class="field"><div class="field-label">Provenance</div>
      <dl class="op-grid">
        <div><dt>author</dt><dd>${escapeHtml(m.author || '—')}</dd></div>
        <div><dt>contract</dt><dd>v${escapeHtml(String(m.author_contract_version ?? '?'))}</dd></div>
        <div><dt>synthesized</dt><dd>${escapeHtml(m.synthesized_at || '—')}</dd></div>
        <div><dt>digest</dt><dd><code>${escapeHtml((m.synth_inputs_digest || '').slice(0, 16))}…</code></dd></div>
      </dl>
      ${m.locked_fields && m.locked_fields.length ? `<div class="op-lock">🔒 locked: <code>${escapeHtml(m.locked_fields.join(', '))}</code> <span style="color:var(--muted-2)">(preserved on re-synthesis)</span></div>` : ''}
      ${m.human_edited ? '<div class="op-human-edit">✎ human-edited — re-synthesis skips this file unless --force</div>' : ''}
    </div>`;
  }

  function openInvariantModal(inv) {
    if (!inv) return;
    const title = titleFor(inv.name, stripIdPrefix(inv.id)) || 'Global grader';
    const conf = inv.confidence || '';
    const appliesTo = Array.isArray(inv.applies_to)
      ? inv.applies_to.map(humanize).join(', ')
      : (inv.applies_to ? humanize(inv.applies_to) : '');
    const evidence = Array.isArray(inv.evidence) ? inv.evidence : (inv.evidence ? [inv.evidence] : []);
    const chips = [
      rawChip('global', 'kind'),
      conf ? chip(conf + ' confidence', 'conf-' + conf) : '',
    ].filter(Boolean).join('');
    const body = `
      ${inv.description ? `<div class="field"><div class="field-label">Description</div><div class="field-val">${escapeHtml(inv.description)}</div></div>` : ''}
      <div class="field"><div class="field-label">Applies to</div><div class="field-val">${escapeHtml(appliesTo || 'All LLM calls')}</div></div>
      ${evidence.length ? `<div class="field"><div class="field-label">Evidence (${evidence.length})</div>
        <ul style="margin:0;padding-left:18px">
          ${evidence.map(e => `<li><code>${escapeHtml(e)}</code></li>`).join('')}
        </ul></div>` : ''}
    `;
    openModal({ kicker: 'Global grader', title, chips, body });
  }

  function renderAgentSpec(spec) {
    if (!spec || typeof spec !== 'object') return '';
    const sandbox = spec.sandbox && typeof spec.sandbox === 'object' ? spec.sandbox : {};
    const tools = Array.isArray(spec.allowed_tools) ? spec.allowed_tools : [];
    const budgets = spec.budgets && typeof spec.budgets === 'object' ? spec.budgets : null;
    const metaRow = [
      spec.harness ? `<span><span class="cs-meta-label">harness</span><code>${escapeHtml(spec.harness)}</code></span>` : '',
      sandbox.image ? `<span><span class="cs-meta-label">image</span><code>${escapeHtml(sandbox.image)}</code></span>` : '',
      sandbox.network ? `<span><span class="cs-meta-label">network</span><code>${escapeHtml(sandbox.network)}</code></span>` : '',
      tools.length ? `<span><span class="cs-meta-label">tools</span>${tools.map(x => rawChip(x, 'muted')).join('')}</span>` : '',
      budgets ? `<span><span class="cs-meta-label">budgets</span><code>${escapeHtml(JSON.stringify(budgets))}</code></span>` : '',
    ].filter(Boolean).join('');
    return `<div class="field">
      <div class="field-label">Agent grader (runs in a sandbox)</div>
      <div class="cs-meta">${metaRow}</div>
      ${collapsibleField('Task prompt', spec.task_prompt, charHint(spec.task_prompt))}
      ${collapsibleField('Verdict contract', spec.verdict_contract, charHint(spec.verdict_contract))}
    </div>`;
  }

  // ---------- Taxonomy (modal-only — not a sidebar section) ----------

  const taxonomyParent = new Map();
  taxonomy.forEach(t => buildParentMap(t, null));
  function buildParentMap(node, parentId) {
    taxonomyParent.set(node.id, parentId);
    (node.children || []).forEach(c => buildParentMap(c, node.id));
  }
  function taxonomyBreadcrumb(node) {
    const chain = [];
    let cur = node;
    while (cur) {
      chain.unshift(cur);
      const pid = taxonomyParent.get(cur.id);
      cur = pid ? taxonomyById.get(pid) : null;
    }
    return chain;
  }
  function collectDescendantFms(node) {
    const out = [...(fmsByTaxonomy.get(node.id) || [])];
    (taxonomyChildren.get(node.id) || []).forEach(c => out.push(...collectDescendantFms(c)));
    return out;
  }

  function openTaxonomyModal(node) {
    if (!node) return;
    const name = titleFor(node.name, stripIdPrefix(node.id)) || 'Node';
    const crumb = taxonomyBreadcrumb(node);
    const breadcrumb = crumb.length > 1
      ? crumb.slice(0, -1)
          .map(n => titleFor(n.name, stripIdPrefix(n.id)) || 'Node')
          .map(escapeHtml).join(' <span style="color:var(--muted-2)">›</span> ')
      : '';
    const kids = taxonomyChildren.get(node.id) || [];
    const directFms = fmsByTaxonomy.get(node.id) || [];
    const rollup = collectDescendantFms(node);
    const chips = [
      rawChip(`${rollup.length} ${rollup.length === 1 ? 'failure' : 'failures'} total`, 'muted'),
      kids.length ? rawChip(`${kids.length} ${kids.length === 1 ? 'child' : 'children'}`, 'muted') : '',
    ].filter(Boolean).join('');
    const body = `
      ${breadcrumb ? `<div class="field"><div class="field-label">Path</div><div class="field-val" style="font-family:var(--font-mono);font-size:11.5px">${breadcrumb} <span style="color:var(--muted-2)">›</span> ${escapeHtml(name)}</div></div>` : ''}
      ${node.description ? `<div class="field"><div class="field-label">Description</div><div class="field-val">${escapeHtml(node.description)}</div></div>` : ''}
      ${kids.length ? `<div class="field"><div class="field-label">Sub-categories (${kids.length})</div>
        <ul style="margin:0;padding-left:18px">
          ${kids.map(k => {
            const kfms = collectDescendantFms(k);
            const kname = titleFor(k.name, stripIdPrefix(k.id)) || 'Node';
            return `<li><a href="#" data-modal-open="tax:${escapeHtml(k.id)}">${escapeHtml(kname)}</a> <span style="color:var(--muted-2);font-family:var(--font-mono);font-size:11px">— ${kfms.length} ${kfms.length === 1 ? 'failure' : 'failures'}</span></li>`;
          }).join('')}
        </ul></div>` : ''}
      ${directFms.length ? `<div class="field"><div class="field-label">Failure modes (${directFms.length})</div>${renderFMList(directFms)}</div>` : ''}
      ${(!kids.length && !directFms.length) ? '<div class="empty">This node has no children and no direct failure modes.</div>' : ''}
    `;
    openModal({ kicker: 'Taxonomy node', title: name, chips, body });
  }

  // The full-tree taxonomy modal — opened by the "Failure taxonomy" button.
  function openAllTaxonomyModal() {
    if (!taxonomyFlat.length) return;
    function buildRows(nodes, depth) {
      return nodes.map(node => {
        const name = titleFor(node.name, stripIdPrefix(node.id)) || 'Node';
        const kids = taxonomyChildren.get(node.id) || [];
        const rollup = collectDescendantFms(node);
        const indent = depth * 20;
        const isTop = depth === 0;
        return `<div class="tax-tree-row" data-modal-open="tax:${escapeHtml(node.id)}" style="padding-left:${12 + indent}px">
          <span class="tax-tree-name${isTop ? ' is-top' : ''}">
            ${depth > 0 ? '<span class="tax-tree-arrow">↳</span>' : ''}
            <span>${escapeHtml(name)}</span>
            ${node.description ? `<span class="tax-tree-desc">${escapeHtml(node.description)}</span>` : ''}
          </span>
          <span class="tax-tree-count">
            ${rollup.length ? `${rollup.length} failure${rollup.length === 1 ? '' : 's'}` : ''}
            ${kids.length ? ` · ${kids.length} child${kids.length === 1 ? '' : 'ren'}` : ''}
          </span>
        </div>
        ${buildRows(kids, depth + 1)}`;
      }).join('');
    }
    const topNodes = taxonomyChildren.get('__root__') || [];
    const totalFms = failureModes.length;
    const body = `
      <div class="tax-tree-summary">
        ${taxonomyFlat.length} nodes covering ${totalFms} failure mode${totalFms === 1 ? '' : 's'}. Click any node to inspect it.
      </div>
      <div class="tax-tree">${buildRows(topNodes, 0)}</div>`;
    openModal({
      kicker: 'Reference',
      title: 'Failure Taxonomy',
      chips: rawChip(`${taxonomyFlat.length} nodes`, 'muted'),
      body,
    });
  }

  // ---------- Failure-mode list (compact, used inline inside modals) ----------

  function renderFMList(fms, opts = {}) {
    return `<div class="fm-list">${fms.map(fm => renderFMRow(fm, opts)).join('')}</div>`;
  }
  function renderFMRow(fm, opts = {}) {
    const { showTitle = true, showGraderLink = true } = opts;
    const g = gradersById.get(fm.grader_id);
    const title = titleFor(fm.name, stripIdPrefix(fm.id)) || 'Failure mode';
    const sev = fm.severity || '';
    const primary = showTitle
      ? `<span class="fm-title">${escapeHtml(title)}</span>`
      : `<span class="fm-title fm-title-as-desc">${escapeHtml(fm.description || title)}</span>`;
    const secondary = (showTitle && fm.description)
      ? `<span class="fm-desc">${escapeHtml(fm.description)}</span>`
      : '';
    const deferred = fm.grader_deferred === true;
    const deferredBadge = deferred
      ? `<span class="fm-deferred" title="Grader not yet synthesized. Run /evals:synthesize-graders --complete &lt;call_site_id&gt; to flesh out.">deferred</span>`
      : '';
    return `<div class="fm-row${deferred ? ' fm-row-deferred' : ''}">
      <span class="fm-dot dot ${sev ? 'sev-' + sev : ''}"></span>
      ${primary}
      <span class="fm-meta">
        ${sev ? humanize(sev) : ''}
        ${g && g.kind ? ` · ${escapeHtml(humanize(g.kind))}` : ''}
        ${deferredBadge}
      </span>
      ${showGraderLink && g ? `<span><a href="#" data-modal-open="g:${escapeHtml(g.id)}">Grader →</a></span>` : '<span></span>'}
      ${secondary}
    </div>`;
  }

  // ---------- Click handlers (cross-links + modal triggers + stat-nav) ----------

  function openByKey(key) {
    if (!key) return false;
    const sep = key.indexOf(':');
    if (sep === -1) return false;
    const kind = key.slice(0, sep);
    const id = key.slice(sep + 1);
    if (kind === 'g')   { openGraderModal(gradersById.get(id)); return true; }
    if (kind === 'cs')  { openCallSiteModal(callSitesById.get(id)); return true; }
    if (kind === 'tax') { openTaxonomyModal(taxonomyById.get(id)); return true; }
    if (kind === 'inv') {
      const inv = invariants.find(iv => (iv.name || stripIdPrefix(iv.id) || '') === id);
      openInvariantModal(inv);
      return true;
    }
    return false;
  }

  document.addEventListener('click', e => {
    // Clickable stat cards on the overview navigate to a sidebar destination.
    const statCard = e.target.closest('[data-nav]');
    if (statCard && !e.target.closest('a, [data-modal-open]')) {
      show(statCard.dataset.nav);
      return;
    }

    // Cross-link jump (sidebar navigation + scroll-to-anchor)
    const a = e.target.closest('a[data-jump]');
    if (a) {
      e.preventDefault();
      const [viewId, anchorId] = a.dataset.jump.split('|');
      closeModal();
      jumpTo(viewId, anchorId);
      return;
    }

    // Modal trigger (rows, cross-link cells inside rows, links inside modal)
    const trigger = e.target.closest('[data-modal-open]');
    if (trigger) {
      // Prevent the row click from also firing when a child link inside the
      // row carries its own data-modal-open.
      e.preventDefault();
      openByKey(trigger.dataset.modalOpen);
      return;
    }

    // Plain link inside the page (e.g. external CTA) — let it through.
  });

  // Wire the "Failure taxonomy" button after the Graders section is in the DOM.
  requestAnimationFrame(() => {
    const btn = document.getElementById('btn-taxonomy-all');
    if (btn) btn.addEventListener('click', openAllTaxonomyModal);
  });

  // ---------- Filters ----------

  // Plain text filter for the LLM Calls list.
  document.querySelectorAll('input[data-filter]').forEach(inp => {
    inp.addEventListener('input', () => {
      const q = inp.value.toLowerCase().trim();
      const container = inp.closest('section').querySelector('[id$="-list"]');
      if (!container) return;
      container.querySelectorAll('[data-search]').forEach(el => {
        el.style.display = !q || el.dataset.search.includes(q) ? '' : 'none';
      });
    });
  });

  // Grader multi-dimensional filter (kind + confidence + LLM call) + text search.
  requestAnimationFrame(() => {
    const state = { search: '', kind: '', conf: '', scope: '' };

    function apply() {
      const list = document.getElementById('grader-list');
      if (!list) return;
      const rows = list.querySelectorAll('tr[data-search]');
      let visible = 0;
      const total = rows.length;
      rows.forEach(row => {
        const ok =
          (!state.search || row.dataset.search.includes(state.search)) &&
          (!state.kind   || row.dataset.fkind  === state.kind) &&
          (!state.conf   || row.dataset.fconf  === state.conf) &&
          (!state.scope  || row.dataset.fscope === state.scope);
        row.style.display = ok ? '' : 'none';
        if (ok) visible++;
      });
      const el = document.getElementById('grader-count');
      if (el) el.textContent = visible === total ? `${total} graders` : `${visible} of ${total}`;
    }

    const textInput = document.getElementById('grader-text-search');
    if (textInput) {
      textInput.addEventListener('input', () => {
        state.search = textInput.value.toLowerCase().trim();
        apply();
      });
    }

    const panel = document.getElementById('grader-filter-panel');
    if (panel) {
      // Chip-strip filters (Kind, Confidence).
      panel.addEventListener('click', e => {
        const btn = e.target.closest('button[data-fkey]');
        if (!btn) return;
        const key = btn.dataset.fkey;
        const val = btn.dataset.fval;
        panel.querySelectorAll(`button[data-fkey="${key}"]`).forEach(b => b.classList.toggle('active', b === btn));
        if (key === 'Kind')       state.kind = val;
        if (key === 'Confidence') state.conf = val;
        apply();
      });
      // LLM Call dropdown — long call-site lists, so a select beats a chip rail.
      panel.querySelectorAll('select[data-fkey]').forEach(sel => {
        sel.addEventListener('change', () => {
          if (sel.dataset.fkey === 'LLM Call') state.scope = sel.value;
          apply();
        });
      });
    }
  });

  // ---------- Initial view ----------

  const initial = (location.hash || '#overview').slice(1);
  show(views.find(v => v.id === initial) ? initial : 'overview');
})();
