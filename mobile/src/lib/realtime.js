import { io } from "socket.io-client";
import Constants from "expo-constants";

const API_BASE = Constants.expoConfig?.extra?.apiBaseUrl || "https://cognizant-care-api.azurewebsites.net";

let socket = null;
const listeners = new Set();   // every subscriber receives every event

function ensureSocket() {
  if (socket) return socket;
  socket = io(API_BASE, {
    transports: ["websocket", "polling"],
    reconnection: true,
    reconnectionDelay: 2000,
  });

  socket.on("connect",    () => console.log("[realtime] connected"));
  socket.on("disconnect", () => console.log("[realtime] disconnected"));

  // Fan out server events to all local subscribers
  ["appointment_booked", "care_gap_updated", "profile_updated"].forEach((name) => {
    socket.on(name, (payload) => {
      listeners.forEach((fn) => {
        try { fn(name, payload); } catch (_) {}
      });
    });
  });

  return socket;
}

/** Subscribe to server-pushed events. Returns an unsubscribe function. */
export function subscribeRealtime(handler) {
  ensureSocket();
  listeners.add(handler);
  return () => listeners.delete(handler);
}

export function disconnectRealtime() {
  if (socket) {
    socket.disconnect();
    socket = null;
    listeners.clear();
  }
}
