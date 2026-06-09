# V1.1 fictitious acceptance data

These files are only for TENNET V1.1 staging and local acceptance.

They contain:

- fictitious restaurant names;
- fictitious Uber order ids;
- fictitious customer labels such as `Client Test`;
- no real customer data;
- no real Uber order;
- no personal address.

## Files

- `uber_orders_report_sample.csv` covers canceled, compensated, partially compensated, already claimed and manual-review orders.
- `uber_payments_report_sample.csv` covers full and partial compensation.
- `uber_adjustments_report_sample.csv` covers customer refund, missing item, adjustment, chargeback and manual-review deductions.
- `customer_refunds_sample.csv` documents the expected customer refund dispute cases.
- `demo_claim_orders.csv` creates existing TENNET claim orders for duplicate/already-claimed and missing-evidence scenarios.

## Suggested staging flow

1. Create restaurants matching `Restaurant Test Nord`, `Restaurant Test Sud` and `Restaurant Test Est`.
2. Map them to `STORE-RC-001`, `STORE-RC-002` and `STORE-RC-003`.
3. Import the orders, payments and adjustments files from `/uber/reporting/new`.
4. Confirm the imports after preview.
5. Run reconciliation for the default 180-day window.
6. Create claim orders for eligible non-compensated results.
7. Recalculate evidence tasks.
8. Import proof files through `/evidence-imports` if needed.
9. Use `/customer-refunds` to detect deductions.
10. Use `/recovery` and `/appeals` for the V1.1 acceptance scenarios.
