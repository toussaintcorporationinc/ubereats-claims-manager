# Resend Setup

Resend is prepared as an optional transactional email provider for TENNET. It is disabled by default.

## Domain

Use the verified sending domain:

- `mail.thetennet.com`

Using a mail subdomain keeps the sending reputation separated from the main application domain.

## DNS

Configure the DNS records exactly as Resend provides them for `mail.thetennet.com`.

Typical records may include:

- SPF or return-path records;
- DKIM records;
- DMARC policy records;
- optional tracking records if enabled in Resend.

Do not invent DNS values. Do not replace existing email records without operator confirmation.

## Environment

Production and staging examples keep Resend disabled:

```env
RESEND_ENABLED=false
RESEND_API_KEY=
RESEND_DOMAIN=mail.thetennet.com
RESEND_FROM_EMAIL=TENNET <notifications@mail.thetennet.com>
RESEND_REPLY_TO=
```

For staging, use:

```env
RESEND_FROM_EMAIL=TENNET Staging <notifications@mail.thetennet.com>
```

`RESEND_API_KEY` must be configured only in the real server environment when Resend is intentionally enabled. It must never be committed, logged, displayed in the UI, stored in audit logs or added to GitHub.

## Provider boundaries

- Resend is for transactional/manual server sends when explicitly enabled.
- Gmail remains separate for Uber dispute conversations, Gmail drafts, manual Gmail send and inbound reply sync.
- Resend does not read inbound replies in this version.
- AutoPilot does not use Resend by default.
- No automatic send is enabled by this setup.

## Verification

After DNS is verified in Resend and the server environment is intentionally configured, verify status from the API:

```bash
curl -fsS https://api.thetennet.com/v1/email/resend/status
```

Authenticated manual sends still require `confirm_send=true` and the existing role permissions.
