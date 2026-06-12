# TENNET native mobile app

Expo/React Native app for restaurant field work.

## What it does

- secure TENNET login with the production API by default;
- dashboard and high priority actions;
- pending evidence tasks for assigned restaurants;
- camera or PDF upload for a task;
- printable evidence ticket creation through the TENNET API;
- QR scan for tokenized public evidence upload links;
- recovery cockpit summary and operational actions;
- account screen with environment and logout.

The app does not enable Gmail, OpenAI, AutoPilot or automatic sending. It only calls the existing TENNET API with the logged-in user permissions.

## Run locally

```bash
cd mobile/tennet-native
npm install
npm run typecheck
npm run android
```

Optional API override:

```bash
set EXPO_PUBLIC_API_BASE_URL=https://staging-api.thetennet.com
set EXPO_PUBLIC_WEB_APP_URL=https://staging-app.thetennet.com
npm run android
```

## Android release path

This app is configured with Android package `com.thetennet.mobile`.

To publish on Google Play, create a production build with EAS or a local native build, then upload the resulting AAB in Play Console. Google Play login, payment profile, app signing and 2FA remain manual owner steps.

Recommended next command once EAS is configured:

```bash
npx eas build --platform android --profile production
```

The repo includes `eas.json` with `development`, `preview` and `production` profiles. `production` creates an Android App Bundle.

Do not commit keystores, service account JSON files or Play Console credentials.
