// Service worker for the installable app. Rendered by apps/core/views.py.
//
// It deliberately caches almost nothing: only the offline page and the files
// it needs. Pages, balances and bookings always come from the network, so no
// personal data is ever stored on the phone by this worker.
"use strict";

var CACHE = "dorm-laundry-offline-{{ version }}";
var PRECACHE = {{ precache|safe }};
var OFFLINE_URL = {{ offline_url|safe }};

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // credentials "omit": the offline page is fetched without the login cookie.
      return Promise.all(
        PRECACHE.map(function (url) {
          return fetch(url, { credentials: "omit" }).then(function (response) {
            return cache.put(url, response);
          });
        })
      );
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) { return key !== CACHE; })
            .map(function (key) { return caches.delete(key); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.mode === "navigate") {
    // A page: always from the network; the offline page only if that fails.
    event.respondWith(
      fetch(request).catch(function () { return caches.match(OFFLINE_URL); })
    );
    return;
  }
  if (PRECACHE.indexOf(new URL(request.url).pathname) !== -1) {
    // The offline page's own CSS and icon, so it looks right without a connection.
    event.respondWith(
      fetch(request).catch(function () { return caches.match(new URL(request.url).pathname); })
    );
  }
  // Everything else is left to the browser: not cached here.
});
