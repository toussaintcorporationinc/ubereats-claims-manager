# Staging Acceptance Plan V1.1

Use this plan to validate TENNET V1.1 RC on staging before any production release.

## Entry Criteria

- `VERSION` is `1.1.0-rc2-tennet`.
- Staging URLs respond on `/health`, `/ready` and `/version`.
- `EMAIL_PROVIDER_ENABLED=false` unless Gmail staging is intentionally tested.
- `GMAIL_INBOUND_SYNC_ENABLED=false` unless Gmail staging is intentionally tested.
- `AI_EVIDENCE_ANALYSIS_ENABLED=false`.
- No real customer data is loaded.

## Acceptance Data

Use `docs/examples/v1_1`.

Create fictitious restaurants:

- `Restaurant Test Nord`
- `Restaurant Test Sud`
- `Restaurant Test Est`

Map stores:

- `STORE-RC-001`
- `STORE-RC-002`
- `STORE-RC-003`

## Acceptance Checklist

- Import Uber orders, payments and adjustments samples.
- Confirm only after preview review.
- Run reconciliation over the default 180-day period.
- Verify compensated, not compensated, partially compensated, already claimed and manual-review results.
- Create claim orders from eligible results.
- Recalculate evidence tasks.
- Import bulk evidence through `/evidence-imports`.
- Analyze using `fake` or local provider only.
- Accept a high-confidence match manually.
- Detect customer refund disputes.
- Create one customer refund claim order.
- Create one internal draft without sending.
- Create a refused review and verify an appeal workflow opens.
- Create appeal draft and Gmail draft record without sending automatically.
- Mark appeal sent only after manual confirmation in the app.
- Verify recovery cockpit totals and actions.
- Export recovery/reporting files and verify no secrets or raw storage paths appear.

## TENNET V1.1 RC2 fixes

- Verify "commande non recue", "commande non reçue" and "Order not received" classify as `order_not_received`.
- Verify "article manquant" and "missing item" classify as `missing_item`.
- Verify appeal Gmail draft creation is disabled with the message "Gmail est desactive sur cet environnement" when `EMAIL_PROVIDER_ENABLED=false`.
- Verify a partial compensation remains visible through `financial_status=partially_compensated` after creating a TENNET dossier.

## Exit Criteria

- All critical scenarios pass.
- Any mapping or reconciliation ambiguity is documented.
- No automatic email was sent.
- No OpenAI call was made unless explicitly enabled for a separate controlled test.
- No real customer data was used.
