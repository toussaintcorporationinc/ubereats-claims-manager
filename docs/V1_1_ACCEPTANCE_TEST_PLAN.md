# V1.1 Acceptance Test Plan

This plan verifies TENNET V1.1 RC end to end on staging with fictitious data first, then with operator-provided Uber export formats.

TENNET does not guarantee reimbursement. It provides detection, tracking, review and traceability.

## Scenario 1 - Uber Reporting Import

1. Open `/uber/reporting/new`.
2. Import `uber_orders_report_sample.csv`.
3. Review preview, detected columns, invalid rows and warnings.
4. Map unmapped stores in `/uber/unmapped-stores`.
5. Confirm the import.
6. Repeat with `uber_payments_report_sample.csv`.
7. Repeat with `uber_adjustments_report_sample.csv`.
8. Verify snapshots and transactions are created only after confirmation.

## Scenario 2 - Six-Month Reconciliation

1. Open `/uber/reconciliation`.
2. Run analysis with default 180-day lookback.
3. Verify:
   - not compensated order;
   - compensated order;
   - partially compensated order;
   - already claimed order;
   - manual-review order.
4. Verify `total_missing_amount` and result reasons.
5. Verify `financial_status` remains `partially_compensated` for a partial payment even if the operational status later becomes `already_claimed`.

## Scenario 3 - Claim Order Creation

1. Create a `ClaimOrder` from one `not_compensated` result.
2. Run bulk create for selected eligible results.
3. Verify compensated, already claimed and manual-review results are skipped.
4. Verify duplicate claim orders are not created.

## Scenario 4 - Evidence Tasks

1. Recalculate evidence tasks.
2. Verify missing evidence tasks are created.
3. Upload a requested proof.
4. Create a tokenized mobile link.
5. Upload via the mobile page.
6. Verify validation is retried and audit logs are created.

## Scenario 5 - Bulk Evidence Import

1. Open `/evidence-imports/new`.
2. Import fictitious ZIP or proof files.
3. Analyze with `fake` or local provider.
4. Verify evidence type classification and extracted order number.
5. Accept a clear match.
6. Verify `EvidenceFile` is created.
7. Verify matching `EvidenceRequestTask` is completed.
8. Verify `ClaimOrder` validation is retried.

## Scenario 6 - Customer Refunds

1. Open `/customer-refunds`.
2. Detect deductions from imported adjustment transactions.
3. Verify:
   - order not received;
   - missing item;
   - negative adjustment;
   - chargeback;
   - manual review.
4. Verify evidence requirements by dispute type.
5. Create a claim order from an eligible dispute.
6. Complete evidence.
7. Create an internal draft without sending.

## TENNET V1.1 RC2 fixes

- Detect `order_not_received` from "Commande non recue", "commande non reçue", "Order not received" and similar text.
- Detect `missing_item` from "Article manquant", "missing item" and similar text.
- Detect `incorrect_item`, `quality_issue` and `order_error_adjustment` from multilingual reason text.
- Refuse appeal Gmail draft creation when Gmail is disabled or not connected.
- Display operational `status`, `financial_status` and `missing_amount` in reconciliation result review.

## Scenario 7 - Recovery Cockpit

1. Open `/recovery`.
2. Verify detected amount.
3. Verify claimable amount.
4. Verify missing-evidence amount.
5. Verify sent, recovered and refused amounts after manual status changes.
6. Open `/recovery/cases`.
7. Open `/recovery/actions`.
8. Export summary XLSX and cases CSV.

## Scenario 8 - Refusals Stay Alive

1. Create a refused response review.
2. Verify `AppealWorkflow` is created.
3. Open `/appeals`.
4. Analyze refusal.
5. Create appeal draft.
6. Create Gmail draft record if Gmail is configured, without sending.
7. Mark sent manually only after explicit user action.
8. Verify cooldown blocks immediate duplicate.
9. Manually close as owner.

## Scenario 9 - Security and Permissions

1. Verify staff cannot manage Uber imports, customer refund detection, appeals or recovery exports.
2. Verify manager sees only assigned restaurants.
3. Verify owner can close appeal workflows manually.
4. Verify no secrets are exposed in API responses or exports.
5. Verify no automatic email send path is active.
6. Verify OpenAI/Vision remains disabled by default.
7. Verify no misleading reimbursement promise appears in UI or docs.
