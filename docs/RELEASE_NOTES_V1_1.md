# TENNET V1.1

Current version: `1.1.1-tennet`

## TENNET V1.1.1 Patch

Version: `1.1.1-tennet`

This patch aligns the repository with the production domain migration:

- `thetennet.com` is the official TENNET domain.
- Production uses `https://app.thetennet.com` and `https://api.thetennet.com`.
- Staging uses `https://staging-app.thetennet.com` and `https://staging-api.thetennet.com`.
- Resend is documented for the verified domain `mail.thetennet.com`.
- Resend remains disabled by default and no API key is stored in the repository.
- Gmail remains separate for Uber conversation threads.
- No automatic send, followup, appeal or OpenAI path is enabled by default.

## TENNET V1.1.0 Final

Version: `1.1.0-tennet`

TENNET V1.1.0 is the final V1.1 release after RC2 staging acceptance. It expands TENNET from a controlled Uber Eats claims workflow into a broader recovery cockpit for imported Uber reporting data, evidence workflows, customer refund disputes and persistent appeals.

## Included

- Uber reporting imports for orders, payments, adjustments and combined CSV/XLSX reports.
- Six-month Uber reconciliation for canceled orders and imported financial transactions.
- Detection of canceled orders that are compensated, not compensated, partially compensated, already claimed, missing evidence or requiring manual review.
- Customer refund and Uber deduction dispute engine for order not received, missing item, incorrect item, quality issue, chargeback and order-error adjustments.
- Evidence request queue with tokenized mobile upload links.
- Bulk evidence import for files and ZIP archives.
- Deterministic fake/local evidence analysis by default, with OCR/AI architecture prepared but disabled by default.
- Evidence matching to claim orders, evidence tasks, customer refund disputes and reconciliation results.
- Persistent appeal workflows so Uber refusals are not closed automatically.
- Recovery cockpit with detected, claimable, missing-evidence, sent, recovered, refused, pending, under-appeal and manual-review amounts.
- CSV/XLSX reporting and recovery exports.

## Guardrails

- No reimbursement is guaranteed.
- No email is sent automatically.
- No follow-up loop is automatic or infinite.
- No appeal is sent automatically.
- OpenAI/Vision analysis is disabled by default.
- Gmail provider remains manual for draft creation, sending and inbound sync.
- No scraping of Uber Eats Manager.
- No Uber password collection or browser automation.
- No fake proof, amount or order number should be created.

## Validation Notes

RC2 staging acceptance was completed before this final release. Production rollout should still validate the workflow with real-format Uber Eats Manager / Uber Reporting exports supplied by the operator before relying on the calculations commercially.

Recommended validation documents:

- `docs/V1_1_ACCEPTANCE_TEST_PLAN.md`
- `docs/STAGING_ACCEPTANCE_PLAN.md`
- `docs/KNOWN_LIMITATIONS_V1_1.md`
- `docs/RECOVERY_COCKPIT.md`
- `docs/BULK_EVIDENCE_IMPORT.md`
- `docs/PERSISTENT_APPEALS.md`
- `docs/CUSTOMER_REFUND_DISPUTES.md`
- `docs/UBER_RECONCILIATION_RULES.md`
