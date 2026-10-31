// Application tracker page. Every value comes from /api/tracker; data is only ever put in the
// page as text nodes, because postings and notes are third-party or free-form text.
const STAGE_VAR = {applied: '--applied', interviewing: '--interviewing', 'offer received': '--offer',
  rejected: '--rejected', withdrawn: '--withdrawn'};
const FORMAT_LABEL = {phone: 'Phone', video: 'Video', in_person: 'In person'};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const state = {data: null, q: '', stage: 'all', dueOnly: false, view: 'list', sort: 'attention', open: null, tab: 'details', jd: {}};
const $ = id => document.getElementById(id);

const stored = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* the page works without it */ } },
};

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'class') node.className = value;
    else if (key === 'style') node.style.cssText = value;
    else if (key === 'value') node.value = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  node.append(...kids.flat().filter(k => k !== null && k !== undefined && k !== false));
  return node;
}

const parts = iso => (iso || '').split('-').map(Number);
const asDate = iso => { const [y, m, d] = parts(iso); return y && m && d ? new Date(y, m - 1, d) : null; };
function shortDate(iso) { const d = asDate(iso); return d ? `${MONTHS[d.getMonth()]} ${d.getDate()}` : (iso || 'No date'); }
function longDate(iso) { const d = asDate(iso); return d ? `${DAYS[d.getDay()]} ${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}` : (iso || 'No date'); }
function clock(t) {
  if (!t) return '';
  const [h, m] = t.split(':').map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`;
}
function dueText(f) {
  if (f.state === 'overdue') return `${-f.days} day${f.days === -1 ? '' : 's'} overdue`;
  if (f.state === 'today') return 'Due today';
  if (f.days === 1) return 'Due tomorrow';
  return `Due in ${f.days} days`;
}
const stageColor = s => `--c: var(${STAGE_VAR[s]})`;
const nextInterview = a => a.interviews.find(i => i.date >= state.data.today);
const app = id => state.data.applications.find(a => a.id === id);

function toast(message, bad) {
  const t = $('toast');
  t.textContent = message;
  t.className = bad ? 'toast bad' : 'toast';
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 1800);
}

async function api(path, body) {
  const res = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined);
  let data = null;
  try { data = await res.json(); } catch { /* an HTML error page */ }
  if (!res.ok) throw new Error((data && data.error) || `The server answered ${res.status}`);
  return data;
}

async function load() {
  try {
    state.data = await api('/api/tracker');
    $('error').hidden = true;
  } catch (err) {
    $('error').textContent = err.message;
    $('error').hidden = false;
    return false;
  }
  renderAll();
  return true;
}

function renderAll() {
  $('today').textContent = longDate(state.data.today);
  renderOverview();
  renderChips();
  renderResults();
  const d = state.data.detached;
  $('foot').textContent = d ? `${d} set${d === 1 ? '' : 's'} of details kept for rows no longer in the CSV (a dashboard box was unticked). They return if the row does.` : '';
}

/* overview */
function renderOverview() {
  const s = state.data.summary;
  const box = $('overview');
  box.replaceChildren();
  $('work').hidden = false;
  if (!s.total) { box.hidden = true; return; }
  box.hidden = false;
  const bars = state.data.stages.filter(k => s.counts[k]).map(k =>
    el('i', {style: `${stageColor(k)};flex:${s.counts[k]}`, title: `${k}: ${s.counts[k]}`}));
  box.append(el('div', {class: 'panel'},
    el('h2', {}, 'Pipeline'),
    el('div', {class: 'total'}, String(s.total), el('small', {}, s.total === 1 ? 'application' : 'applications')),
    el('div', {class: 'stack', 'aria-hidden': 'true'}, bars),
    el('ul', {class: 'legend'}, state.data.stages.map(k => el('li', {},
      el('button', {type: 'button', style: stageColor(k), 'aria-pressed': String(state.stage === k), onclick: () => setStage(state.stage === k ? 'all' : k)},
        el('span', {class: 'dot'}), k, el('b', {}, String(s.counts[k]))))))));

  const due = s.overdue + s.due_today;
  box.append(el('div', {class: 'panel'},
    el('h2', {}, 'Follow-ups', el('b', {}, due ? `${due} due` : 'none due')),
    s.follow_ups.length ? el('ul', {class: 'mini'}, s.follow_ups.slice(0, 5).map(a => el('li', {},
      el('button', {type: 'button', onclick: () => openApp(a.id)},
        el('span', {class: 'who'}, a.company), el('span', {class: 'what'}, a.role),
        el('span', {class: `when ${a.follow_up.state}`}, dueText(a.follow_up))))))
      : el('p', {class: 'nil'}, 'Nothing in the next few days.')));

  box.append(el('div', {class: 'panel'},
    el('h2', {}, 'Interviews', el('b', {}, s.upcoming.length ? `${s.upcoming.length} upcoming` : 'none booked')),
    s.upcoming.length ? el('ul', {class: 'mini'}, s.upcoming.slice(0, 5).map(i => el('li', {},
      el('button', {type: 'button', onclick: () => openApp(i.app_id)},
        el('span', {class: 'who'}, i.company),
        el('span', {class: 'what'}, [FORMAT_LABEL[i.format], i.with].filter(Boolean).join(' with ')),
        el('span', {class: 'when'}, `${shortDate(i.date)} ${clock(i.time)}`.trim())))))
      : el('p', {class: 'nil'}, 'Add one from an application when it is scheduled.')));

  const top = Math.max(...s.weeks.map(w => w.count), 1);
  box.append(el('div', {class: 'panel'},
    el('h2', {}, 'Applied per week'),
    el('div', {class: 'weeks', role: 'img', 'aria-label': s.weeks.map(w => `week of ${shortDate(w.start)}: ${w.count}`).join(', ')},
      s.weeks.map(w => el('div', {title: `Week of ${shortDate(w.start)}: ${w.count} applied`},
        el('i', {style: `height:${w.count / top * 100}%`})))),
    el('p', {class: 'pace-note'}, s.sent ? `${s.heard_back} of ${s.sent} reached an interview or offer` : 'Nothing sent yet')));
}

function setStage(stage) { state.stage = stage; state.dueOnly = false; renderOverview(); renderChips(); renderResults(); }

function renderChips() {
  const s = state.data.summary;
  $('chips').replaceChildren(
    el('button', {type: 'button', 'aria-pressed': String(state.stage === 'all' && !state.dueOnly), onclick: () => setStage('all')}, `All ${s.total}`),
    el('button', {type: 'button', 'aria-pressed': String(state.dueOnly), onclick: () => { state.dueOnly = !state.dueOnly; state.stage = 'all'; renderOverview(); renderChips(); renderResults(); }}, 'Follow-up due'),
    ...state.data.stages.map(k => el('button', {type: 'button', 'aria-pressed': String(state.stage === k), onclick: () => setStage(k)}, `${k[0].toUpperCase()}${k.slice(1)}`)));
  document.querySelectorAll('.switch button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
}

/* list and pipeline */
function matches(a) {
  if (state.stage !== 'all' && a.status !== state.stage) return false;
  if (state.dueOnly && !['overdue', 'today'].includes(a.follow_up.state)) return false;
  if (!state.q) return true;
  const hay = [a.company, a.role, a.location, a.contact, a.notes, a.salary, a.raw_status, a.log,
    ...a.interviews.map(i => `${i.with} ${i.notes}`)].join(' ').toLowerCase();
  return state.q.toLowerCase().split(/\s+/).every(w => hay.includes(w));
}

function urgency(a) {
  const f = a.follow_up;
  if (a.final) return 1e6;
  if (f.state === 'overdue') return f.days - 1000;
  const next = nextInterview(a);
  if (next) return (asDate(next.date) - asDate(state.data.today)) / 864e5 - 500;
  return f.date ? f.days : 1e5;
}

function sorted(list) {
  const by = {
    newest: (a, b) => b.date.localeCompare(a.date),
    oldest: (a, b) => a.date.localeCompare(b.date),
    company: (a, b) => a.company.localeCompare(b.company),
    attention: (a, b) => urgency(a) - urgency(b) || b.date.localeCompare(a.date),
  };
  return [...list].sort(by[state.sort]);
}

function flagsFor(a) {
  const next = nextInterview(a);
  return [
    a.drafted && el('span', {class: 'tag plain'}, 'Drafted, not sent'),
    next && el('span', {class: 'tag meet'}, `${FORMAT_LABEL[next.format]} ${shortDate(next.date)}`),
    ['overdue', 'today', 'soon'].includes(a.follow_up.state) && el('span', {class: `tag ${a.follow_up.state}`}, dueText(a.follow_up)),
    !a.jd_saved && el('span', {class: 'tag missing'}, 'Description missing'),
  ];
}

function renderResults() {
  const box = $('results');
  const toolbar = document.querySelector('.toolbar');
  if (!state.data.applications.length) {
    toolbar.hidden = true;
    box.replaceChildren(el('div', {class: 'empty-state'},
      el('h2', {}, 'No applications yet'),
      el('p', {}, 'Tick “I applied” on a daily page, or add one here. Each application keeps its job description, interviews and follow-ups.'),
      el('button', {type: 'button', class: 'btn primary', onclick: openAdd}, 'Add your first application')));
    return;
  }
  toolbar.hidden = false;
  const list = sorted(state.data.applications.filter(matches));
  if (state.view === 'board') return box.replaceChildren(renderBoard(list));
  if (!list.length) return box.replaceChildren(el('div', {class: 'empty-state'}, el('h2', {}, 'Nothing matches'), el('p', {}, 'Try a different search or filter.')));
  box.replaceChildren(el('div', {class: 'list'}, list.map(a => {
    const d = asDate(a.date);
    const meta = [a.location, a.salary].filter(Boolean).join('  ·  ');
    return el('button', {type: 'button', class: `card${a.final ? ' closed' : ''}`, style: stageColor(a.status), onclick: () => openApp(a.id)},
      el('span', {class: 'date'}, d ? MONTHS[d.getMonth()] : '', el('b', {}, d ? String(d.getDate()) : '?')),
      el('span', {},
        el('div', {class: 'co'}, a.company), el('div', {class: 'ro'}, a.role),
        meta && el('div', {class: 'me'}, meta)),
      el('span', {class: 'flags'},
        el('span', {class: 'pill'}, el('span', {class: 'dot'}), a.status), flagsFor(a)));
  })));
}

function renderBoard(list) {
  return el('div', {class: 'board'}, state.data.stages.map(stage => {
    const items = list.filter(a => a.status === stage);
    const col = el('div', {class: 'col', style: stageColor(stage),
      ondragover: e => { e.preventDefault(); col.classList.add('over'); },
      ondragleave: () => col.classList.remove('over'),
      ondrop: e => {
        e.preventDefault();
        col.classList.remove('over');
        const id = e.dataTransfer.getData('text/plain');
        if (id && app(id) && app(id).status !== stage) save(id, {status: stage}, `Moved to ${stage}`);
      }},
    el('h3', {}, el('span', {class: 'dot'}), stage, el('b', {}, String(items.length))),
    items.map(a => el('button', {type: 'button', class: 'tile', draggable: 'true', onclick: () => openApp(a.id),
      ondragstart: e => e.dataTransfer.setData('text/plain', a.id)},
    el('div', {class: 'co'}, a.company), el('div', {class: 'ro'}, a.role), flagsFor(a))));
    return col;
  }));
}

/* saving */
async function save(id, changes, message, redraw) {
  try {
    const fresh = await api('/api/tracker/update', {id, changes});
    await load();
    if (message !== null) toast(message || 'Saved');
    if (redraw && state.open === id) renderDrawer();
    return fresh;
  } catch (err) {
    toast(err.message, true);
    return null;
  }
}

/* detail drawer */
function openApp(id, tab) {
  const target = `#app/${encodeURIComponent(id)}${tab === 'jd' ? '/jd' : ''}`;
  if (location.hash === target) route(); else location.hash = target;
}
function closeApp() { history.pushState(null, '', location.pathname); route(); }

