// Web Push in the browser: register the service worker, ask permission, subscribe, and tell the server.
import { api } from "./api";

export type PushSupport = "ok" | "unsupported" | "ios-install" | "denied";

function urlB64ToBytes(s: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function pushSupport(): PushSupport {
  if (typeof window === "undefined") return "unsupported";
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone = window.matchMedia?.("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
  if (ios && !standalone) return "ios-install"; // iOS only allows push for apps added to the Home Screen
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return "ok";
}

async function registration() {
  return (await navigator.serviceWorker.getRegistration("/")) ?? (await navigator.serviceWorker.register("/sw.js", { scope: "/" }));
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (pushSupport() !== "ok") return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

export async function enablePush(): Promise<number> {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked for this site. Allow them in the browser's site settings, then try again.");
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const { public_key } = await api.pushKey();
  let sub = await reg.pushManager.getSubscription();
  if (sub) {
    // a subscription made with another server key can't be reused
    const old = sub.options.applicationServerKey;
    const same = old && btoa(String.fromCharCode(...new Uint8Array(old))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "") === public_key;
    if (!same) {
      await sub.unsubscribe();
      sub = null;
    }
  }
  sub = sub ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64ToBytes(public_key) }));
  const j = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  return (await api.pushSubscribe(j.endpoint, j.keys)).devices;
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.pushUnsubscribe(sub.endpoint).catch(() => undefined);
  await sub.unsubscribe();
}
