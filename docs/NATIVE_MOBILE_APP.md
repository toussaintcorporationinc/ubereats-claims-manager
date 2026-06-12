# TENNET native mobile app

TENNET now includes a native mobile foundation under `mobile/tennet-native`.

## Purpose

The native app is designed for restaurant field operations:

- see the most urgent proof tasks;
- take a proof photo from the phone;
- upload a PDF or image to a specific task;
- print a TENNET evidence ticket;
- scan a ticket QR code;
- upload through tokenized public proof links;
- view recovery amounts and next actions.

It is a companion to the web app, not a separate backend. It uses the same production API, roles, audit logs and evidence rules.

## Security model

- Login uses `/v1/auth/login`.
- The JWT is stored with `expo-secure-store`.
- The app never stores Gmail passwords, Uber passwords, Resend keys or OpenAI keys.
- The app does not enable Gmail, OpenAI, AutoPilot or automatic sending.
- Staff only see data allowed by the existing backend permissions.
- Public upload links still use hashed one-time tokens on the backend.

## Production defaults

- API: `https://api.thetennet.com`
- Web app: `https://app.thetennet.com`
- Android package: `com.thetennet.mobile`
- iOS bundle identifier: `com.thetennet.mobile`

Use `EXPO_PUBLIC_API_BASE_URL` and `EXPO_PUBLIC_WEB_APP_URL` for staging builds.

## Play Store readiness

The repository prepares the native app source and package identity. Publishing still requires owner-controlled Google Play steps:

- Google Play Console access;
- app signing setup;
- store listing, screenshots and privacy declarations;
- upload of an AAB generated from this app;
- review submission.

`mobile/tennet-native/eas.json` defines a production Android App Bundle profile. Do not run submit automation with stored credentials until the Play Console account and privacy declarations are verified by the owner.

Credentials, 2FA codes and service account files must never be committed or pasted into logs.

## Manual verification

1. Build/run the app on Android.
2. Log in with a TENNET user.
3. Confirm dashboard loads.
4. Open `Preuves`.
5. Upload a fictitious proof photo.
6. Create and print a proof ticket.
7. Scan the QR code and upload a second fictitious proof through the public link.
8. Open `Recovery`.
9. Verify no Gmail, OpenAI or auto-send action is triggered.
