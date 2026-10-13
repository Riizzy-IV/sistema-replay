const { SUPABASE_URL, SUPABASE_ANON_KEY, BUCKET } = window.CONFIG;
// Sem Supabase configurado, o app lê os replays direto do PC da quadra (modo local).
const LOCAL = !SUPABASE_URL || SUPABASE_URL.includes('SEU-PROJETO');
const sb = LOCAL ? null : supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const $ = (id) => document.getElementById(id);
const lista = $('lista'), vazio = $('vazio'), aviso = $('aviso');
const player = $('player'), video = $('video');

let dia = inicioDoDia(new Date());
let replays = []; // [{ replay_id, created_at, clipes: [linha, ...] }]
let atual = null, cameraAtual = 0;

function inicioDoDia(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function mesmoDia(a, b) { return inicioDoDia(a).getTime() === inicioDoDia(b).getTime(); }
function urlPublica(path, download) {
  if (LOCAL) return `/midia/${path}`;
  return sb.storage.from(BUCKET).getPublicUrl(path, download ? { download } : undefined).data.publicUrl;
}
const hora = (iso) => new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

function agrupar(linhas) {
  const grupos = new Map();
  for (const l of linhas) {
    if (!grupos.has(l.replay_id)) grupos.set(l.replay_id, { replay_id: l.replay_id, created_at: l.created_at, clipes: [] });
    grupos.get(l.replay_id).clipes.push(l);
  }
  for (const g of grupos.values()) g.clipes.sort((a, b) => a.camera.localeCompare(b.camera));
  return [...grupos.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

async function carregar() {
  const fim = new Date(dia); fim.setDate(fim.getDate() + 1);
  atualizarCabecalhoDia();
  aviso.hidden = true;
  const { data, error } = LOCAL
    ? await fetch(`/api/replays?de=${dia.toISOString()}&ate=${fim.toISOString()}`)
      .then(async (r) => ({ data: await r.json(), error: !r.ok }), () => ({ error: true }))
    : await sb.from('replays').select('*')
      .gte('created_at', dia.toISOString()).lt('created_at', fim.toISOString())
      .order('created_at', { ascending: false });
  if (error) { aviso.textContent = 'Não foi possível carregar os replays. Verifique sua internet.'; aviso.hidden = false; return; }
  replays = agrupar(data);
  renderizar();
}

function renderizar() {
  lista.replaceChildren();
  vazio.hidden = replays.length > 0;
  for (const r of replays) {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'card';
    const thumb = r.clipes.find((c) => c.thumb_path);
    if (thumb) {
      const img = document.createElement('img');
      img.src = urlPublica(thumb.thumb_path); img.alt = ''; img.loading = 'lazy';
      btn.append(img);
    }
    const info = document.createElement('div');
    info.className = 'card-info';
    const t = document.createElement('strong'); t.textContent = hora(r.created_at);
    const d = document.createElement('span');
    d.textContent = `${r.clipes[0].duracao}s` + (r.clipes.length > 1 ? ` · ${r.clipes.length} câmeras` : '');
    info.append(t, d);
    const play = document.createElement('span'); play.className = 'play'; play.textContent = '▶';
    btn.append(info, play);
    btn.onclick = () => abrir(r);
    li.append(btn);
    lista.append(li);
  }
}

function abrir(r) {
  atual = r; cameraAtual = 0;
  $('player-titulo').textContent = `Replay das ${hora(r.created_at)}`;
  const abas = $('cameras');
  abas.replaceChildren();
  abas.hidden = r.clipes.length < 2;
  r.clipes.forEach((c, i) => {
    const b = document.createElement('button');
    b.role = 'tab'; b.textContent = c.camera_nome || c.camera;
    b.onclick = () => trocarCamera(i);
    abas.append(b);
  });
  trocarCamera(0);
  player.showModal();
  video.play().catch(() => {});
}

function trocarCamera(i) {
  cameraAtual = i;
  const c = atual.clipes[i];
  [...$('cameras').children].forEach((b, j) => b.setAttribute('aria-selected', String(i === j)));
  video.src = urlPublica(c.video_path);
  $('baixar').href = urlPublica(c.video_path, `el-mare-${c.id}.mp4`);
  $('baixar').download = `el-mare-${c.id}.mp4`;
}

$('fechar').onclick = () => player.close();
player.addEventListener('close', () => { video.pause(); video.removeAttribute('src'); video.load(); });

$('compartilhar').onclick = async () => {
  const c = atual.clipes[cameraAtual];
  const url = urlPublica(c.video_path);
  try {
    if (navigator.share) await navigator.share({ title: 'Meu replay na El Mare', url });
    else { await navigator.clipboard.writeText(url); toast('Link copiado!'); }
  } catch (_) { /* usuário cancelou */ }
};

function atualizarCabecalhoDia() {
  const hoje = inicioDoDia(new Date());
  const ontem = new Date(hoje); ontem.setDate(ontem.getDate() - 1);
  $('dia-texto').textContent = mesmoDia(dia, hoje) ? 'Hoje' : mesmoDia(dia, ontem) ? 'Ontem'
    : dia.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' });
  $('dia-proximo').disabled = mesmoDia(dia, hoje);
  const iso = `${dia.getFullYear()}-${String(dia.getMonth() + 1).padStart(2, '0')}-${String(dia.getDate()).padStart(2, '0')}`;
  $('dia-input').value = iso;
  $('dia-input').max = new Date(hoje.getTime() - hoje.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function mudarDia(delta) { dia.setDate(dia.getDate() + delta); dia = inicioDoDia(dia); carregar(); }
$('dia-anterior').onclick = () => mudarDia(-1);
$('dia-proximo').onclick = () => mudarDia(1);
$('dia-input').onchange = (e) => {
  if (!e.target.value) return;
  const [a, m, d] = e.target.value.split('-').map(Number);
  dia = new Date(a, m - 1, d); carregar();
};

let timerToast;
function toast(texto) {
  const t = $('toast'); t.textContent = texto; t.hidden = false;
  clearTimeout(timerToast); timerToast = setTimeout(() => { t.hidden = true; }, 3000);
}

// Novos replays aparecem sozinhos
function chegou(linha) {
  if (!mesmoDia(new Date(linha.created_at), dia)) return;
  const todas = replays.flatMap((r) => r.clipes).filter((c) => c.id !== linha.id);
  const novo = !todas.some((c) => c.replay_id === linha.replay_id);
  replays = agrupar([...todas, linha]);
  renderizar();
  if (novo) toast('Novo replay chegou!');
}

if (LOCAL) {
  $('ao-vivo').hidden = false;
  setInterval(async () => {
    if (document.hidden || !mesmoDia(dia, new Date())) return;
    const fim = new Date(dia); fim.setDate(fim.getDate() + 1);
    try {
      const linhas = await (await fetch(`/api/replays?de=${dia.toISOString()}&ate=${fim.toISOString()}`)).json();
      const conhecidos = new Set(replays.flatMap((r) => r.clipes).map((c) => c.id));
      linhas.filter((l) => !conhecidos.has(l.id)).forEach(chegou);
    } catch (_) { /* PC fora do ar; tenta de novo */ }
  }, 3000);
} else {
  sb.channel('replays')
    .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'replays' }, ({ new: linha }) => chegou(linha))
    .subscribe((estado) => { $('ao-vivo').hidden = estado !== 'SUBSCRIBED'; });
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) carregar(); });

if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');
carregar();
