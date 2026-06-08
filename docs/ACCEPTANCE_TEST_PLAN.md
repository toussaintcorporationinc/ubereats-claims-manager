# Acceptance test plan V1

Run these scenarios before commercial launch. Use only fictitious restaurants, orders, proofs and email addresses controlled by the team.

## Scenario A - Auth and roles

1. Create the first owner from `/setup-owner`.
2. Log in as owner.
3. Create one restaurant.
4. Create one manager and one staff user.
5. Assign the restaurant to the manager and staff user.
6. Confirm staff cannot create restaurants or manage users.
7. Confirm a manager without assignment cannot access another restaurant.

Expected result: permissions match owner, manager and staff rules.

## Scenario B - Manual order

1. Create one disputed order.
2. Upload one `cancellation_proof`.
3. Upload one `preparation_proof` or one `waste_photo`.
4. Validate the order.

Expected result: the order becomes `ready_to_send`; missing proof cases become `missing_evidence`.

## Scenario C - Bulk import

1. Import `docs/examples/demo_orders.csv`.
2. Review the preview.
3. Confirm invalid rows, duplicates and unauthorized rows are clearly marked.
4. Confirm the import.
5. Open the created orders.

Expected result: only valid and authorized rows create orders.

## Scenario D - Email

1. Generate an internal draft for a ready order.
2. Connect a Gmail sandbox account.
3. Create a Gmail draft with evidence included.
4. Send the Gmail draft manually after explicit confirmation.
5. Verify the provider draft status becomes `sent`.
6. Verify an outbound `EmailThread` exists.

Expected result: the email is sent only after manual confirmation.

## Scenario E - Uber reply

1. Sync inbound Gmail replies.
2. Confirm a reply linked by thread appears on the order.
3. Manually link an unlinked reply if needed.
4. Process a reply as accepted, refused or payment to verify.
5. Check the order status and audit log.

Expected result: replies are recorded and decisions are traceable.

## Scenario F - Follow-up

1. Recalculate follow-ups for an eligible sent order.
2. Create a `followup_1` internal draft.
3. Create a Gmail draft for the follow-up.
4. Send it manually through the Gmail send workflow.
5. Mark or verify the task as completed.
6. Check `retry_count` and `last_followup_sent_at`.

Expected result: follow-ups are limited, traceable and never automatic.

## Scenario G - Reporting

1. Open `/reports`.
2. Filter by restaurant and date range.
3. Export orders as CSV.
4. Export commercial summary as XLSX.
5. Confirm `customer_name` is absent by default.

Expected result: reporting respects roles, filters and data minimization.

## Scenario H - Production

1. Verify `/health`.
2. Verify `/ready`.
3. Verify `/version`.
4. Run a PostgreSQL backup.
5. Run an evidence/import backup.
6. Perform a restore test on a non-production environment.
7. Review Docker logs.
8. Execute the rollback plan on a test stack.

Expected result: operations are ready before go-live.