function route() {
  const m = location.hash.match(/^#app\/([^/]+)(\/jd)?$/);
  const id = m ? decodeURIComponent(m[1]) : null;
  const a = id && state.data && app(id);
  const wasOpen = state.open;
  state.open = a ? id : null;
  state.tab = m && m[2] ? 'jd' : 'details';
  $('drawer').hidden = $('scrim').hidden = !a;
  document.body.classList.toggle('locked', !!a);
  if (a) {
    renderDrawer();
    if (!wasOpen) $('drawer').querySelector('.close').focus();
  } else if (wasOpen) {
    const back = document.querySelector('#results button');
    if (back) back.focus();
  }
}

function field(label, key, a, opts = {}) {
  const input = el(opts.area ? 'textarea' : 'input', {
    value: a[key] || '', type: opts.type, rows: opts.rows, placeholder: opts.placeholder, autocomplete: 'off',
    onchange: e => save(a.id, {[key]: e.target.value}, undefined, opts.redraw)});
  if (opts.area) input.textContent = a[key] || '';
  return el('label', {class: opts.wide ? 'wide' : undefined}, label, input,
    opts.hint && el('small', {}, opts.hint));
}

function renderDrawer() {
  const a = app(state.open);
  if (!a) return;
  const scroll = $('drawer').scrollTop;
  const links = [a.links.posting && el('a', {href: a.links.posting, target: '_blank', rel: 'noopener noreferrer'}, 'Original posting'),
    a.links.cv && el('a', {href: a.links.cv, target: '_blank'}, 'CV sent'),
    a.links.cover && el('a', {href: a.links.cover, target: '_blank'}, 'Cover letter')].filter(Boolean);
  const head = el('div', {class: 'd-head'},
    el('div', {class: 'd-top'},
      el('div', {}, el('h2', {}, a.company), el('p', {class: 'd-role'}, a.role)),
      el('button', {type: 'button', class: 'icon-btn close', 'aria-label': 'Close', onclick: closeApp}, '✕')),
    el('div', {class: 'tabs', role: 'tablist'},
      el('button', {type: 'button', role: 'tab', 'aria-selected': String(state.tab === 'details'), onclick: () => openApp(a.id)}, 'Details'),
      el('button', {type: 'button', role: 'tab', 'aria-selected': String(state.tab === 'jd'), onclick: () => openApp(a.id, 'jd')},
        a.jd_saved ? 'Job description' : 'Job description (missing)')));
  const body = el('div', {class: 'd-body'});
  $('drawer').replaceChildren(head, body);
  if (state.tab === 'jd') renderJd(a, body); else renderDetails(a, body, links);
  $('drawer').scrollTop = scroll;
}

function renderDetails(a, body, links) {
  const stageNote = a.drafted ? 'Drafted, not sent yet: no follow-up runs until it is.'
    : a.raw_status.trim().toLowerCase() !== {applied: 'applied', interviewing: 'interview', 'offer received': 'offer', rejected: 'rejected', withdrawn: 'withdrawn'}[a.status]
      ? `Recorded in the CSV as “${a.raw_status || 'blank'}”.` : '';
  body.append(el('section', {class: 'sect'}, el('h3', {}, 'Status'),
    el('div', {class: 'stages'}, state.data.stages.map(s => el('button', {
      type: 'button', style: stageColor(s), 'aria-pressed': String(a.status === s),
      onclick: () => { if (a.status !== s) save(a.id, {status: s}, `Moved to ${s}`, true); }},
    el('span', {class: 'dot'}), s[0].toUpperCase() + s.slice(1)))),
    stageNote && el('p', {class: 'raw'}, stageNote),
    a.drafted && el('p', {class: 'raw'}, el('button', {type: 'button', class: 'btn', onclick: () => save(a.id, {sent: true}, 'Marked as sent today', true)}, 'I sent it today'))));

  body.append(renderFollowUp(a));
  body.append(renderInterviews(a));

  body.append(el('section', {class: 'sect'}, el('h3', {}, 'Application'),
    el('div', {class: 'grid'},
      field('Date applied', 'date', a, {type: 'date', redraw: true}),
      field('Recruiter or contact', 'contact', a),
      field('Location', 'location', a, {hint: a.location_from_posting ? 'From the saved posting. Type to replace.' : ''}),
      field('Salary', 'salary', a, {hint: a.salary_from_posting ? 'From the saved posting. Type to replace.' : ''}),
      field('Application deadline', 'deadline', a, {type: 'date'}),
      field('Posting link', 'source', a, {redraw: true})),
    a.fit && el('p', {class: 'raw'}, `Fit score ${a.fit}${a.channel ? ` · via ${a.channel}` : ''}`),
    links.length ? el('div', {class: 'links'}, links) : null));

  const notes = field('Recruiter, what was discussed, interview prep', 'notes', a, {area: true, rows: 7, wide: true,
    placeholder: 'Saved when you click away.'});
  body.append(el('section', {class: 'sect'}, el('h3', {}, 'Notes'), el('div', {class: 'grid'}, notes)));
  if (a.log) body.append(el('section', {class: 'sect'}, el('h3', {}, 'Tracker log'), el('p', {class: 'log'}, a.log)));
}

function renderFollowUp(a) {
  const f = a.follow_up;
  const box = el('section', {class: 'sect'}, el('h3', {}, 'Follow-up'));
  if (a.final || a.drafted) {
    box.append(el('p', {class: 'nil'}, a.final ? 'Closed, so nothing to chase.' : 'Nothing sent, so nobody is late replying.'));
    return box;
  }
  box.append(el('p', {class: `fu-state ${f.state}`},
    f.state === 'none' ? (f.sent >= 2 ? 'Two follow-ups sent. Time to decide, not chase again.' : 'No follow-up planned')
      : `${dueText(f)} · ${longDate(f.date)}`));
  box.append(el('div', {class: 'fu'},
    el('input', {type: 'date', value: f.date, 'aria-label': 'Follow-up date', onchange: e => save(a.id, {follow_up: e.target.value}, 'Follow-up moved', true)}),
    el('button', {type: 'button', class: 'btn', disabled: f.sent >= 2, onclick: async () => {
      try { await api('/api/tracker/followup', {id: a.id}); await load(); toast('Follow-up logged'); renderDrawer(); } catch (err) { toast(err.message, true); }
    }}, 'I sent a follow-up'),
    f.custom && el('button', {type: 'button', class: 'btn quiet', onclick: () => save(a.id, {follow_up: ''}, `Back to 7 days after applying`, true)}, 'Reset to default'),
    f.state !== 'none' && el('button', {type: 'button', class: 'btn quiet', onclick: () => save(a.id, {follow_up: 'none'}, 'Follow-up cleared', true)}, 'Not needed')));
  box.append(el('p', {class: 'raw'}, `${f.sent} of 2 follow-ups sent${f.default ? ` · default ${shortDate(f.default)}` : ''}`));
  return box;
}

function renderInterviews(a) {
  const box = el('section', {class: 'sect'}, el('h3', {}, 'Interviews'));
  const editing = {index: null};
  const formHost = el('div', {});
  const put = (list, message) => save(a.id, {interviews: list}, message, true);

  const showForm = (item, index) => {
    editing.index = index;
    const v = item || {date: '', time: '', format: 'video', with: '', notes: ''};
    const form = el('form', {class: 'iform', onsubmit: e => {
      e.preventDefault();
      const d = new FormData(form);
      const entry = {id: v.id, date: d.get('date'), time: d.get('time'), format: d.get('format'), with: d.get('with'), notes: d.get('notes')};
      const list = [...a.interviews];
      if (index === null) list.push(entry); else list[index] = entry;
      const moved = index === null && a.raw_status.trim().toLowerCase() === 'applied';
      put(list, moved ? 'Interview saved, status moved to interviewing' : 'Interview saved');
    }},
    el('label', {class: 'ifield'}, 'Date', el('input', {type: 'date', name: 'date', required: true, value: v.date})),
    el('label', {class: 'ifield'}, 'Time', el('input', {type: 'time', name: 'time', value: v.time})),
    el('label', {class: 'ifield'}, 'Format', el('select', {name: 'format'}, Object.entries(FORMAT_LABEL).map(([k, label]) => {
      const o = el('option', {value: k}, label); o.selected = k === v.format; return o;
    }))),
    el('label', {class: 'ifield wide'}, 'With whom', el('input', {name: 'with', value: v.with, autocomplete: 'off', placeholder: 'Name and role'})),
    el('label', {class: 'ifield wide'}, 'Notes', el('textarea', {name: 'notes', rows: 2}, v.notes)),
    el('div', {class: 'row-end wide'},
      el('button', {type: 'button', class: 'btn quiet', onclick: () => formHost.replaceChildren(addBtn)}, 'Cancel'),
      el('button', {type: 'submit', class: 'btn primary'}, 'Save interview')));
    formHost.replaceChildren(form);
    form.querySelector('input').focus();
  };
  const addBtn = el('button', {type: 'button', class: 'btn', onclick: () => showForm(null, null)}, 'Add interview');

  if (!a.interviews.length) box.append(el('p', {class: 'nil', style: 'margin-bottom:10px'}, 'None scheduled.'));
  a.interviews.forEach((i, n) => box.append(el('div', {class: `interview${i.date < state.data.today ? ' past' : ''}`},
    el('div', {class: 't'}, `${longDate(i.date)}${i.time ? `, ${clock(i.time)}` : ''}`),
    el('div', {class: 's'}, [FORMAT_LABEL[i.format], i.with && `with ${i.with}`].filter(Boolean).join(' '), i.notes ? `\n${i.notes}` : ''),
    el('div', {class: 'a'},
      el('button', {type: 'button', class: 'btn quiet', onclick: () => showForm(i, n)}, 'Edit'),
      el('button', {type: 'button', class: 'btn quiet', onclick: () => {
        if (confirm(`Remove the interview on ${longDate(i.date)}?`)) put(a.interviews.filter((_, x) => x !== n), 'Interview removed');
      }}, 'Remove')))));
  formHost.append(addBtn);
  box.append(formHost);
  return box;
}

async function renderJd(a, body) {
  if (!a.jd_saved) {
    const area = el('textarea', {rows: 14, placeholder: 'Paste the full job description here'});
    body.append(el('section', {class: 'sect'},
      el('div', {class: 'missing-box'}, 'No job description saved',
        el('span', {}, 'Nothing was found for this application, and it will not be reconstructed. Paste it if you still have it.')),
      area,
      el('div', {class: 'row-end', style: 'margin-top:10px'},
        a.links.posting && el('a', {class: 'btn', href: a.links.posting, target: '_blank', rel: 'noopener noreferrer'}, 'Try the original posting'),
        el('button', {type: 'button', class: 'btn primary', onclick: async () => {
          try {
            await api('/api/tracker/jd', {id: a.id, text: area.value});
            delete state.jd[a.id];
            await load();
            toast('Job description saved');
            renderDrawer();
          } catch (err) { toast(err.message, true); }
        }}, 'Save job description'))));
    return;
  }
  const holder = el('div', {class: 'jd'}, 'Loading...');
  const copy = el('button', {type: 'button', class: 'btn quiet', onclick: async () => {
    try { await navigator.clipboard.writeText(state.jd[a.id] || ''); toast('Copied'); } catch { toast('Could not copy', true); }
  }}, 'Copy');
  body.append(el('section', {class: 'sect'}, el('div', {class: 'jd-bar'}, 'Saved copy. It stays here after the posting is taken down.', copy), holder));
  try {
    if (state.jd[a.id] === undefined) state.jd[a.id] = (await api(`/api/tracker/jd?id=${encodeURIComponent(a.id)}`)).text;
    holder.replaceChildren(...formatJd(state.jd[a.id]));
  } catch (err) { holder.textContent = err.message; }
}

function formatJd(text) {
  const out = [];
  let list = null;
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    const bullet = line.match(/^(?:[-*•·]|\d+\.)\s+(.*)$/);
    if (bullet) {
      if (!list) { list = el('ul'); out.push(list); }
      list.append(el('li', {}, bullet[1]));
      continue;
    }
    if (!line) continue;
    list = null;
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    out.push(heading ? el('h4', {}, heading[1]) : el('p', {}, line));
  }
  return out;
}

