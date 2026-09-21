// Trailer Docs service worker -- offline shell for the hosted copy.
// The cache name carries the build version, so publishing a new version
// installs a fresh cache and drops the old one.
const CACHE = 'trailer-docs-1.2.0';
const ASSETS = ['./', './index.html', './manifest.webmanifest',
                './icon-180.png', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Cache first: on set there is often a weak signal, and waiting on the network
// is worse than serving the copy we already have. A background fetch refreshes
// the cache for next launch.
self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;
  e.respondWith(
    caches.match(req, {ignoreSearch: true}).then(hit => {
      const net = fetch(req).then(res => {
        if(res && res.ok && new URL(req.url).origin === self.location.origin){
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => null);
      if(hit) return hit;
      return net.then(res => res || (req.mode === 'navigate'
        ? caches.match('./index.html') : Response.error()));
    })
  );
});
