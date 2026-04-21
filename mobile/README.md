# Cognizant Care — Mobile (Expo / React Native)

Per-member APK that talks to the Flask backend's `/api/v1/mobile/*` endpoints.

## Flow

1. Member opens app → enters Member ID → backend emails a 6-digit OTP.
2. Member enters OTP → backend issues a 30-day JWT (stored in `expo-secure-store`).
3. Every subsequent request carries `Authorization: Bearer <jwt>`. Backend derives
   `member_id` from the JWT, never from the request body — so a member can only
   ever see/modify their own data.

## Screens

- `app/login.jsx` — Member ID entry
- `app/verify.jsx` — OTP verification
- `app/(tabs)/home.jsx` — Profile + open care gaps
- `app/(tabs)/appointments.jsx` — List & book appointments
- `app/(tabs)/chat.jsx` — Bedrock-powered personal health assistant

## Setup

```bash
cd mobile
npm install
npx expo start
```

Scan the QR code with the Expo Go app, or press `a` to launch on an Android emulator.

### API base URL

`app.json` → `expo.extra.apiBaseUrl`.

- `http://10.0.2.2:5000` — Android emulator reaching host machine
- `http://<your-LAN-ip>:5000` — physical device on the same WiFi
- `https://care.yourdomain.com` — production

## Build APK

```bash
npm install -g eas-cli
eas login
eas build:configure
npm run build:apk
```

EAS returns a downloadable `.apk` URL. Distribute to members via email / install link.