/* add */
function openAdd() {
  const form = $('add-form');
  form.reset();
  form.date.value = state.data.today;
  syncFollow();
  $('add-error').hidden = true;
  $('add-dialog').showModal();
}

function syncFollow() {
  const form = $('add-form');
  const d = asDate(form.date.value);
  if (!d) { $('add-follow').textContent = ''; return; }
  d.setDate(d.getDate() + 7);
  const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  $('add-follow').textContent = `Leave empty for ${shortDate(iso)}, 7 days after applying`;
}

async function submitAdd(event) {
  event.preventDefault();
  const fields = Object.fromEntries(new FormData($('add-form')));
  try {
    const created = await api('/api/tracker/add', fields);
    $('add-dialog').close();
    await load();
    toast('Application saved');
    openApp(created.id);
  } catch (err) {
    $('add-error').textContent = err.message;
    $('add-error').hidden = false;
  }
}

/* theme */
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  const dark = theme ? theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  $('theme').textContent = dark ? '☀' : '☾';
}

function init() {
  applyTheme(stored.get('tracker-theme'));
  state.view = stored.get('tracker-view') === 'board' ? 'board' : 'list';
  $('theme').addEventListener('click', () => {
    const next = $('theme').textContent === '☀' ? 'light' : 'dark';
    stored.set('tracker-theme', next);
    applyTheme(next);
  });
  $('add').addEventListener('click', openAdd);
  $('add-cancel').addEventListener('click', () => $('add-dialog').close());
  $('add-form').addEventListener('submit', submitAdd);
  $('add-form').date.addEventListener('input', syncFollow);
  $('add-form').status.append(...['applied', 'interviewing', 'offer received', 'rejected', 'withdrawn'].map(s => el('option', {value: s}, s)));
  $('search').addEventListener('input', e => { state.q = e.target.value.trim(); renderResults(); });
  $('sort').addEventListener('change', e => { state.sort = e.target.value; renderResults(); });
  document.querySelectorAll('.switch button').forEach(b => b.addEventListener('click', () => {
    state.view = b.dataset.view;
    stored.set('tracker-view', state.view);
    renderChips();
    renderResults();
  }));
  $('scrim').addEventListener('click', closeApp);
  addEventListener('hashchange', route);
  addEventListener('popstate', route);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && state.open && !$('add-dialog').open) closeApp(); });
  load().then(ok => { if (ok) route(); });
}

init();
