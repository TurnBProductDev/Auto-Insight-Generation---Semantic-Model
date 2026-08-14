/* Client onboarding wizard.
 *
 * Vanilla JS on purpose - no build step, no CDN, one file, matching how every
 * other rendered artifact in this repo works. The form is generated from
 * /api/schema so the UI can never carry a second, drifting copy of the 200-key
 * catalogue: adding a key to src/config_schema.py makes it appear here.
 *
 * Two hundred settings is not a form anyone can fill in. Each one carries a
 * tier, and this page shows only the "essential" ones until asked for more, so
 * setting up a client is about twenty decisions rather than two hundred.
 */

const S = {
  schema: null,
  clients: [],
  name: '',
  config: {},
  businessRules: '',
  summaryBusinessRules: '',
  probe: null,
  probeJob: null,
  validation: null,
  deploy: loadDeploySpec(),
  ruleTab: 'business',
  detail: 'essential',   // essential | standard | all
  filter: '',
  dirty: false,
  step: 'client',
};

/* ------------------------------------------------------------------ utils */

const el = (tag, props = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function toast(message, kind = '') {
  const node = el('div', { class: `toast ${kind}` }, message);
  $('#toast-host').append(node);
  setTimeout(() => node.remove(), kind === 'error' ? 8000 : 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!response.ok && response.status !== 409) {
    throw new Error(data.detail || `${response.status} ${response.statusText}`);
  }
  return data;
}

const fmt = (value) => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(none)';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};

const num = (value, digits = 1) =>
  value === null || value === undefined ? '-' : Number(value).toFixed(digits);

function loadDeploySpec() {
  try { return JSON.parse(localStorage.getItem('insightgen.deploy') || '{}'); }
  catch { return {}; }
}

/* --------------------------------------------------------------- the steps */

const STEPS = [
  { id: 'client', label: 'Choose a client', render: renderClientStep },
  { id: 'connection', label: 'Connect', group: 'connection', render: renderConnectionStep },
  { id: 'probe', label: 'Check the data', render: renderProbeStep },
  { id: 'scope', label: 'Shops to compare', group: 'scope' },
  { id: 'roles', label: 'Product levels', group: 'roles' },
  { id: 'features', label: 'What to include', group: 'features' },
  { id: 'publishing', label: 'Where it goes', group: 'publishing', render: renderPublishingStep },
  { id: 'summary_tuning', label: 'Summary settings', group: 'summary_tuning' },
  { id: 'rag_calendar', label: 'Targets & holidays', group: 'rag_calendar' },
  { id: 'insight_tuning', label: 'Deep-dive settings', group: 'insight_tuning' },
  { id: 'rulebooks', label: 'Your house rules', render: renderRulebooksStep },
  { id: 'review', label: 'Check & save', render: renderReviewStep },
  { id: 'deploy', label: 'Go live', render: renderDeployStep },
];

const TIER_ORDER = { essential: 0, standard: 1, expert: 2 };
const DETAIL_LEVELS = {
  essential: { label: 'Only what I must decide', max: 0 },
  standard: { label: 'Add the ones worth reviewing', max: 1 },
  all: { label: 'Show everything', max: 2 },
};

function renderNav() {
  const nav = $('#steps');
  nav.innerHTML = '';
  nav.append(el('div', { class: 'rail-label' }, 'Setting up a client'));
  STEPS.forEach((step, index) => {
    const done = stepIsDone(step);
    nav.append(el('button', {
      class: [step.id === S.step ? 'active' : '', done ? 'done' : ''].join(' '),
      onclick: () => go(step.id),
    }, el('span', { class: 'num' }, done ? '✓' : String(index + 1)), step.label));
  });
}

function stepIsDone(step) {
  if (step.id === 'client') return Boolean(S.name);
  if (step.id === 'connection') {
    return ['tenant_id', 'workspace_id', 'dataset_id'].every((k) => String(S.config[k] || '').length > 30);
  }
  if (step.id === 'probe') return Boolean(S.probe && S.probe.status !== 'failed');
  if (step.id === 'rulebooks') return Boolean(S.businessRules.trim() && S.summaryBusinessRules.trim());
  if (step.id === 'review') return Boolean(S.validation && S.validation.ok);
  return false;
}

function go(id) {
  S.step = id;
  S.filter = '';
  renderNav();
  render();
  window.scrollTo({ top: 0 });
}

/* -------------------------------------------------------- generic form UI */

function fieldNode(entry) {
  const value = S.config[entry.key];
  const wrap = el('div', { class: `field ${entry.type === 'bool' ? 'bool' : ''}`, 'data-key': entry.key });

  const badges = el('span', { class: 'badge-row' });
  if (entry.tier === 'essential') badges.append(el('span', { class: 'badge need' }, 'needs an answer'));
  if (entry.warn) badges.append(el('span', { class: 'badge trap', title: entry.warn }, 'easy to get wrong'));
  if (entry.dead) badges.append(el('span', { class: 'badge dead' }, 'no longer used'));
  if (entry.perClient) badges.append(el('span', { class: 'badge pc', title: 'Should differ for each client' }, 'per client'));
  if (probeRecommendation(entry.key)) badges.append(el('span', { class: 'badge probe' }, 'the data check has an answer'));

  const label = el('label', { for: `f-${entry.key}` }, entry.label, badges);
  const help = el('div', { class: 'help' }, entry.help);

  const detail = el('div', { class: 'detail hidden' },
    entry.detail || 'No further notes.',
    el('div', { class: 'tiny muted' }, `Setting name: ${entry.key}. `
      + `If left alone: ${fmt(entry.default)}`));
  const footnote = el('div', { class: 'footnote' },
    el('button', {
      class: 'link tiny',
      onclick: (event) => { event.preventDefault(); detail.classList.toggle('hidden'); },
    }, 'More detail'));

  const onInput = (raw) => {
    S.config[entry.key] = raw;
    S.dirty = true;
    S.validation = null;
    markDirty();
  };

  let input;
  if (entry.type === 'bool') {
    input = el('input', { type: 'checkbox', id: `f-${entry.key}` });
    input.checked = Boolean(value);
    input.addEventListener('change', () => onInput(input.checked));
    wrap.append(input, el('div', {}, label, help, footnote, detail));
    return wrap;
  }

  if (entry.type === 'enum') {
    const names = entry.choiceLabels || {};
    input = el('select', { id: `f-${entry.key}` },
      ...entry.choices.map((choice) => el('option', { value: choice }, names[choice] || choice)));
    input.value = value ?? entry.default;
    input.addEventListener('change', () => onInput(input.value));
  } else if (entry.type === 'list' && entry.itemChoices) {
    const names = entry.itemLabels || {};
    const selected = new Set((value || []).map((v) => String(v)));
    input = el('div', { class: 'chooser', id: `f-${entry.key}` });
    for (const choice of entry.itemChoices) {
      const box = el('input', { type: 'checkbox', value: choice });
      box.checked = selected.has(choice);
      box.addEventListener('change', () => {
        box.checked ? selected.add(choice) : selected.delete(choice);
        onInput(entry.itemChoices.filter((c) => selected.has(c)));
      });
      input.append(el('label', {}, box, names[choice] || choice));
    }
  } else if (entry.type === 'object' || entry.type === 'list') {
    input = el('textarea', { id: `f-${entry.key}`, spellcheck: 'false' });
    input.value = value === undefined || value === null
      ? JSON.stringify(entry.default) : JSON.stringify(value, null, entry.type === 'object' ? 2 : 0);
    input.addEventListener('change', () => {
      try {
        onInput(JSON.parse(input.value || (entry.type === 'object' ? '{}' : '[]')));
        wrap.classList.remove('invalid');
      } catch {
        wrap.classList.add('invalid');
        toast(`${entry.label}: that is not written correctly. A list looks like ["A", "B"]; a `
          + 'set of pairs looks like {"their name": "our name"}.', 'error');
      }
    });
  } else if (entry.type === 'int' || entry.type === 'float') {
    input = el('input', { type: 'number', id: `f-${entry.key}`, step: entry.type === 'int' ? '1' : 'any' });
    input.value = value ?? entry.default ?? '';
    input.addEventListener('change', () => onInput(input.value === '' ? null : Number(input.value)));
  } else {
    input = el('input', { type: 'text', id: `f-${entry.key}`, autocomplete: 'off' });
    input.value = value ?? entry.default ?? '';
    input.addEventListener('change', () => onInput(input.value));
  }

  wrap.append(label, input, help);
  const recommendation = probeRecommendation(entry.key);
  if (recommendation && JSON.stringify(recommendation.value) !== JSON.stringify(value)) {
    wrap.append(el('div', { class: 'suggestion' },
      el('div', {}, 'The data check suggests ', el('strong', {}, fmt(recommendation.value))),
      el('button', {
        class: 'btn secondary tiny',
        onclick: (event) => { event.preventDefault(); applyRecommendation(recommendation); },
      }, 'Use this')));
  }
  wrap.append(footnote, detail);
  return wrap;
}

function probeRecommendation(key) {
  return (S.probe?.recommendations || []).find((r) => r.key === key) || null;
}

function applyRecommendation(recommendation) {
  S.config[recommendation.key] = recommendation.value;
  S.dirty = true;
  S.validation = null;
  toast('Set from the data check.', 'ok');
  render();
}

function visibleKeys(groupId) {
  const cap = DETAIL_LEVELS[S.detail].max;
  const needle = S.filter.trim().toLowerCase();
  return S.schema.keys
    .filter((k) => k.group === groupId)
    .filter((k) => (needle
      ? (k.label.toLowerCase().includes(needle) || k.key.includes(needle)
        || k.help.toLowerCase().includes(needle))
      : TIER_ORDER[k.tier] <= cap));
}

function renderGroup(groupId) {
  const group = S.schema.groups.find((g) => g.id === groupId);
  const all = S.schema.keys.filter((k) => k.group === groupId);
  const counts = {
    essential: all.filter((k) => k.tier === 'essential').length,
    standard: all.filter((k) => k.tier === 'standard').length,
    expert: all.filter((k) => k.tier === 'expert').length,
  };
  const index = STEPS.findIndex((s) => s.id === groupId);
  const main = $('#main');
  main.append(el('h2', {}, `Step ${index + 1} · ${group.title}`));
  main.append(el('p', { class: 'blurb' }, group.blurb));

  if (group.probeDriven && !S.probe) {
    main.append(el('div', { class: 'notice warning' },
      el('strong', {}, 'Run the data check first. '),
      'The answers here depend on what your dashboard actually contains, and a wrong answer '
      + 'quietly produces a worse report rather than an error. ',
      el('button', { class: 'link', onclick: () => go('probe') }, 'Go to the data check')));
  }

  if (!counts.essential && S.detail === 'essential' && !S.filter) {
    main.append(el('div', { class: 'notice ok' },
      'Nothing on this step needs a decision - every setting here already has a sensible '
      + 'default. Move on, or use the control below if you want to look.'));
  }

  main.append(el('div', { class: 'toolbar' },
    el('label', { class: 'inline' }, 'Show: ',
      (() => {
        const select = el('select', {},
          ...Object.entries(DETAIL_LEVELS).map(([id, spec]) => {
            const shown = id === 'essential' ? counts.essential
              : id === 'standard' ? counts.essential + counts.standard : all.length;
            return el('option', { value: id }, `${spec.label} (${shown})`);
          }));
        select.value = S.detail;
        select.addEventListener('change', () => {
          S.detail = select.value;
          localStorage.setItem('insightgen.detail', S.detail);
          renderGroupBody(groupId);
        });
        return select;
      })()),
    el('input', {
      type: 'search', placeholder: 'Search all settings on this step…', value: S.filter,
      oninput: (event) => { S.filter = event.target.value; renderGroupBody(groupId); },
    }),
    el('span', { class: 'sep' }),
    el('span', { class: 'muted small' }, `${all.length} settings on this step`)));

  main.append(el('div', { class: 'panel', id: 'group-body' }));
  renderGroupBody(groupId);
  main.append(navButtons(groupId));
}

function renderGroupBody(groupId) {
  const body = $('#group-body');
  if (!body) return;
  body.innerHTML = '';
  const keys = visibleKeys(groupId);
  if (!keys.length) {
    body.append(el('p', { class: 'muted' }, S.filter
      ? 'Nothing on this step matches that search.'
      : 'Nothing to show at this level of detail.'));
    return;
  }
  keys.sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier]);
  let lastTier = null;
  for (const entry of keys) {
    if (entry.tier !== lastTier && !S.filter) {
      lastTier = entry.tier;
      const heading = {
        essential: ['You need to answer these', ''],
        standard: ['Worth a look', 'The defaults here are usually right.'],
        expert: ['Leave these alone unless you know why',
          'Changing them can quietly make the reports wrong.'],
      }[entry.tier];
      body.append(el('div', { class: `tier-head ${entry.tier}` },
        el('h4', {}, heading[0]),
        heading[1] ? el('span', {}, heading[1]) : null));
    }
    body.append(fieldNode(entry));
  }
}

