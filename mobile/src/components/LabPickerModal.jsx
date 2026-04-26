import { useEffect, useState } from "react";
import {
  Modal, View, Text, TouchableOpacity, ScrollView, ActivityIndicator,
  StyleSheet, Linking, Alert,
} from "react-native";
import { WebView } from "react-native-webview";
import * as Location from "expo-location";
import { findNearbyLabs } from "../lib/api";
import { COG, S } from "../lib/brand";

const RADIUS_M = 25000;  // 25 km — per user spec

/**
 * Lab picker for the manual booking flow.
 *
 * Renders an interactive Leaflet map (via WebView, no native module / no
 * Google Maps API key in the client) with all returned labs as numbered pins,
 * plus a scrollable list of cards below. Selecting a lab — either by tapping
 * a pin in the WebView (postMessage'd back to RN) or tapping a card — locks
 * in the choice and the parent's "Confirm" button becomes active.
 */
export default function LabPickerModal({ visible, measureId, onClose, onPicked }) {
  const [phase, setPhase]         = useState("loading");   // loading | ready | error
  const [labs, setLabs]           = useState([]);
  const [userLoc, setUserLoc]     = useState(null);
  const [selectedId, setSelected] = useState(null);
  const [errMsg, setErrMsg]       = useState("");

  useEffect(() => {
    if (!visible) return;
    setPhase("loading"); setLabs([]); setSelected(null); setErrMsg("");

    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") {
          setErrMsg("Location permission is required to find nearby labs.");
          setPhase("error");
          return;
        }
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setUserLoc(here);

        const res = await findNearbyLabs({
          lat: here.lat, lng: here.lng, measureId, radius: RADIUS_M,
        });
        const items = (res.results || []).filter(l => l.lat && l.lng);
        setLabs(items);
        setPhase(items.length === 0 ? "error" : "ready");
        if (items.length === 0) {
          setErrMsg("No labs found within 25 km. Try the chat assistant for a wider search.");
        }
      } catch (e) {
        setErrMsg(e.message || "Could not load nearby labs.");
        setPhase("error");
      }
    })();
  }, [visible, measureId]);

  const handleConfirm = () => {
    const lab = labs.find(l => l.place_id === selectedId);
    if (!lab) { Alert.alert("Pick a lab", "Tap a lab from the list or map."); return; }
    onPicked?.(lab);
  };

  // Build the Leaflet HTML once labs are loaded.
  const html = userLoc && labs.length
    ? buildLeafletHtml(userLoc, labs, selectedId)
    : null;

  // Selecting from WebView marker click
  const handleWebMessage = (e) => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === "selectLab" && m.place_id) setSelected(m.place_id);
    } catch (_) {}
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent={false}>
      <View style={styles.root}>
        <View style={styles.header}>
          <Text style={styles.title}>Pick a nearby lab</Text>
          <TouchableOpacity onPress={onClose}><Text style={styles.close}>✕</Text></TouchableOpacity>
        </View>

        {phase === "loading" && (
          <View style={styles.center}>
            <ActivityIndicator size="large" color={COG.primary} />
            <Text style={styles.hint}>Finding labs within 25 km of your location…</Text>
          </View>
        )}

        {phase === "error" && (
          <View style={styles.center}>
            <Text style={styles.errTitle}>Couldn't load labs</Text>
            <Text style={styles.hint}>{errMsg}</Text>
            <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
              <Text style={styles.closeBtnText}>Close</Text>
            </TouchableOpacity>
          </View>
        )}

        {phase === "ready" && (
          <>
            {html ? (
              <View style={styles.mapWrap}>
                <WebView
                  originWhitelist={["*"]}
                  source={{ html }}
                  style={styles.webview}
                  javaScriptEnabled
                  domStorageEnabled
                  onMessage={handleWebMessage}
                  // CRITICAL: setSupportMultipleWindows + onShouldStartLoad
                  // prevent embedded links from trying to launch native intents
                  // that aren't registered (avoids any chance of a force-close).
                  setSupportMultipleWindows={false}
                  onShouldStartLoadWithRequest={(req) => req.url.startsWith("data:") || req.url.startsWith("about:") || req.url.startsWith("https://")}
                />
              </View>
            ) : null}

            <ScrollView style={styles.list} contentContainerStyle={{ paddingBottom: 100 }}>
              <Text style={styles.listHdr}>{labs.length} labs found</Text>
              {labs.map((l, i) => {
                const sel = selectedId === l.place_id;
                return (
                  <TouchableOpacity
                    key={l.place_id}
                    style={[styles.card, sel && styles.cardActive]}
                    onPress={() => setSelected(l.place_id)}
                  >
                    <View style={styles.numBubble}><Text style={styles.numText}>{i + 1}</Text></View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.labName}>{l.name}</Text>
                      <Text style={styles.labAddr} numberOfLines={2}>{l.address || ""}</Text>
                      <View style={styles.metaRow}>
                        {l.rating != null && (
                          <Text style={styles.rating}>★ {Number(l.rating).toFixed(1)}</Text>
                        )}
                        {l.open_now === true  && <Text style={styles.openTag}>Open now</Text>}
                        {l.open_now === false && <Text style={styles.closedTag}>Closed</Text>}
                        <TouchableOpacity onPress={() => {
                          Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${l.lat},${l.lng}`);
                        }}>
                          <Text style={styles.dirLink}>Directions →</Text>
                        </TouchableOpacity>
                      </View>
                    </View>
                    {sel && <Text style={styles.checkMark}>✓</Text>}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <View style={styles.footer}>
              <TouchableOpacity
                style={[styles.confirmBtn, !selectedId && { opacity: 0.4 }]}
                disabled={!selectedId}
                onPress={handleConfirm}
              >
                <Text style={styles.confirmText}>
                  {selectedId
                    ? `Confirm: ${labs.find(l => l.place_id === selectedId)?.name?.slice(0, 30) || "this lab"}`
                    : "Tap a lab to continue"}
                </Text>
              </TouchableOpacity>
            </View>
          </>
        )}
      </View>
    </Modal>
  );
}

// ─── Leaflet HTML builder ─────────────────────────────────────────────────────

function buildLeafletHtml(user, labs, activeId) {
  const labsJson = JSON.stringify(labs.map((l, i) => ({
    place_id: l.place_id,
    name:     l.name,
    address:  l.address || "",
    rating:   l.rating,
    lat:      l.lat,
    lng:      l.lng,
    idx:      i + 1,
  })));
  const activeIdJson = JSON.stringify(activeId || "");

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map { margin:0; padding:0; height:100%; width:100%; background:#f7f7f5; }
    .num-pin {
      width: 32px; height: 32px; border-radius: 50%;
      background: #000048; color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 14px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.35);
      border: 2px solid #fff;
    }
    .num-pin.active { background: #2F78C4; transform: scale(1.18); }
    .me-pin {
      width: 18px; height: 18px; border-radius: 50%;
      background: #26EFE9; border: 3px solid #000048;
      box-shadow: 0 0 0 4px rgba(38,239,233,0.35);
    }
    .leaflet-popup-content { font: 13px/1.3 -apple-system,Segoe UI,Roboto,sans-serif; min-width: 180px; }
    .leaflet-popup-content b { color: #000048; }
    .lp-btn {
      display: inline-block; margin-top: 6px; padding: 5px 10px;
      background: #26EFE9; color: #000048; border-radius: 999px;
      font-weight: 700; font-size: 11px; text-decoration: none;
    }
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var labs = ${labsJson};
  var activeId = ${activeIdJson};
  var me = { lat: ${user.lat}, lng: ${user.lng} };

  var bounds = L.latLngBounds([[me.lat, me.lng]]);
  labs.forEach(function (l) { bounds.extend([l.lat, l.lng]); });

  var map = L.map('map', { zoomControl: true, attributionControl: false }).fitBounds(bounds, { padding: [30, 30] });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);

  // user marker
  L.marker([me.lat, me.lng], {
    icon: L.divIcon({ className: '', html: '<div class="me-pin"></div>', iconSize: [18, 18] })
  }).addTo(map).bindTooltip('You', { permanent: false, direction: 'top' });

  function send(payload) {
    if (window.ReactNativeWebView) {
      window.ReactNativeWebView.postMessage(JSON.stringify(payload));
    }
  }

  labs.forEach(function (l) {
    var cls = (l.place_id === activeId) ? 'num-pin active' : 'num-pin';
    var marker = L.marker([l.lat, l.lng], {
      icon: L.divIcon({ className: '', html: '<div class="' + cls + '">' + l.idx + '</div>', iconSize: [32, 32] })
    }).addTo(map);
    marker.bindPopup(
      '<b>' + escapeHtml(l.name) + '</b><br/>' +
      escapeHtml(l.address || '') +
      (l.rating != null ? '<br/>★ ' + l.rating : '') +
      '<br/><a class="lp-btn" href="#" onclick="window.ReactNativeWebView.postMessage(JSON.stringify({type:\\'selectLab\\',place_id:\\'' + l.place_id + '\\'})); return false;">Pick this lab</a>'
    );
    marker.on('click', function () {
      send({ type: 'selectLab', place_id: l.place_id });
    });
  });

  function escapeHtml(s) { return String(s).replace(/[&<>"]/g, function(c) { return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]; }); }
</script>
</body>
</html>`;
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COG.white },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: COG.primary, paddingTop: 48, paddingBottom: 14, paddingHorizontal: 18,
  },
  title: { color: COG.white, fontSize: 17, fontWeight: "800" },
  close: { color: COG.white, fontSize: 22, fontWeight: "700", paddingHorizontal: 6 },

  center:  { flex: 1, justifyContent: "center", alignItems: "center", paddingHorizontal: 32 },
  hint:    { color: COG.grayDark, fontSize: 13, marginTop: 12, textAlign: "center", lineHeight: 18 },
  errTitle:{ color: COG.red,      fontSize: 15, fontWeight: "800" },
  closeBtn: { backgroundColor: COG.primary, paddingHorizontal: 24, paddingVertical: 10, borderRadius: 999, marginTop: 18 },
  closeBtnText: { color: COG.white, fontWeight: "800" },

  mapWrap: { height: 280, backgroundColor: COG.grayLightest },
  webview: { flex: 1, backgroundColor: "transparent" },

  list:    { flex: 1, paddingHorizontal: S.lg, paddingTop: S.md },
  listHdr: { fontSize: 11, fontWeight: "800", color: COG.grayDark, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 8 },

  card: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, paddingHorizontal: 12,
    borderWidth: 1, borderColor: COG.grayLighter, backgroundColor: COG.white,
    marginBottom: 8,
  },
  cardActive: { borderColor: COG.primary, backgroundColor: "rgba(38,239,233,0.08)" },
  numBubble:  {
    width: 28, height: 28, borderRadius: 14, backgroundColor: COG.primary,
    alignItems: "center", justifyContent: "center", marginRight: 12,
  },
  numText:   { color: COG.white, fontSize: 12, fontWeight: "800" },
  labName:   { fontSize: 14, fontWeight: "700", color: COG.primary },
  labAddr:   { fontSize: 11, color: COG.grayDark, marginTop: 2, lineHeight: 14 },
  metaRow:   { flexDirection: "row", alignItems: "center", flexWrap: "wrap", marginTop: 5, gap: 10 },
  rating:    { fontSize: 11, fontWeight: "700", color: COG.blueDark },
  openTag:   { fontSize: 10, fontWeight: "700", color: COG.green, letterSpacing: 0.3 },
  closedTag: { fontSize: 10, fontWeight: "700", color: COG.red,   letterSpacing: 0.3 },
  dirLink:   { fontSize: 11, fontWeight: "700", color: COG.blueDark, textDecorationLine: "underline" },
  checkMark: { fontSize: 22, color: COG.green, fontWeight: "800", marginLeft: 8 },

  footer:   {
    position: "absolute", bottom: 0, left: 0, right: 0,
    backgroundColor: COG.white,
    borderTopWidth: 1, borderTopColor: COG.grayLighter,
    paddingHorizontal: S.lg, paddingVertical: S.md, paddingBottom: 28,
  },
  confirmBtn: {
    backgroundColor: COG.primary, borderRadius: 999,
    paddingVertical: 14, alignItems: "center",
  },
  confirmText: { color: COG.white, fontSize: 14, fontWeight: "800", letterSpacing: 0.3 },
});
