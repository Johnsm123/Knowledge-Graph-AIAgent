import { useEffect, useRef } from "react";
import { io } from "socket.io-client";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "https://cognizant-care-api.azurewebsites.net";

let socketInstance = null;

function getSocket() {
  if (!socketInstance) {
    socketInstance = io(API_BASE, {
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionDelay: 1500,
    });
    socketInstance.on("connect", () => {
      socketInstance.emit("join_portal");
    });
  }
  return socketInstance;
}

export function useRealtimeEvents(handlers) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const socket = getSocket();
    const bound = {};
    for (const event of Object.keys(handlersRef.current || {})) {
      bound[event] = (payload) => {
        const fn = handlersRef.current[event];
        if (typeof fn === "function") fn(payload);
      };
      socket.on(event, bound[event]);
    }
    return () => {
      for (const [event, fn] of Object.entries(bound)) {
        socket.off(event, fn);
      }
    };
  }, []);
}
