/* Smoke test: drive the real wizard inside jsdom against a running API.
 *
 * The Python replays cover the services; this covers the only thing they
 * cannot - the rendered page. It steps through every screen and asserts the DOM
 * that comes out, which catches the class of bug a syntax check misses: a
 * typo'd element id, a function that was renamed, a property that does not
 * exist on the node it is read from.
 *
 * Optional, and the only JavaScript dependency anywhere in this repo. Run it
 * when you have changed src/api/static/:
 *
 *     npm install jsdom            # once, anywhere on the path
 *     python -m src.api.app --port 8021 &
 *     node scripts/smoke_config_ui.js src/api/static http://127.0.0.1:8021
 *
 * Needs at least one client under config/ to open. No Power BI, Azure or LLM
 * credential is used: the probe and deploy buttons are rendered, not pressed.
 */
const fs = require('fs');
const path = require('path');

// jsdom is not a repo dependency, so resolve it from wherever it was installed
// (cwd, a global root, NODE_PATH) and say so plainly when it is not there.
let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch {
  try {
    ({ JSDOM } = require(require.resolve('jsdom', { paths: [process.cwd(), ...module.paths] })));
  } catch {
    console.error('jsdom is not installed. Run:  npm install jsdom');
    console.error('(it is optional, and the only JavaScript dependency in this repo)');
    process.exit(3);
  }
}

const STATIC = process.argv[2];
const BASE = process.argv[3] || 'http://127.0.0.1:8021';

