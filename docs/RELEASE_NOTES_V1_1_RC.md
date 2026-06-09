# TENNET V1.1 Release Candidate

Version: `1.1.0-rc2-tennet`

TENNET V1.1 RC prepares the product for a staging acceptance cycle focused on Uber data imports, financial reconciliation, customer refund disputes, bulk evidence handling and persistent appeals.

## TENNET V1.1 RC2 fixes

- Improved detection for `order_not_received`, `missing_item`, `incorrect_item`, `quality_issue` and order-error adjustments from multilingual transaction text.
- Appeal Gmail draft creation now refuses clearly when Gmail is disabled or when no Gmail account is connected.
- Uber reconciliation results now keep `financial_status`, so a partially compensated order remains financially visible even when the operational status becomes `already_claimed`.

## Included

- Uber connector foundation with official API strategy and import fallback.
- Uber reporting import preview for orders, payments, adjustments and combined reports.
- Six-month reconciliation engine for canceled orders and financial transactions.
- Detection of canceled orders that are compensated, not compensated, partially compensated, already claimed, needing evidence or requiring manual review.
- Customer refund and order error dispute engine for customer refunds, missing items, order not received, chargebacks and negative adjustments.
- Evidence request queue and tokenized mobile upload links.
- Bulk evidence import for files and ZIP archives.
- Controlled fake/local evidence analysis and OCR-ready architecture.
- Evidence matching to claim orders, evidence tasks, customer refund disputes and reconciliation results.
- Persistent appeal workflow after Uber refusals.
- Recovery cockpit with unified detected, claimable, missing evidence, sent, recovered, refused, under-appeal and manual-review amounts.
- Staging configuration and V1.1 acceptance data.

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

## Validation Required

V1.1 RC must be validated in staging with real-format Uber Eats Manager / Uber Reporting exports supplied by the operator before production rollout.

The acceptance run should verify:

- report column mapping;
- unmapped store handling;
- reconciliation calculations;
- customer refund classification;
- evidence requirements and upload flows;
- bulk evidence matching accuracy;
- refusal-to-appeal workflow;
- recovery cockpit totals and exports.

## Not Production Release Yet

This RC does not deploy production automatically and does not modify the stable production `v1.0.3-tennet` deployment.
