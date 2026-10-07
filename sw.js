/* Only application files enter this cache. Orders stay in localStorage. */
'use strict';
const CACHE = 'xiaodan-app-v1.1.1';
const FILES = ['./index.html', './manifest.webmanifest', './icons/apple-touch-icon.png', './icons/icon-192.png', './icons/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(names => Promise.all(names.filter(name => name.startsWith('xiaodan-app-') && name !== CACHE).map(name => caches.delete(name)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !url.href.startsWith(self.registration.scope)) return;
  if (event.request.mode === 'navigate') {
    // Guides and download pages must not overwrite the offline application shell.
    const scopeURL = new URL(self.registration.scope);
    const indexURL = new URL('./index.html', scopeURL);
    if (url.pathname !== scopeURL.pathname && url.pathname !== indexURL.pathname) return;
    event.respondWith(fetch(event.request).then(response => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE).then(cache => cache.put(indexURL, copy)));
      }
      return response;
    }).catch(() => caches.match(new URL('./index.html', self.registration.scope))));
  } else {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
  }
});
