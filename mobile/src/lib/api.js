import * as SecureStore from "expo-secure-store";
import Constants from "expo-constants";

const API_BASE = Constants.expoConfig?.extra?.apiBaseUrl || "http://10.0.2.2:5000";
const TOKEN_KEY = "cogcare.jwt";
const MEMBER_KEY = "cogcare.member_id";

export async function saveSession(memberId, token) {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
  await SecureStore.setItemAsync(MEMBER_KEY, memberId);
}

export async function getSession() {
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  const memberId = await SecureStore.getItemAsync(MEMBER_KEY);
  return token ? { token, memberId } : null;
}

export async function clearSession() {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  await SecureStore.deleteItemAsync(MEMBER_KEY);
}

async function authHeaders() {
  const session = await getSession();
  if (!session) throw new Error("Not authenticated");
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.token}`,
  };
}

export async function requestOtp(memberId) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/activate/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

export async function verifyOtp(memberId, otp) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/activate/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId, otp }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "OTP verification failed");
  await saveSession(data.member_id, data.token);
  return data;
}

export async function getMe() {
  const res = await fetch(`${API_BASE}/api/v1/mobile/member/me`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Fetch failed");
  return res.json();
}

export async function listAppointments() {
  const res = await fetch(`${API_BASE}/api/v1/mobile/appointments`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Fetch failed");
  return res.json();
}

export async function cancelAppointment(appointmentId) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/appointments/${encodeURIComponent(appointmentId)}/cancel`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Cancel failed");
  return data;
}

export async function bookAppointment(payload) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/appointments`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Booking failed");
  return data;
}

export async function sendChat(message, userLocation) {
  const body = { message };
  if (userLocation?.lat && userLocation?.lng) body.user_location = userLocation;
  const res = await fetch(`${API_BASE}/api/v1/mobile/chat`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Chat failed");
  return { reply: data.reply, attachment: data.attachment || null };
}

export async function listAvailableSlots() {
  const res = await fetch(`${API_BASE}/api/v1/mobile/slots`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Slots fetch failed");
  return res.json();
}

export async function findNearbyLabs({ lat, lng, measureId, radius = 25000 }) {
  const qs = new URLSearchParams({
    lat: String(lat),
    lng: String(lng),
    measure_id: measureId || "",
    radius: String(radius),
  });
  const res = await fetch(`${API_BASE}/api/v1/mobile/labs/nearby?${qs}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error("Nearby labs failed");
  return res.json();
}

export async function updateProfile(updates) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/member/me`, {
    method: "PATCH",
    headers: await authHeaders(),
    body: JSON.stringify(updates),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Profile update failed");
  return data;
}

export async function registerPushToken(fcmToken) {
  const res = await fetch(`${API_BASE}/api/v1/mobile/push/register`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify({ fcm_token: fcmToken }),
  });
  return res.ok;
}

export async function resetChat() {
  try {
    await fetch(`${API_BASE}/api/v1/mobile/chat/reset`, {
      method: "POST",
      headers: await authHeaders(),
    });
  } catch (_) {}
}

export async function fetchProactiveMessages() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/mobile/chat/proactive`, {
      headers: await authHeaders(),
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.messages || [];
  } catch (_) {
    return [];
  }
}