function navButtons(currentId) {
  const index = STEPS.findIndex((s) => s.id === currentId);
  return el('div', { class: 'actions' },
    index > 0 ? el('button', { class: 'btn secondary', onclick: () => go(STEPS[index - 1].id) },
      '← Back to ' + STEPS[index - 1].label) : null,
    el('span', { class: 'grow' }),
    index < STEPS.length - 1 ? el('button', { class: 'btn', onclick: () => go(STEPS[index + 1].id) },
      'Next: ' + STEPS[index + 1].label + ' →') : null);
}

/* ----------------------------------------------------------- step: client */

function renderClientStep() {
  const main = $('#main');
  main.append(template('tpl-client'));

  const list = $('#client-list');
  if (!S.clients.length) {
    list.append(el('p', { class: 'muted' }, 'No clients set up yet. Start one below.'));
  } else {
    const table = el('table', { class: 'grid' },
      el('thead', {}, el('tr', {},
        el('th', {}, 'Client'), el('th', {}, 'Reports saved to'),
        el('th', {}, 'Storage folder'), el('th', {}, 'Report style'),
        el('th', {}, 'House rules'), el('th', {}, ''))));
    const body = el('tbody');
    for (const client of S.clients) {
      const config = client.config || {};
      body.append(el('tr', {},
        el('td', {}, el('strong', {}, client.name)),
        el('td', { class: 'small' }, config.output_folder || 'outputs'),
        el('td', { class: 'small' },
          config.azure_blob_prefix === '' ? 'the top level'
            : (config.azure_blob_prefix ?? 'not uploading')),
        el('td', {},
          el('span', { class: `pill ${config.summary_r4_enabled ? 'ok' : 'muted'}` },
            config.summary_r4_enabled ? 'balanced report' : 'single area'), ' ',
          el('span', { class: `pill ${config.summary_r6_enabled ? 'ok' : 'muted'}` },
            config.summary_r6_enabled ? 'dashboard' : 'no dashboard')),
        el('td', { class: 'small' },
          `${Math.round((client.businessRulesBytes || 0) / 1024)} KB + `
          + `${Math.round((client.summaryRulesBytes || 0) / 1024)} KB`),
        el('td', {}, el('button', { class: 'btn secondary', onclick: () => openClient(client.name) }, 'Open'))));
    }
    table.append(body);
    list.append(table);
  }

  const cloneSelect = $('#clone-from');
  for (const client of S.clients) cloneSelect.append(el('option', { value: client.name }, client.name));

  $('#btn-create').addEventListener('click', createClient);
}

