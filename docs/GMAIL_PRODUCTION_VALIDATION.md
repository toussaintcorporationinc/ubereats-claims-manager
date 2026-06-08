# Gmail production validation V1

Use a dedicated Gmail account controlled by the business. Validate in sandbox before sending operational claims.

## Google Cloud setup

1. Create or select a Google Cloud project.
2. Configure the OAuth consent screen.
3. Create an OAuth client for a web application.
4. Add the production redirect URI:

```text
https://api.example.com/v1/email/gmail/oauth/callback
```

5. Store the client id and secret only in `.env.production`.

## Scopes

Configure scopes for:

- Gmail compose and draft creation;
- Gmail send through a manually approved draft;
- Gmail readonly for inbound replies.

Recommended value:

```text
https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly
```

If scopes change after an account is connected, reconnect the Gmail account.

## Local vs production

Local redirect URI:

```text
http://localhost:8000/v1/email/gmail/oauth/callback
```

Production redirect URI:

```text
https://api.example.com/v1/email/gmail/oauth/callback
```

## Validation steps

1. Set `EMAIL_PROVIDER_ENABLED=true`.
2. Connect Gmail from `/settings/email`.
3. Confirm status shows connected without exposing tokens.
4. Create one internal draft.
5. Create one Gmail draft.
6. Confirm the draft exists in Gmail.
7. Send one manual test email to a controlled address.
8. Confirm provider draft status becomes `sent`.
9. Sync inbound replies with `GMAIL_INBOUND_SYNC_ENABLED=true`.
10. Confirm the reply appears in `/inbox`.
11. Disconnect Gmail and confirm status becomes disconnected.

## Token and log checks

Verify that:

- no access token appears in API responses;
- no refresh token appears in API responses;
- no token appears in frontend storage;
- no token appears in Docker logs;
- no Gmail secret is committed.

## Revocation

To revoke access:

1. Disconnect from `/settings/email`.
2. Revoke the app in the Google account security page.
3. Disable provider if needed:

```bash
EMAIL_PROVIDER_ENABLED=false
GMAIL_INBOUND_SYNC_ENABLED=false
```

