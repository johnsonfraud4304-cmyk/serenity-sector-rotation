const CACHE_NAME = 'sector-v1';
const ASSETS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', e => e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS))));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))));
self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request));
  } else {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
