# TENNET release notes V1

Version: `1.0.1-tennet`

## Features

- Extensible multi-restaurant claim management.
- JWT authentication with owner, manager and staff roles.
- Disputed Uber Eats order tracking.
- Secure local evidence upload.
- CSV/XLSX bulk order import with preview and confirmation.
- Claim validation based on blocking evidence.
- Internal email draft generation.
- Gmail OAuth connection.
- Real Gmail draft creation with evidence attachments.
- Manual approved Gmail send.
- Gmail inbound reply sync and manual linking.
- Manual Uber response review.
- Controlled follow-up workflow with J+2, J+5, J+10 and J+15 policy.
- Commercial dashboard and reporting.
- CSV/XLSX exports.
- Production Docker Compose, Caddy reverse proxy and persistent volumes.
- Backup, restore, operations and go-live documentation.

## Limits

- No AI classification or OpenAI integration.
- No automatic reply.
- No automatic follow-up send.
- No automatic email send.
- Local evidence storage in production V1.
- No S3 or KMS integration yet.
- No advanced JWT refresh token flow.
- No antivirus scanning for uploaded files.
- Gmail production use must be validated with a sandbox account before real use.
- Moderate npm vulnerabilities, if reported by npm audit, should be handled in a separate dependency-hardening mission.

## Operational warning

Every Gmail send requires explicit manual confirmation. Follow-up tasks create drafts only.