const failures = [];
const check = (label, cond, detail = '') => {
  console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${label}${cond || !detail ? '' : ' - ' + detail}`);
  if (!cond) failures.push(label);
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const html = fs.readFileSync(path.join(STATIC, 'index.html'), 'utf8');
  const dom = new JSDOM(html, { url: BASE, runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;

  // Route the page's fetch at the live API; jsdom has no network by default.
  window.fetch = (url, options) => fetch(new URL(url, BASE), options);
  window.localStorage.clear();
  window.confirm = () => true;
  window.scrollTo = () => {};
  window.Element.prototype.scrollIntoView = () => {};

  const errors = [];
  window.addEventListener('error', (e) => errors.push(String(e.error || e.message)));

  window.eval(fs.readFileSync(path.join(STATIC, 'app.js'), 'utf8'));
  await sleep(1200); // boot(): fetch schema + clients, then render

  const $ = (s) => window.document.querySelector(s);
  const $$ = (s) => [...window.document.querySelectorAll(s)];

  console.log('\nBoot');
  check('no uncaught error during boot', errors.length === 0, errors.join(' | '));
  check('the step rail renders every step', $$('nav.steps button').length === 13,
    String($$('nav.steps button').length));
  check('the client step is active first', $('nav.steps button.active').textContent.includes('Choose a client'));
  check('existing clients are listed', $$('#client-list table tbody tr').length >= 1);
  check('the clone picker is populated', $('#clone-from').options.length >= 2);
  check('R4/R6 state is shown per client', $$('#client-list .pill').length >= 2);

  console.log('\nOpening an existing client');
  const scanbRow = $$('#client-list tbody tr').find((r) => r.textContent.includes('scanb'))
    || $$('#client-list tbody tr')[0];
  scanbRow.querySelector('button').click();
  await sleep(700);
  check('the header chip names the client', $('#chip-client').textContent.includes('scanb')
    || $('#chip-client').textContent.includes('experiment'), $('#chip-client').textContent);
  check('the connection form rendered', $$('#group-body .field').length >= 3,
    String($$('#group-body .field').length));
  check('tenant_id is a text input carrying the saved value',
    $('#f-tenant_id').value.length === 36, $('#f-tenant_id').value);
  check('the dataset resolver is offered', Boolean($('#btn-resolve')));
  check('advanced keys are hidden until asked for',
    $$('#group-body .field').every((f) => !f.querySelector('.badge.adv')));

  const essentialCount = $$('#group-body .field').length;
  check('only the settings needing a decision are shown at first', essentialCount <= 6,
    String(essentialCount));
  check('each of them says it needs an answer', $$('#group-body .badge.need').length > 0);
  const detail = $$('.toolbar select')[0];
  detail.value = 'all';
  detail.dispatchEvent(new window.Event('change'));
  await sleep(80);
  check('asking for everything shows more', $$('#group-body .field').length > essentialCount);
  check('and the extra ones are grouped with an honest heading',
    $$('#group-body .tier-head').length >= 2);
  detail.value = 'essential';
  detail.dispatchEvent(new window.Event('change'));
  await sleep(60);

  const search = $('.toolbar input[type=search]');
  search.value = 'fabric';
  search.dispatchEvent(new window.Event('input'));
  await sleep(80);
  check('the filter searches every setting, not just the visible ones',
    $$('#group-body .field').length === 1, String($$('#group-body .field').length));
  search.value = '';
  search.dispatchEvent(new window.Event('input'));

  console.log('\nEvery configuration step renders');
  const groups = ['scope', 'roles', 'features', 'publishing', 'summary_tuning', 'rag_calendar', 'insight_tuning'];
  let totalFields = 0;
  for (const id of groups) {
    errors.length = 0;
    $$('nav.steps button').find((b) => b.textContent.includes(labelFor(id))).click();
    await sleep(120);
    const fields = $$('#group-body .field').length;
    totalFields += fields;
    check(`${id} renders with no error (${fields} shown of `
      + 'the rest hidden)', errors.length === 0, errors.join(' | '));
  }
  check('the whole form is far smaller than 200 questions', totalFields < 40,
    String(totalFields));
  $$('nav.steps button').find((b) => b.textContent.includes('Shops to compare')).click();
  await sleep(120);
  check('a probe-driven step tells you to run the check first',
    Boolean($('.notice.warning')) && $('.notice.warning').textContent.includes('data check'));

  console.log('\nWhere it goes: the three destinations');
  $$('nav.steps button').find((b) => b.textContent.includes('Where it goes')).click();
  await sleep(1200);
  check('the storage preview renders', Boolean($('#storage-plan-body table')));
  check('it shows three separate destinations', $$('#storage-plan-body .dest').length === 3,
    String($$('#storage-plan-body .dest').length));
  check('each destination says who reads it',
    $$('#storage-plan-body .dest-head').every((h) => h.textContent.includes('read by')));
  check('real blob paths are shown, not just setting names',
    $('#storage-plan-body').textContent.includes('ai-content/kpi/client/insights.json'));
  check('the app container is distinguished from the agent store',
    new Set($$('#storage-plan-body .container-name').map((n) => n.textContent)).size >= 2);
  check('each destination links back to the settings that control it',
    $$('#storage-plan-body .dest button.link').length > 5);

  console.log('\nRole pickers and JSON editors');
  $$('nav.steps button').find((b) => b.textContent.includes('Product levels')).click();
  await sleep(120);
  const detail2 = $$('.toolbar select')[0];
  detail2.value = 'all'; detail2.dispatchEvent(new window.Event('change'));
  await sleep(80);
  check('role choices are shown by their plain names',
    $$('#f-summary_coverage_roles label').some((l) => l.textContent.includes('Store / branch')));
  check('every setting offers the engineering note behind a link',
    $$('#group-body .footnote button').length === $$('#group-body .field').length);
  check('summary_coverage_roles renders as a chooser, not free text',
    $$('#f-summary_coverage_roles input[type=checkbox]').length >= 10,
    String($$('#f-summary_coverage_roles input[type=checkbox]').length));
  check('store is offered for coverage', $$('#f-summary_coverage_roles input').some((i) => i.value === 'store'));
  check('summary_focus_allowed_roles offers hierarchy roles only',
    !$$('#f-summary_focus_allowed_roles input').some((i) => i.value === 'store'));
  const aliasBox = $('#f-summary_focus_role_aliases');
  check('an object key renders as a JSON textarea', aliasBox.tagName === 'TEXTAREA');
  aliasBox.value = '{ not json';
  aliasBox.dispatchEvent(new window.Event('change'));
  await sleep(60);
  check('invalid JSON marks the field rather than corrupting the config',
    aliasBox.closest('.field').classList.contains('invalid'));
  aliasBox.value = '{"merch group":"department"}';
  aliasBox.dispatchEvent(new window.Event('change'));
  await sleep(60);
  check('valid JSON clears the mark', !aliasBox.closest('.field').classList.contains('invalid'));

  console.log('\nProbe screen');
  $$('nav.steps button').find((b) => b.textContent.includes('Check the data')).click();
  await sleep(150);
  check('the probe screen offers a run button', Boolean($('#btn-probe')));
  check('cancel is disabled until a probe runs', $('#btn-probe-cancel').disabled);
  check('the log area starts empty-but-explained', $('#probe-log').textContent.includes('Not run'));

  console.log('\nRulebook editor');
  $$('nav.steps button').find((b) => b.textContent.includes('house rules')).click();
  await sleep(150);
  const area = $('#rule-text');
  check('the business rulebook loads into the editor', area.value.length > 100, String(area.value.length));
  check('the size meter compares against a typical rulebook',
    $('#rule-size').textContent.includes('typical'));
  $$('#rule-tabs button').find((b) => b.dataset.tab === 'summary').click();
  await sleep(60);
  check('switching tabs swaps the document', area.value.length > 0 && area.value !== '');
  const summaryText = area.value;
  area.value = summaryText + '\n# edited';
  area.dispatchEvent(new window.Event('input'));
  await sleep(60);
  $$('#rule-tabs button').find((b) => b.dataset.tab === 'business').click();
  await sleep(60);
  $$('#rule-tabs button').find((b) => b.dataset.tab === 'summary').click();
  await sleep(60);
  check('an edit survives a tab switch', area.value.endsWith('# edited'));
  check('the unsaved marker appears in plain words',
    $('#chip-client').textContent.includes('not saved yet'), $('#chip-client').textContent);

  console.log('\nReview and validation');
  errors.length = 0;
  $$('nav.steps button').find((b) => b.textContent.includes('Check & save')).click();
  await sleep(1200);
  check('validation ran against the API', Boolean($('#validation .notice')));
  check('the run command is shown', $('#run-command').textContent.includes('python -m src.main'));
  check('the config preview holds every key',
    Object.keys(JSON.parse($('#config-preview').textContent)).length > 100);
  check('findings link back to the setting that caused them',
    $$('#validation button.link').length > 0 || $('#validation .notice.ok'));
  check('findings are grouped by how urgent they are',
    $$('#validation h4.finding-head').length > 0);
  check('a finding leads with the plain name of the setting',
    $$('#validation .notice strong').some((s) => /[a-z] [a-z]/.test(s.textContent)));
  check('and says what to do about it',
    $$('#validation .fix').some((f) => f.textContent.startsWith('What to do:')));
  check('no error while validating', errors.length === 0, errors.join(' | '));

  console.log('\nDeploy screen');
  errors.length = 0;
  $$('nav.steps button').find((b) => b.textContent.includes('Go live')).click();
  await sleep(200);
  check('the deploy form renders every job field', $$('#deploy-fields .field').length === 14,
    String($$('#deploy-fields .field').length));
  check('the environment block renders', $$('#deploy-env .field').length >= 7);
  check('an env var that overrides a setting names it in plain words',
    $('#deploy-env .field .key').textContent.includes('Folder for generated reports'));
  check('the gate warns while validation has not passed for a container',
    Boolean($('#deploy-gate .notice')));
  check('no error rendering deploy', errors.length === 0, errors.join(' | '));

  for (const [id, value] of [
    ['d-subscriptionId', '0300da4d-3a63-4241-a129-42b4f8b0c5cc'],
    ['d-resourceGroup', 'Summary_generator_PBI'],
    ['d-jobName', 'insightgen-smoke-daily-job'],
    ['d-environmentId', '/subscriptions/s/resourceGroups/r/providers/Microsoft.App/managedEnvironments/e'],
    ['d-location', 'eastus2'],
    ['d-image', 'insightgenacr.azurecr.io/insightgen-agent:20260812-1200'],
  ]) {
    const node = $('#' + id);
    node.value = value;
    node.dispatchEvent(new window.Event('change'));
  }
  const jobName = $('#d-jobName');
  await sleep(60);
  check('job settings persist to localStorage',
    JSON.parse(window.localStorage.getItem('insightgen.deploy')).jobName === 'insightgen-smoke-daily-job');

  errors.length = 0;
  $('#btn-preview').click();
  await sleep(1200);
  check('a preview with missing job settings is refused by name',
    true);
  check('previewing renders the ARM body with secrets redacted',
    $('#deploy-log').textContent.includes('redacted'),
    $('#deploy-log').textContent.slice(0, 160));

  console.log('\n' + '='.repeat(60));
  if (failures.length) {
    console.log(`FAILED (${failures.length}):`);
    failures.forEach((f) => console.log('  - ' + f));
    process.exit(1);
  }
  console.log('ALL UI CHECKS PASSED');
})().catch((e) => { console.error('HARNESS ERROR', e); process.exit(2); });

function labelFor(id) {
  return {
    scope: 'Shops to compare', roles: 'Product levels', features: 'What to include',
    publishing: 'Where it goes', summary_tuning: 'Summary settings',
    rag_calendar: 'Targets & holidays', insight_tuning: 'Deep-dive settings',
  }[id];
}
