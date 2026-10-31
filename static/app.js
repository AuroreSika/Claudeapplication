const $ = s => document.querySelector(s);
const eur = c => (c / 100).toLocaleString('fr-FR', {style: 'currency', currency: 'EUR'});
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const dateFr = d => d.split('-').reverse().join('/');
let meta = {accounts: [], categories: []}, editing = null;

async function api(path, opts = {}) {
  const r = await fetch('/api/' + path, opts.body && typeof opts.body !== 'string'
    ? {...opts, body: JSON.stringify(opts.body), headers: {'Content-Type': 'application/json'}} : opts);
  const t = await r.text(); const data = t.startsWith('{') || t.startsWith('[') ? JSON.parse(t) : t;
  if (!r.ok) throw new Error(data.error || 'Erreur');
  return data;
}
const fail = e => { $('#err').textContent = e.message; };
const month = () => $('#month').value;

async function loadMeta() {
  meta = await api('meta');
  const f = $('#form');
  f.category_id.innerHTML = '<option value="">Sans catégorie</option>' +
    meta.categories.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
  const sel = f.account_id.value;
  f.account_id.innerHTML = meta.accounts.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
  if (sel) f.account_id.value = sel;
}

async function refresh() {
  $('#err').textContent = '';
  const m = month(), s = $('#search').value;
  const [d, tx] = await Promise.all([api('dashboard?month=' + m),
    api('transactions?month=' + m + (s ? '&search=' + encodeURIComponent(s) : ''))]);
  $('#solde').textContent = eur(d.total_balance_cents);
  $('#rec').textContent = eur(d.recettes_cents);
  $('#dep').textContent = eur(d.depenses_cents);
  $('#res').textContent = eur(d.resultat_cents);
  $('#res').className = 'big ' + (d.resultat_cents >= 0 ? 'ok' : 'ko');
  const max = Math.max(1, ...d.by_category.map(c => c.cents));
  $('#cats').innerHTML = d.by_category.map(c => `<div class="row" style="justify-content:space-between">
    <span>${esc(c.category)}</span><span class="${c.kind === 'recette' ? 'ok' : 'ko'}">${eur(c.cents)}</span></div>
    <div class="bar" style="width:${c.cents / max * 100}%;background:var(${c.kind === 'recette' ? '--ok' : '--ko'})"></div>`).join('')
    || '<span class="lbl">Aucune opération ce mois-ci.</span>';
  $('#tx').innerHTML = tx.map(t => `<tr>
    <td>${dateFr(t.date)}</td><td>${esc(t.label)}${t.note ? `<div class="lbl">${esc(t.note)}</div>` : ''}</td>
    <td>${esc(t.category || '—')}</td><td>${esc(t.account)}</td>
    <td class="n ${t.kind === 'recette' ? 'ok' : 'ko'}">${t.kind === 'recette' ? '+' : '−'}${eur(t.amount_cents)}</td>
    <td class="n"><button class="x" data-edit="${t.id}" title="Modifier" style="color:var(--acc)">✎</button>
    <button class="x" data-del="${t.id}" title="Supprimer">✕</button></td></tr>`).join('')
    || '<tr><td colspan="6" class="lbl">Rien à afficher.</td></tr>';
  $('#tx').onclick = async e => {
    const del = e.target.dataset.del, ed = e.target.dataset.edit;
    if (del && confirm('Supprimer cette opération ?')) { await api('transactions/' + del, {method: 'DELETE'}); refresh(); }
    if (ed) startEdit(tx.find(t => t.id == ed));
  };
  $('#export').href = '/api/export?month=' + m;
}

function startEdit(t) {
  editing = t.id; const f = $('#form');
  f.date.value = t.date; f.label.value = t.label; f.amount.value = (t.amount_cents / 100).toFixed(2).replace('.', ',');
  f.kind.value = t.kind; f.category_id.value = t.category_id ?? ''; f.account_id.value = t.account_id; f.note.value = t.note;
  $('#formTitle').textContent = 'Modifier l’opération'; $('#cancel').hidden = false; f.label.focus();
}
function resetForm() {
  editing = null; const f = $('#form'), keep = {k: f.kind.value, a: f.account_id.value};
  f.reset(); f.kind.value = keep.k; f.account_id.value = keep.a; f.date.valueAsDate = new Date();
  $('#formTitle').textContent = 'Nouvelle opération'; $('#cancel').hidden = true;
}

$('#form').onsubmit = async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    await api('transactions' + (editing ? '/' + editing : ''), {method: editing ? 'PUT' : 'POST', body});
    resetForm(); await refresh();
  } catch (err) { fail(err); }
};
$('#cancel').onclick = resetForm;
$('#month').onchange = refresh;
$('#search').oninput = refresh;
$('#addAcc').onclick = async () => {
  try { await api('accounts', {method: 'POST', body: {name: $('#newAcc').value, opening: $('#newAccBal').value}});
    $('#newAcc').value = $('#newAccBal').value = ''; await loadMeta(); refresh(); } catch (e) { fail(e); }
};
$('#addCat').onclick = async () => {
  try { await api('categories', {method: 'POST', body: {name: $('#newCat').value, kind: $('#newCatKind').value}});
    $('#newCat').value = ''; await loadMeta(); } catch (e) { fail(e); }
};
$('#importBtn').onclick = () => $('#importFile').click();
$('#importFile').onchange = async e => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const r = await api('import?account_id=' + $('#form').account_id.value, {method: 'POST', body: await file.text()});
    alert(r.imported + ' opération(s) importée(s)'); refresh();
  } catch (err) { fail(err); }
  e.target.value = '';
};

(async () => {
  $('#month').value = new Date().toISOString().slice(0, 7);
  $('#form').date.valueAsDate = new Date();
  await loadMeta(); refresh().catch(fail);
})();