async function openClient(name) {
  try {
    const data = await api(`/api/clients/${encodeURIComponent(name)}`);
    S.name = name;
    S.config = data.config;
    S.businessRules = data.businessRules || '';
    S.summaryBusinessRules = data.summaryBusinessRules || '';
    S.probe = data.probe || null;
    S.validation = null;
    S.dirty = false;
    toast(`Opened ${name}.`, 'ok');
    go('connection');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function createClient() {
  const name = $('#new-client-name').value.trim();
  const source = $('#clone-from').value;
  if (!name) { toast('Give the client a short name first.', 'error'); return; }
  try {
    if (source) {
      await api(`/api/clients/${encodeURIComponent(source)}/clone`, {
        method: 'POST', body: { target: name },
      });
      await refreshClients();
      await openClient(name);
      toast(`Copied ${source} into ${name}. The settings that must differ have been cleared.`, 'ok');
      return;
    }
    const defaults = await api(`/api/clients/${encodeURIComponent(name)}/defaults`);
    S.name = name;
    S.config = defaults.config;
    S.businessRules = defaults.business_rules || '';
    S.summaryBusinessRules = defaults.summary_business_rules || '';
    S.probe = null;
    S.validation = null;
    S.dirty = true;
    toast(`Started ${name}. Nothing is saved until you press Save on the 'Check & save' step.`, 'ok');
    go('connection');
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------- step: connection */

function renderConnectionStep() {
  renderGroup('connection');
  const resolver = el('div', { class: 'panel highlight' },
    el('h3', {}, 'Only have a report link?'),
    el('p', { class: 'small muted' },
      'A report and the data behind it have different IDs, and this form needs the data one. '
      + 'Paste the report ID here and it will be looked up for you.'),
    el('div', { class: 'row' },
      el('div', { class: 'field' },
        el('label', { for: 'resolve-report' }, 'Report ID'),
        el('input', { type: 'text', id: 'resolve-report', placeholder: 'Paste it here', autocomplete: 'off' })),
      el('div', { class: 'field' },
        el('label', {}, 'Result'),
        el('div', { id: 'resolve-result', class: 'muted small' }, 'Not looked up yet.'))),
    el('div', { class: 'actions' },
      el('button', { class: 'btn secondary', id: 'btn-resolve' }, 'Find the dataset')));
  const body = $('#group-body');
  body.parentNode.insertBefore(resolver, body);
  $('#btn-resolve').addEventListener('click', resolveDataset);
}

async function resolveDataset() {
  const report = $('#resolve-report').value.trim();
  const workspace = String(S.config.workspace_id || '').trim();
  const tenant = String(S.config.tenant_id || '').trim();
  const target = $('#resolve-result');
  // The lookup signs in as you, so it needs the organisation as well as the
  // workspace. Sending only the workspace made it fall back to a deployment
  // environment variable and report "tenant is not configured".
  if (!tenant) { toast('Fill in the Organisation ID first - the lookup signs in with it.', 'error'); return; }
  if (!workspace) { toast('Fill in the Workspace ID first - the lookup needs it.', 'error'); return; }
  if (!report) { toast('Paste a report ID first.', 'error'); return; }
  target.textContent = 'Looking it up…';
  try {
    const data = await api('/api/resolve-dataset', {
      method: 'POST', body: { tenantId: tenant, workspaceId: workspace, reportId: report },
    });
    S.config.dataset_id = data.datasetId;
    S.dirty = true;
    S.validation = null;
    target.innerHTML = '';
    target.append(el('span', { class: 'pill ok' }, 'found'), ' ',
      el('span', { class: 'mono small' }, data.datasetId), ' — ', data.reportName || '');
    render();
    toast('Dataset ID filled in for you.', 'ok');
  } catch (error) {
    target.textContent = error.message;
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------- step: publishing */

/* The step people get wrong, and the reason is structural: there is not one
   cloud destination but three, serving different audiences. Sixteen storage
   fields in one column cannot convey that; the resolved paths can. */
function renderPublishingStep() {
  renderGroup('publishing');
  const panel = el('div', { class: 'panel highlight', id: 'storage-plan' },
    el('h3', {}, 'Where your files will actually end up'),
    el('p', { class: 'small muted' },
      'Worked out from the settings below, using the same rules the run itself uses. '
      + 'Re-check it after any change here.'),
    el('div', { class: 'actions' },
      el('button', { class: 'btn secondary', id: 'btn-storage-plan' }, 'Work it out')),
    el('div', { id: 'storage-plan-body' }));
  const body = $('#group-body');
  body.parentNode.insertBefore(panel, body);
  $('#btn-storage-plan').addEventListener('click', loadStoragePlan);
  loadStoragePlan();
}

async function loadStoragePlan() {
  const host = $('#storage-plan-body');
  if (!host) return;
  host.innerHTML = '<span class="spinner dark"></span> working it out…';
  let plan;
  try {
    plan = await api('/api/storage-plan', {
      method: 'POST', body: { name: S.name, config: S.config },
    });
  } catch (error) {
    host.innerHTML = '';
    host.append(el('div', { class: 'notice error' }, error.message));
    return;
  }
  host.innerHTML = '';
  host.append(el('p', { class: 'small' },
    'Storage account: ', el('strong', {}, plan.account)));

  for (const dest of plan.destinations) {
    const card = el('div', { class: `dest ${dest.enabled ? '' : 'off'}` },
      el('div', { class: 'dest-head' },
        el('span', { class: `pill ${dest.enabled ? 'ok' : 'muted'}` },
          dest.enabled ? 'switched on' : 'switched off'),
        el('strong', {}, dest.title),
        el('span', { class: 'muted small' }, `read by ${dest.audience}`)),
      el('p', { class: 'small muted' }, dest.purpose));

    if (dest.enabled) {
      const rows = el('table', { class: 'grid' },
        el('thead', {}, el('tr', {}, el('th', {}, 'What'), el('th', {}, 'Ends up at'))),
        el('tbody', {}, ...dest.paths.map((p) => el('tr', {},
          el('td', {}, p.what),
          el('td', { class: 'mono small' },
            el('span', { class: 'container-name' }, dest.container + '/'), p.path)))));
      card.append(el('div', { class: 'scroll-x' }, rows));
    } else {
      card.append(el('p', { class: 'small muted' },
        `Nothing is written here. Container would be "${dest.container}".`));
    }

    if (dest.note) card.append(el('p', { class: 'small muted note' }, dest.note));
    if (dest.warning) card.append(el('div', { class: 'notice warning' }, dest.warning));
    card.append(el('div', { class: 'small muted' }, 'Set by: ',
      ...dest.settings.map((key, i) => {
        const entry = S.schema.keys.find((k) => k.key === key);
        return el('span', {}, i ? ', ' : '', el('button', {
          class: 'link',
          onclick: () => { S.detail = 'all'; renderGroupBody('publishing'); highlight(key); },
        }, entry ? entry.label : key));
      })));
    host.append(card);
  }
}

/* ------------------------------------------------------------ step: probe */

function renderProbeStep() {
  const main = $('#main');
  main.append(template('tpl-probe'));
  $('#btn-probe').addEventListener('click', startProbe);
  $('#btn-probe-cancel').addEventListener('click', cancelProbe);
  if (S.probe) {
    $('#probe-log').textContent = (S.probe.logs || []).join('\n');
    $('#probe-state').textContent = statusLine(S.probe);
    renderProbeResults();
  }
  main.append(navButtons('probe'));
}

function statusLine(probe) {
  const words = {
    ok: 'All clear',
    degraded: 'Usable, with things to be aware of',
    failed: 'Problems that must be fixed',
  };
  return `${words[probe.status] || probe.status} · took ${probe.duration_seconds}s`;
}

async function startProbe() {
  const missing = ['tenant_id', 'workspace_id', 'dataset_id']
    .filter((k) => !String(S.config[k] || '').trim())
    .map((k) => S.schema.keys.find((e) => e.key === k).label);
  if (missing.length) {
    toast(`Fill in ${missing.join(', ')} on the Connect step first.`, 'error');
    return;
  }
  $('#probe-log').textContent = '';
  $('#btn-probe').disabled = true;
  $('#btn-probe-cancel').disabled = false;
  $('#probe-state').innerHTML = '<span class="spinner dark"></span> checking…';
  try {
    const { jobId } = await api('/api/probe', {
      method: 'POST',
      body: { name: S.name, config: S.config, deepScan: $('#probe-deep')?.checked },
    });
    S.probeJob = jobId;
    pollJob(jobId, {
      log: $('#probe-log'),
      onDone: (job) => {
        $('#btn-probe').disabled = false;
        $('#btn-probe-cancel').disabled = true;
        if (job.status === 'failed') {
          $('#probe-state').textContent = `Could not finish: ${job.error}`;
          toast(job.error, 'error');
          return;
        }
        S.probe = job.result;
        S.validation = null;
        $('#probe-state').textContent = statusLine(S.probe);
        renderProbeResults();
        updateChips();
        renderNav();
        const n = S.probe.recommendations.length;
        toast(S.probe.status === 'failed'
          ? 'The check found problems that must be fixed before this client can go live.'
          : `Check finished. ${n} setting${n === 1 ? '' : 's'} can be filled in from it.`,
          S.probe.status === 'failed' ? 'error' : 'ok');
      },
    });
  } catch (error) {
    $('#btn-probe').disabled = false;
    $('#btn-probe-cancel').disabled = true;
    $('#probe-state').textContent = error.message;
    toast(error.message, 'error');
  }
}

async function cancelProbe() {
  if (!S.probeJob) return;
  await api(`/api/jobs/${S.probeJob}/cancel`, { method: 'POST' });
  toast('Stopping after the query that is running now.');
}

function pollJob(jobId, { log, onDone }) {
  let offset = 0;
  const tick = async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}?offset=${offset}`);
    } catch (error) {
      log.textContent += `\n${error.message}`;
      return;
    }
    if (job.logs.length) {
      log.textContent += (log.textContent ? '\n' : '') + job.logs.join('\n');
      log.scrollTop = log.scrollHeight;
      offset = job.logCount;
    }
    if (['done', 'failed', 'cancelled'].includes(job.status)) { onDone(job); return; }
    setTimeout(tick, 900);
  };
  tick();
}

function renderProbeResults() {
  const host = $('#probe-results');
  if (!host || !S.probe) return;
  host.innerHTML = '';
  const probe = S.probe;

  if (probe.blocking?.length) {
    host.append(el('div', { class: 'notice error' },
      el('strong', {}, 'Do not set this client live yet. '),
      'These have to be sorted out first.'));
    for (const blocker of probe.blocking) {
      host.append(el('div', { class: 'notice error' }, blocker));
    }
  }
  for (const warning of probe.warnings || []) {
    host.append(el('div', { class: 'notice warning' }, warning));
  }
  if (!probe.blocking?.length && !probe.warnings?.length) {
    host.append(el('div', { class: 'notice ok' },
      'Nothing to flag. This dashboard has everything the agent needs.'));
  }

  const model = probe.model || {};
  const freshness = probe.freshness || {};
  const entities = probe.entities || {};
  host.append(el('div', { class: 'panel' },
    el('h3', {}, 'What we found in your dashboard'),
    el('div', { class: 'stat-grid' },
      stat('Main table of sales', model.factTable || 'not identified'),
      stat('Main figure reported', (model.primaryMetric || {}).family || 'not identified'),
      stat('Stores identified',
        model.entityResolved ? (model.entityDimension || {}).column : 'no - choose a level by hand',
        model.entityResolved ? '' : 'bad'),
      stat('Sets of measures found', String((model.measureFamilies || []).length)),
      stat('Data goes up to', freshness.data_as_of || 'not measured',
        freshness.freshness_status === 'stale' ? 'warn' : ''),
      stat('How current it is',
        { stale: 'out of date', current: 'up to date', delayed: 'slightly behind' }[freshness.freshness_status]
        || 'not measured',
        freshness.freshness_status === 'stale' ? 'warn' : ''))));

  const families = model.measureFamilies || [];
  if (families.length) {
    host.append(el('div', { class: 'panel' },
      el('h3', {}, 'Measures the agent will use'),
      el('p', { class: 'small muted' },
        'For each figure it reports, the agent needs this year, last year, and the change. '
        + 'Where last year is missing it works it out by subtracting the change - that is fine, '
        + 'not a problem.'),
      el('div', { class: 'scroll-x' }, table(
        ['What it measures', 'This year', 'Last year', 'The change', ''],
        families.map((family) => [
          family.family + (family.isPrimary ? ' (main)' : ''),
          family.current || '—', family.prior || '—', family.change || '—',
          family.priorReconstructed
            ? el('span', { class: 'pill warn' }, 'last year worked out from the change') : '',
        ])))));
  }

  const roles = (probe.roles || {}).resolved || [];
  if (roles.length) {
    host.append(el('div', { class: 'panel' },
      el('h3', {}, 'Product levels found'),
      el('p', { class: 'small muted' },
        '"Figures add up" means every member of that level, added together, matches the '
        + 'dashboard\'s own total. If it does not, any percentage worked out for that level '
        + 'would be wrong - so do not use it.'),
      el('div', { class: 'scroll-x' }, table(
        ['Level', 'Column in your data', 'How many members', 'Figures add up',
          'Everything looked at', 'Can be used for'],
        roles.map((role) => [
          role.role, role.column || '—', role.memberCount ?? '—',
          role.reconciled === false
            ? el('span', { class: 'pill bad' }, 'no - do not use')
            : el('span', { class: 'pill ok' }, role.reconciled === true ? 'yes' : 'not checked'),
          role.poolCapped ? el('span', { class: 'pill warn' }, 'largest only') : 'yes',
          role.coverageOnly ? 'ranked table only' : 'written stories and tables',
        ]),
        roles.map((role) => role.reconciled === false)))));
  }

  const axes = probe.time_axes || [];
  if (axes.length) {
    host.append(el('div', { class: 'panel' },
      el('h3', {}, 'Date columns found'),
      el('p', { class: 'small muted' }, probe.deep
        ? 'A "data load date" records when figures were imported, not when trading happened - '
        + 'a whole month can land on one date. Day-by-day reporting on one of those would be '
        + 'meaningless, so the agent refuses to use it.'
        : 'These have not been judged yet. Tick "thorough check" above and run it again to find '
        + 'out whether day-by-day and week-by-week reporting can work here.'),
      el('div', { class: 'scroll-x' }, table(
        ['Column', 'Type', 'Verdict', 'Records by', 'Periods of history'],
        axes.map((axis) => [
          `${axis.table || ''}[${axis.column}]` + (axis.selected ? '  ← chosen' : ''),
          axis.dataType || '—',
          axis.verdict === 'batch_date'
            ? el('span', { class: 'pill bad' }, 'data load date - not usable')
            : axis.verdict
              ? el('span', { class: 'pill ok' }, 'real trading date')
              : el('span', { class: 'pill muted' }, probe.deep ? 'not needed' : 'not checked'),
          axis.grain || '—', axis.periods ?? '—',
        ])))));
  }

  host.append(el('div', { class: 'panel' },
    el('h3', {}, 'Your shops'),
    entities.resolved
      ? el('div', {},
        el('p', { class: 'small muted' },
          'Only shops trading in both years can be compared fairly. The rest still count '
          + 'towards this year\'s totals - they are simply left out of the comparison.'),
        el('div', { class: 'stat-grid' },
          stat('Trading in both years', String((entities.comparable || []).length)),
          stat('Already excluded', String((entities.excluded || []).length)),
          stat('This year only (new)', String((entities.currentOnly || []).length)),
          stat('Last year only (closed)', String((entities.priorOnly || []).length))))
      : el('p', { class: 'muted' },
        'The agent could not pick out individual shops in this dashboard, so it will work out '
        + 'which are comparable each time it runs. That is usually fine. '
        + (entities.warnings || []).join(' '))));

  if ((probe.recommendations || []).length) {
    const panel = el('div', { class: 'panel highlight' },
      el('h3', {}, 'Settings we can fill in for you'),
      el('p', { class: 'small muted' },
        'These come straight from what is in your dashboard. Applying them all is the usual '
        + 'choice - you can still change any of them afterwards.'));
    for (const recommendation of probe.recommendations) {
      const current = S.config[recommendation.key];
      const applied = JSON.stringify(current) === JSON.stringify(recommendation.value);
      const entry = S.schema.keys.find((k) => k.key === recommendation.key);
      panel.append(el('div', { class: 'recommendation' },
        el('div', { class: 'body' },
          el('div', {}, el('strong', {}, entry ? entry.label : recommendation.key), ' → ',
            el('span', { class: 'val' }, fmt(recommendation.value))),
          el('div', { class: 'small muted' }, recommendation.reason)),
        applied
          ? el('span', { class: 'pill ok' }, 'already set')
          : el('button', { class: 'btn secondary', onclick: () => applyRecommendation(recommendation) },
            'Use this')));
    }
    panel.append(el('div', { class: 'actions' },
      el('button', {
        class: 'btn teal',
        onclick: () => {
          for (const recommendation of probe.recommendations) {
            S.config[recommendation.key] = recommendation.value;
          }
          S.dirty = true;
          S.validation = null;
          toast(`${probe.recommendations.length} settings filled in.`, 'ok');
          render();
        },
      }, 'Use all of these')));
    host.append(panel);
  }

  host.append(el('details', { class: 'raw' },
    el('summary', {}, 'Everything the check returned (for support)'),
    el('pre', {}, JSON.stringify(probe, null, 2))));
}

function stat(label, value, kind = '') {
  return el('div', { class: 'stat' },
    el('div', { class: 'label' }, label),
    el('div', { class: `value ${kind}` }, value));
}

function table(headers, rows, badFlags = []) {
  const head = el('thead', {}, el('tr', {}, ...headers.map((h) => el('th', {}, h))));
  const body = el('tbody');
  rows.forEach((row, index) => {
    body.append(el('tr', { class: badFlags[index] ? 'bad' : '' },
      ...row.map((cell) => el('td', {}, cell))));
  });
  return el('table', { class: 'grid' }, head, body);
}

/* ------------------------------------------------------- step: rulebooks */

function renderRulebooksStep() {
  const main = $('#main');
  main.append(template('tpl-rulebooks'));
  const area = $('#rule-text');

  const sync = () => {
    area.value = S.ruleTab === 'business' ? S.businessRules : S.summaryBusinessRules;
    $$('#rule-tabs button').forEach((button) =>
      button.classList.toggle('active', button.dataset.tab === S.ruleTab));
    updateRuleMeter();
  };

  $$('#rule-tabs button').forEach((button) => button.addEventListener('click', () => {
    S.ruleTab = button.dataset.tab;
    sync();
  }));

  area.addEventListener('input', () => {
    if (S.ruleTab === 'business') S.businessRules = area.value;
    else S.summaryBusinessRules = area.value;
    S.dirty = true;
    S.validation = null;
    updateRuleMeter();
    markDirty();
  });

  $('#rule-upload').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const text = await file.text();
    if (S.ruleTab === 'business') S.businessRules = text; else S.summaryBusinessRules = text;
    S.dirty = true;
    sync();
    toast(`Loaded ${file.name} (${Math.round(file.size / 1024)} KB).`, 'ok');
  });

  $('#btn-rule-template').addEventListener('click', async () => {
    const templates = await api(`/api/clients/${encodeURIComponent(S.name || 'x')}/defaults`);
    const text = S.ruleTab === 'business' ? templates.business_rules : templates.summary_business_rules;
    if (!text) { toast('There is no starting template for that one.', 'error'); return; }
    if (S.ruleTab === 'business') S.businessRules = text; else S.summaryBusinessRules = text;
    S.dirty = true;
    sync();
    toast('Template loaded. Replace the parts that do not apply to this client.', 'ok');
  });

  sync();
  main.append(navButtons('rulebooks'));
}

function updateRuleMeter() {
  const text = S.ruleTab === 'business' ? S.businessRules : S.summaryBusinessRules;
  const bytes = new TextEncoder().encode(text).length;
  const typical = S.ruleTab === 'business' ? 45000 : 4000;
  $('#rule-size').textContent = `${(bytes / 1024).toFixed(1)} KB — a typical one is about `
    + `${typical / 1000} KB`;
  $('#rule-meter').style.width = `${Math.min(100, (bytes / typical) * 100)}%`;
  $('#rule-note').textContent = S.ruleTab === 'business'
    ? 'This is sent to the AI with every single request, so anything in it shapes every number '
      + 'and every sentence. Keep it to rules that genuinely change how figures are worked out.'
    : 'This one is much shorter. It covers how the daily summary should be worded and which '
      + 'figures your managers actually care about.';
}

/* ---------------------------------------------------------- step: review */

function renderReviewStep() {
  const main = $('#main');
  main.append(template('tpl-review'));
  $('#run-command').textContent = S.name
    ? `cd powerbi-summary-agent\npython -m src.main --config config/${S.name}/config.json`
    : 'Choose a client first.';
  $('#config-preview').textContent = JSON.stringify(S.config, null, 2);
  $('#btn-validate').addEventListener('click', runValidation);
  $('#btn-save').addEventListener('click', saveClient);
  $('#btn-bundle').addEventListener('click', () => {
    if (!S.name) { toast('Save the client first.', 'error'); return; }
    window.location = `/api/clients/${encodeURIComponent(S.name)}/bundle`;
  });
  if (S.validation) renderValidation(); else runValidation();
  main.append(navButtons('review'));
}

async function runValidation() {
  const host = $('#validation');
  if (host) host.innerHTML = '<span class="spinner dark"></span> checking…';
  try {
    S.validation = await api('/api/validate', {
      method: 'POST',
      body: {
        name: S.name,
        config: S.config,
        probe: S.probe,
        target: $('#validate-container')?.checked ? 'container' : 'local',
        businessRules: S.businessRules,
        summaryBusinessRules: S.summaryBusinessRules,
        env: deployEnv(),
      },
    });
    renderValidation();
    renderNav();
  } catch (error) {
    if (host) host.innerHTML = '';
    toast(error.message, 'error');
  }
}

function renderValidation() {
  const host = $('#validation');
  if (!host || !S.validation) return;
  host.innerHTML = '';
  const { findings, errorCount, warningCount, ok } = S.validation;

  host.append(el('div', { class: `notice ${ok ? 'ok' : 'error'}` },
    el('strong', {}, ok
      ? 'Nothing is blocking this client. '
      : `${errorCount} thing${errorCount === 1 ? '' : 's'} must be fixed first. `),
    warningCount
      ? `${warningCount} other${warningCount === 1 ? '' : 's'} worth reading, but not blocking.`
      : 'No other warnings.',
    S.validation.hasProbe ? '' : ' The data check has not run, so answers about product levels '
      + 'and shops have not been verified against the real dashboard.'));

  const order = { error: 0, warning: 1, info: 2 };
  const heading = {
    error: 'Must be fixed',
    warning: 'Worth reading',
    info: 'For your information',
  };
  let last = null;
  for (const finding of [...findings].sort((a, b) => order[a.level] - order[b.level])) {
    if (finding.level !== last) {
      last = finding.level;
      host.append(el('h4', { class: 'finding-head' }, heading[finding.level]));
    }
    const node = el('div', { class: `notice ${finding.level}` },
      el('strong', {}, finding.title || finding.key), el('br'),
      finding.message,
      finding.fix ? el('span', { class: 'fix' }, 'What to do: ' + finding.fix) : null);
    const entry = S.schema.keys.find((k) => k.key === finding.key);
    if (entry) {
      node.append(' ', el('button', {
        class: 'link',
        onclick: () => { go(entry.group); setTimeout(() => highlight(finding.key), 60); },
      }, 'Take me to it'));
    }
    host.append(node);
  }
}

function highlight(key) {
  const entry = S.schema.keys.find((k) => k.key === key);
  // A finding can point at a setting the current detail level hides, so widen
  // the view rather than scrolling to nothing.
  if (entry && TIER_ORDER[entry.tier] > DETAIL_LEVELS[S.detail].max) {
    S.detail = 'all';
    renderGroupBody(entry.group);
  }
  const node = document.querySelector(`[data-key="${key}"]`);
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  node.classList.add('flash');
  setTimeout(() => node.classList.remove('flash'), 2000);
}

async function saveClient() {
  if (!S.name) { toast('Choose a client first.', 'error'); return; }
  try {
    await api(`/api/clients/${encodeURIComponent(S.name)}`, {
      method: 'PUT',
      body: {
        config: S.config,
        businessRules: S.businessRules,
        summaryBusinessRules: S.summaryBusinessRules,
      },
    });
    S.dirty = false;
    markDirty();
    await refreshClients();
    toast(`Saved. Everything for ${S.name} is now in config/${S.name}/.`, 'ok');
    runValidation();
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ---------------------------------------------------------- step: deploy */

const DEPLOY_FIELDS = [
  ['subscriptionId', 'Azure subscription ID', 'Your Azure administrator can give you this.'],
  ['resourceGroup', 'Resource group', 'The group the scheduled job lives in.'],
  ['jobName', 'Name for the scheduled job', 'Something like insightgen-<client>-daily-job.'],
  ['environmentId', 'Container Apps environment',
    'The full ID. Not needed when updating a job that already exists.'],
  ['location', 'Region', 'For example eastus2. Not needed when updating an existing job.'],
  ['image', 'Container image', 'The published version of the agent to run.'],
  ['cron', 'When it runs (UTC)',
    'Five fields: minute, hour, day, month, weekday. "30 3 * * *" means 3:30am every day. '
    + 'Stagger clients so they do not all run at once.'],
  ['cpu', 'Processor share', 'Existing jobs use 1.0.'],
  ['memory', 'Memory', 'Existing jobs use 2Gi.'],
  ['replicaTimeout', 'Give up after (seconds)', '3600 is normal. A run takes 4-5 minutes.'],
  ['replicaRetryLimit', 'Retries if it fails', '1 is normal.'],
  ['identityResourceId', 'Managed identity',
    'The identity allowed to read Power BI and write to storage.'],
  ['registryServer', 'Container registry', 'Where the image is stored.'],
  ['registryIdentity', 'Identity used to pull the image', 'Usually the same identity as above.'],
];

const DEPLOY_ENV_DEFAULTS = {
  AGENT_OUTPUT_FOLDER: 'outputs',
  POWERBI_AUTH_MODE: 'managed_identity',
  POWERBI_QUERY_API: 'arrow',
  AZURE_OPENAI_ENDPOINT: '',
  AZURE_OPENAI_DEPLOYMENT: '',
  AZURE_OPENAI_API_VERSION: '',
  AZURE_MANAGED_IDENTITY_CLIENT_ID: '',
};

const ENV_NOTES = {
  AGENT_OUTPUT_FOLDER: 'Where the job saves files. Must be "outputs" - it cannot write anywhere else.',
  POWERBI_AUTH_MODE: 'How the job signs in to Power BI. In the cloud this must be the server identity.',
  POWERBI_QUERY_API: 'Response format. "arrow" is right for an unattended job.',
  AZURE_OPENAI_ENDPOINT: 'Your Azure OpenAI address.',
  AZURE_OPENAI_DEPLOYMENT: 'Which Azure OpenAI deployment to use. For Azure, this decides the '
    + 'model - not the model box on the Connect step.',
  AZURE_OPENAI_API_VERSION: 'Azure OpenAI API version.',
  AZURE_MANAGED_IDENTITY_CLIENT_ID: 'The client ID of the identity above.',
};

const MAPPED_ENV = {
  AGENT_OUTPUT_FOLDER: 'output_folder',
  POWERBI_AUTH_MODE: 'powerbi_auth_mode',
  POWERBI_QUERY_API: 'powerbi_query_api',
};

function deployEnv() {
  return { ...DEPLOY_ENV_DEFAULTS, ...(S.deploy.env || {}) };
}

function renderDeployStep() {
  const main = $('#main');
  main.append(template('tpl-deploy'));

  const gate = $('#deploy-gate');
  if (!S.probe) {
    gate.append(el('div', { class: 'notice error' },
      el('strong', {}, 'The data check has not been run. '),
      'Nobody has confirmed this dashboard\'s figures add up, so this client should not be '
      + 'scheduled yet. ',
      el('button', { class: 'link', onclick: () => go('probe') }, 'Run the check')));
  }
  if (!S.validation || !S.validation.ok) {
    gate.append(el('div', { class: 'notice warning' },
      el('strong', {}, 'Not checked yet, or something is blocking. '),
      'A folder clash, a missing storage container or a failed data check all stop a client '
      + 'going live. ',
      el('button', { class: 'link', onclick: () => go('review') }, 'Check it now')));
  }

  const fields = $('#deploy-fields');
  for (const [key, label, help] of DEPLOY_FIELDS) {
    const input = el('input', { type: 'text', id: `d-${key}`, autocomplete: 'off' });
    input.value = S.deploy[key] ?? '';
    input.addEventListener('change', () => {
      S.deploy[key] = input.value;
      localStorage.setItem('insightgen.deploy', JSON.stringify(S.deploy));
    });
    fields.append(el('div', { class: 'field' },
      el('label', { for: `d-${key}` }, label), input, el('div', { class: 'help' }, help)));
  }

  const envHost = $('#deploy-env');
  const env = deployEnv();
  for (const key of Object.keys(env)) {
    const input = el('input', { type: 'text', id: `e-${key}`, autocomplete: 'off' });
    input.value = env[key];
    input.addEventListener('change', () => {
      S.deploy.env = { ...deployEnv(), [key]: input.value };
      localStorage.setItem('insightgen.deploy', JSON.stringify(S.deploy));
      S.validation = null;
    });
    const mapped = MAPPED_ENV[key];
    const entry = mapped && S.schema.keys.find((k) => k.key === mapped);
    envHost.append(el('div', { class: 'field' },
      el('label', { for: `e-${key}` }, key,
        entry ? el('span', { class: 'key' }, ` overrides "${entry.label}" from the form`) : null),
      input,
      el('div', { class: 'help' }, ENV_NOTES[key] || '')));
  }

  $('#btn-preview').addEventListener('click', previewDeploy);
  $('#btn-deploy').addEventListener('click', runDeploy);
  $('#btn-run-now').addEventListener('click', runNow);
  main.append(navButtons('deploy'));
}

function deployPayload() {
  // An env var set to the empty string still overrides the config - presence is
  // what main.py checks, not truthiness - so blanks are dropped rather than sent.
  const env = Object.fromEntries(
    Object.entries(deployEnv()).filter(([, value]) => String(value).trim() !== ''));
  return {
    name: S.name,
    job: {
      ...S.deploy,
      cpu: Number(S.deploy.cpu || 1),
      replicaTimeout: Number(S.deploy.replicaTimeout || 3600),
      replicaRetryLimit: Number(S.deploy.replicaRetryLimit || 1),
      env,
      secretEnv: { AZURE_OPENAI_API_KEY: 'azure-openai-api-key' },
    },
  };
}

async function previewDeploy() {
  try {
    const data = await api('/api/deploy/preview', { method: 'POST', body: deployPayload() });
    $('#deploy-log').textContent = JSON.stringify(data, null, 2);
    toast('This is exactly what would be sent to Azure. Nothing has been changed.', 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function runDeploy() {
  const name = S.deploy.jobName || '(no name yet)';
  if (!confirm(`Create or update the scheduled job "${name}"?\n\n`
    + 'This uploads the settings and both rule documents to Azure. Anything already on the job '
    + 'that this app does not manage is left untouched.')) return;
  $('#deploy-state').innerHTML = '<span class="spinner dark"></span> sending…';
  try {
    const data = await api('/api/deploy', { method: 'POST', body: deployPayload() });
    if (data.deployed === false) {
      $('#deploy-state').textContent = 'Refused - something is blocking';
      S.validation = data.validation;
      $('#deploy-log').textContent = data.validation.findings
        .filter((f) => f.level === 'error')
        .map((f) => `${f.title || f.key}\n    ${f.message}`
          + `${f.fix ? '\n    What to do: ' + f.fix : ''}`)
        .join('\n\n');
      toast('Not deployed: fix the blocking problems shown below first.', 'error');
      return;
    }
    $('#deploy-log').textContent = '';
    pollJob(data.jobId, {
      log: $('#deploy-log'),
      onDone: (job) => {
        const result = job.result || {};
        const ok = result.status === 'ok';
        $('#deploy-state').textContent = ok ? 'Done' : 'Failed';
        toast(ok
          ? `${result.created ? 'Created' : 'Updated'} the scheduled job. It will run on the `
            + 'schedule you set.'
          : `Could not deploy: ${result.reason || job.error}`,
          ok ? 'ok' : 'error');
      },
    });
  } catch (error) {
    $('#deploy-state').textContent = error.message;
    toast(error.message, 'error');
  }
}

async function runNow() {
  try {
    const data = await api('/api/deploy/start', { method: 'POST', body: deployPayload() });
    toast(`Started a run now${data.executionName ? ` (${data.executionName})` : ''}. `
      + 'A full run takes about 4-5 minutes.', 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ---------------------------------------------------------------- render */

function template(id) {
  return document.getElementById(id).content.cloneNode(true);
}

function updateChips() {
  $('#chip-client').textContent = S.name
    ? (S.dirty ? `${S.name} — not saved yet` : S.name)
    : 'no client chosen';
  const words = { ok: 'all clear', degraded: 'check it', failed: 'problems found' };
  $('#chip-probe').textContent = S.probe
    ? `data check: ${words[S.probe.status] || S.probe.status}`
    : 'data not checked';
}

function markDirty() {
  updateChips();
}

function render() {
  const main = $('#main');
  main.innerHTML = '';
  const step = STEPS.find((s) => s.id === S.step) || STEPS[0];

  if (step.id !== 'client' && !S.name) {
    main.append(el('div', { class: 'notice warning' },
      'No client is open yet. ',
      el('button', { class: 'link', onclick: () => go('client') }, 'Choose or start one first.')));
    return;
  }

  if (step.render) step.render();
  else renderGroup(step.group);
  updateChips();
}

async function refreshClients() {
  const data = await api('/api/clients');
  S.clients = data.clients;
}

async function boot() {
  S.detail = localStorage.getItem('insightgen.detail') || 'essential';
  if (!DETAIL_LEVELS[S.detail]) S.detail = 'essential';
  try {
    S.schema = await api('/api/schema');
    await refreshClients();
  } catch (error) {
    $('#main').append(el('div', { class: 'notice error' },
      `Could not reach the server: ${error.message}. Check it is still running.`));
    return;
  }
  renderNav();
  render();
  window.addEventListener('beforeunload', (event) => {
    if (!S.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
}

boot();
