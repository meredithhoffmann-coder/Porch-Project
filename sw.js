/* The Porch Project — service worker
 *
 * What this does, in plain words:
 *  - Pages, styles and scripts: always try the internet first, so neighbors see
 *    your latest listings and events. A saved copy is used ONLY when offline.
 *  - Photos and icons from porchproject.co: shown from the saved copy for speed,
 *    and quietly refreshed in the background.
 *  - Anything from other sites (Google Analytics, Google Sheets, Flodesk, fonts,
 *    business websites) is never touched — it goes straight to the internet.
 *
 * If you ever need to force every phone to drop its saved copies, bump VERSION.
 */
const VERSION = 'pp-v1';
const PAGE_CACHE = VERSION + '-pages';
const ASSET_CACHE = VERSION + '-assets';
const OFFLINE_URL = '/offline.html';

const PRECACHE = [
  OFFLINE_URL,
  '/styles.css',
  '/icons/icon-192.png',
  '/icons/apple-touch-icon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(ASSET_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;   // never touch other sites

  const isPage = req.mode === 'navigate' ||
    (req.headers.get('accept') || '').includes('text/html');
  const isCode = /\.(css|js|json|webmanifest|xml)$/i.test(url.pathname);

  if (isPage || isCode) {
    // Network first: pages, styles and scripts are always fresh when there's signal.
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(isPage ? PAGE_CACHE : ASSET_CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() =>
          caches.match(req).then((hit) => hit || (isPage ? caches.match(OFFLINE_URL) : Response.error()))
        )
    );
    return;
  }

  // Photos and icons: serve saved copy fast, refresh it in the background.
  event.respondWith(
    caches.open(ASSET_CACHE).then((cache) =>
      cache.match(req).then((hit) => {
        const refresh = fetch(req)
          .then((res) => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          })
          .catch(() => hit);
        return hit || refresh;
      })
    )
  );
});
