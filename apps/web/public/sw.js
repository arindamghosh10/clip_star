/* clip_star service worker: shows push notifications and opens the right page when one is tapped.
   It caches nothing, so the app is always current. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let msg = { title: "clip_star", body: "", url: "/" };
  try {
    msg = { ...msg, ...event.data.json() };
  } catch (e) {
    if (event.data) msg.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(msg.title, {
      body: msg.workspace ? `${msg.body}${msg.body ? "\n" : ""}${msg.workspace}` : msg.body,
      tag: msg.tag || undefined,
      icon: "/icon-192.png",
      badge: "/badge-96.png",
      data: { url: msg.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const w of wins) {
        if (new URL(w.url).origin === self.location.origin && "focus" in w) {
          await w.focus();
          return w.navigate(url);
        }
      }
      return self.clients.openWindow(url);
    })(),
  );
});
