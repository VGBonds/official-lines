// Search over propositions (with the stances taken on them) and claims. The index is
// search.json, built with the site; matching happens here, deterministically: every query
// word must occur, short words exactly, longer words as the start of a word. No ranking by
// relevance: propositions before claims, contested first, then newest first.
(function () {
  const $ = id => document.getElementById(id);
  const q = $('q'), stanceSel = $('stance'), status = $('status');
  const SYMBOL = { asserts: '●', qualifies: '◐', denies: '○' };
  const STOP = new Set(('a an the of on in to for is are was were be been who what which whom whose ' +
    'against with and or about by from at as does do did that this it its their his her they them ' +
    'calling call calls called more less than says say said support supports opposes oppose ' +
    'favour favor backs back wants want').split(' '));
  const MAX_CLAIMS = 100;
  let index = null, loading = null;

  function tokens(text) {
    return (text || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .split(/[^a-z0-9]+/).filter(t => t.length > 1);
  }
  function stem(t) {  // light: drop a plural or verb ending so "sanction" finds "sanctions"
    for (const end of ['ing', 'ed', 'es', 's']) {
      if (t.length > end.length + 3 && t.endsWith(end)) return t.slice(0, -end.length);
    }
    return t;
  }
  function queryTerms(text) {
    return [...new Set(tokens(text).filter(t => !STOP.has(t)).map(stem))];
  }
  function cmpDate(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function matches(terms, words) {  // short terms exactly; longer ones on a shared stem
    return terms.every(term => words.some(w => term.length <= 3 ? w === term
      : w.startsWith(term) || (w.length >= 5 && term.startsWith(w))));
  }
  function words(item) {
    if (!item._w) {
      const text = item.p !== undefined
        ? item.p + ' ' + item.stances.map(s => s.q).join(' ')
        : item.c + ' ' + item.x + ' ' + index.events[item.e].t;
      item._w = tokens(text).map(stem);
    }
    return item._w;
  }

  function load() {
    if (index || loading) return loading;
    status.textContent = 'Loading the index…';
    loading = fetch('search.json').then(r => r.json()).then(data => { index = data; apply(); })
      .catch(() => { status.textContent = 'The search index could not be loaded.'; });
    return loading;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function eventLink(item) {
    const a = el('a', null, index.events[item.e].t);
    a.href = 'event/' + item.e + '.html';
    return a;
  }

  function renderProp(item, stance) {
    const li = el('li', 'hit');
    const p = el('p', 'prop', item.p + ' ');
    if (item.l) p.appendChild(el('span', 'badge', item.l));
    li.appendChild(p);
    const meta = el('p', 'muted small');
    meta.appendChild(eventLink(item));
    meta.appendChild(document.createTextNode(' · ' + index.events[item.e].d));
    li.appendChild(meta);
    const ul = el('ul', 'stances');
    item.stances.filter(s => !stance || s.s === stance).forEach(s => {
      const row = el('li');
      row.appendChild(el('span', 'sym', SYMBOL[s.s] + ' '));
      row.appendChild(el('strong', null, s.n));
      row.appendChild(document.createTextNode(' ' + s.s + (s.q ? ': “' + s.q + '”' : '')));
      ul.appendChild(row);
    });
    li.appendChild(ul);
    return li;
  }
  function renderClaim(item) {  // item.names: every actor that made this claim in this event
    const li = el('li', 'hit claim');
    const p = el('p');
    p.appendChild(el('strong', null, item.names.join(', ')));
    p.appendChild(document.createTextNode(' (' + item.sd + '): ' + item.c + ' — '));
    p.appendChild(eventLink(item));
    li.appendChild(p);
    return li;
  }

  function apply() {
    const terms = queryTerms(q.value), stance = stanceSel.value;
    const url = new URL(location.href);
    if (q.value.trim()) url.searchParams.set('q', q.value.trim()); else url.searchParams.delete('q');
    if (stance) url.searchParams.set('stance', stance); else url.searchParams.delete('stance');
    history.replaceState(null, '', url);
    if (!terms.length) {
      $('props-section').hidden = $('claims-section').hidden = true;
      if (index) status.textContent = 'Type at least one word that is not a stance word.';
      return;
    }
    if (!index) { load(); return; }
    const rank = { contested: 0, 'shared floor': 1, 'uncontested majority': 1, '': 2 };
    const props = index.props
      .filter(p => matches(terms, words(p)) && (!stance || p.stances.some(s => s.s === stance)))
      .sort((a, b) => rank[a.l] - rank[b.l] || cmpDate(index.events[b.e].d, index.events[a.e].d));
    const byText = new Map();  // the same claim by several actors (a joint text) is one line
    if (!stance) index.claims.filter(c => matches(terms, words(c))).forEach(c => {
      const key = c.e + '\n' + c.c, hit = byText.get(key);
      if (hit) { hit.names.push(c.n); if (c.sd > hit.sd) hit.sd = c.sd; }
      else byText.set(key, { ...c, names: [c.n] });
    });
    const claims = [...byText.values()].sort((a, b) => cmpDate(b.sd, a.sd));

    const pl = $('props'), cl = $('claims');
    pl.replaceChildren(...props.map(p => renderProp(p, stance)));
    cl.replaceChildren(...claims.slice(0, MAX_CLAIMS).map(renderClaim));
    $('props-section').hidden = !props.length;
    $('claims-section').hidden = !claims.length;
    status.textContent = 'Matching: ' + terms.join(', ') + '. ' + props.length + ' proposition'
      + (props.length === 1 ? '' : 's') + (stance ? ' with a stance of "' + stance + '"' : '')
      + (stance ? '. Claims are not shown with a stance filter, as a claim records no stance.' :
        ', ' + claims.length + ' claim' + (claims.length === 1 ? '' : 's')
        + (claims.length > MAX_CLAIMS ? ' (newest ' + MAX_CLAIMS + ' shown)' : '') + '.');
  }

  const params = new URL(location.href).searchParams;
  q.value = params.get('q') || '';
  stanceSel.value = params.get('stance') || '';
  q.addEventListener('input', apply);
  stanceSel.addEventListener('input', apply);
  q.addEventListener('focus', load, { once: true });
  if (q.value) load();
})();
