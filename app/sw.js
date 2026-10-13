// Guarda só a "casca" do app para abrir rápido; vídeos e dados sempre vêm da rede.
const CACHE = 'elmare-v2';
const CASCA = ['./', 'index.html', 'style.css', 'app.js', 'config.js', 'logo-texto.png', 'icon-192.png', 'manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CASCA)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((chaves) => Promise.all(chaves.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  const casca = CASCA.map((p) => new URL(p, self.registration.scope).href);
  if (e.request.method !== 'GET' || !casca.includes(url.origin + url.pathname)) return;
  // rede primeiro (pega atualizações), cache se estiver offline
  e.respondWith(
    fetch(e.request)
      .then((r) => { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request)),
  );
});
