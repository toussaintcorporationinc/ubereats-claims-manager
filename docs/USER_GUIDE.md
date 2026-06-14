# TENNET user guide V1

TENNET helps restaurants prepare, track and document Uber Eats claims for orders cancelled after preparation.

Important: no email, reply or follow-up is sent automatically. Every Gmail send requires manual confirmation.

The official production application is `https://app.thetennet.com`.

## Login and first owner

1. Open the application.
2. If no user exists, open `/setup-owner`.
3. Create the first owner account.
4. Use `/login` for future sessions.

After the first owner exists, public registration is closed.

## Restaurants and users

1. As owner, open `/restaurants/new`.
2. Create a restaurant with name, legal name, address and sender email.
3. Open `/users/new`.
4. Create manager or staff users.
5. Open the user detail page and assign restaurants.

Managers and staff see only their assigned restaurants.

## Manual claim order

1. Open `/orders/new`.
2. Select the restaurant.
3. Enter the Uber order number and amount.
4. Add any known date, time, customer, loss type and notes.
5. Save the order.

Do not invent missing data. Leave unknown optional fields empty.

## Bulk import CSV/XLSX

1. Open `/imports/new`.
2. Select a CSV or XLSX file.
3. Click analyse.
4. Review valid, invalid, duplicate and unauthorized rows.
5. Confirm the import only after reviewing the preview.

The backend creates only valid and authorized rows.

## Evidence upload

1. Open an order detail page.
2. In the evidence section, choose the evidence type.
3. Select a PDF or supported image.
4. Upload the file.

Required blocking evidence for validation:

- `cancellation_proof`;
- `preparation_proof` or `waste_photo`.

The receipt is recommended but not blocking in V1.

## Evidence request queue

1. Open `/evidence-tasks`.
2. Recalculate evidence requests as owner or manager.
3. Review missing proof tasks by restaurant, status, type and priority.
4. Open a task.
5. Upload the requested file directly, or create a mobile upload link.
6. Send the link to the person who can provide the proof.
7. The mobile page accepts only the requested proof type.
8. After upload, TENNET attaches the proof, completes the task, audits the action and validates the order again.

The raw mobile token is shown only once. TENNET stores only the token hash.

## Live evidence station

Open `/live-evidence` when the restaurant team needs to collect proofs fast on phone, tablet or front counter.

1. Review the next recommended proof.
2. Click `Imprimer ticket`.
3. Print the TENNET ticket on the available system printer.
4. Put the ticket next to the receipt, prepared order, waste photo or requested proof.
5. Scan the QR code or open the upload link.
6. Upload the photo. On compatible mobile browsers, TENNET opens the camera directly.

The station does not read the Uber Eats tablet, does not invent proof and does not send email. It only routes field evidence to the right TENNET task.

## Bulk evidence import

1. Open `/evidence-imports/new`.
2. Select a restaurant if the batch is restaurant-specific.
3. Upload several proof files or one ZIP.
4. Open the created batch.
5. Run the analysis.
6. Review each imported file, detected type and match candidates.
7. Accept a candidate only when the match is clear.
8. Ignore files that are not useful for a claim.

TENNET can attach an imported file to an order, an evidence task, a customer refund dispute or a reconciliation result. It does not invent proof and does not force ambiguous matches.

## Claim validation

1. Open the order detail page.
2. Click validate dossier.
3. Review `missing_items` and `blocking_reasons` if incomplete.

Complete orders become `ready_to_send`. Incomplete orders become `missing_evidence`.

## Internal drafts and Gmail drafts

1. Open a `ready_to_send` order.
2. Click generate internal draft.
3. Review the subject and body.
4. If Gmail is connected, click create Gmail draft.
5. Choose whether to include evidence files.

Creating a Gmail draft does not send the email.

## Manual Gmail send

1. Open `/drafts` or the order detail page.
2. Find a Gmail provider draft.
3. Click send Gmail draft.
4. Read the warning.
5. Confirm explicitly.

This action sends a real email and cannot be undone.

## Inbound replies

1. Open `/inbox`.
2. Click sync Gmail replies.
3. Review linked and unlinked messages.
4. Link an unlinked message manually if the match is clear.

The application reads and links replies. It does not answer automatically.

## Response review

1. Open a linked inbound reply.
2. Choose the manual decision: accepted, refused, payment to verify, payment confirmed, manual review or ignored.
3. Save the review.

The decision updates the order and creates an audit log.

## Persistent appeals after refusal

1. When a claim or customer refund dispute is refused, open `/appeals`.
2. Open the workflow detail.
3. Review the refusal analysis and required evidence.
4. Create an internal appeal draft.
5. Create a Gmail draft only if Gmail is configured and the content is ready.
6. Send manually through the approved Gmail workflow.
7. Mark the appeal as sent in TENNET.
8. Pause, manually close or reopen the workflow when appropriate.

A refusal does not close the case automatically. Appeals are limited, traceable and never sent automatically.

## Customer refund deductions

1. Open `/customer-refunds`.
2. Detect deductions from imported Uber financial transactions.
3. Open a dispute detail page.
4. Create a TENNET claim order when the case is eligible.
5. Upload the required evidence.
6. Create an internal draft only when evidence is complete.
7. If Gmail is connected, create a Gmail draft.
8. Send manually through the Gmail send workflow.
9. Record Uber's decision with a manual review.

Possible decisions include accepted, payment to verify, payment confirmed, refused, evidence requested, information requested, follow-up needed, ignored and manual review.

TENNET does not promise reimbursement. It helps ensure no detected deduction is left unreviewed.

## Recovery cockpit

1. Open `/recovery`.
2. Review detected, claimable, missing evidence, sent, recovered and refused amounts.
3. Open `/recovery/cases` to filter all recoverable cases.
4. Open `/recovery/actions` to work through evidence, drafts, responses, follow-ups and manual reviews.
5. Export summary XLSX or cases CSV if your role allows it.

The cockpit also highlights active appeals, escalations and refused amounts still under appeal. It does not send emails, create automatic follow-ups or make decisions without the user.

## Controlled follow-ups

1. Open `/followups`.
2. Recalculate follow-ups as owner or manager.
3. Create an internal follow-up draft.
4. Create a Gmail draft if needed.
5. Send manually through the Gmail send workflow.
6. Complete or skip the task.

Follow-ups are limited and traceable. There is no infinite follow-up loop.

## AutoPilot controlled send

AutoPilot can send Gmail emails automatically only when the configured safety rules are met. It is off by default.

Use it this way:

1. Confirm Gmail is connected.
2. Confirm the restaurant has AutoPilot enabled.
3. Open `/autopilot`.
4. Choose initial claims, follow-ups, appeals or all.
5. Run a dry-run first.
6. Review candidates and skipped reasons.
7. Run AutoPilot only if the dry-run is correct.
8. Review `/autopilot/runs` after execution.

AutoPilot requires complete evidence, daily limits, per-restaurant limits and cooldowns. It never closes a refusal automatically and does not guarantee reimbursement. Use the emergency stop button if sending must be paused immediately.

## Reports and exports

1. Open `/reports`.
2. Filter by restaurant and date.
3. Review claimed, recovered, pending and refused amounts.
4. Export CSV or XLSX if your role allows it.

Customer names are excluded from reports and exports by default.

## V1.1 staging acceptance

For the V1.1 release candidate, use `/uber/reporting`, `/uber/reconciliation`, `/customer-refunds`, `/evidence-tasks`, `/evidence-imports`, `/appeals` and `/recovery` with fictitious data first.

Use `docs/examples/v1_1` as the starting dataset.

Before production rollout, repeat the import and reconciliation scenarios with real-format Uber exports supplied by the operator, while keeping customer data minimized.

## Smart Import and mobile usage

Open `/dashboard` or `/smart-import` to drop Uber reports, evidence images, PDFs or ZIP files without renaming them. TENNET detects the content, routes the file, applies safe Uber rows automatically, keeps doubtful rows visible, then runs the recovery machine: deductions, claim files, drafts, followups, appeals, Gmail sync and AutoPilot when the configured safety rules allow it.

Use `/remboursements` for customer refund disputes and `/annulations` for cancelled prepared orders. These pages are business paths; the technical screens remain available for audit and verification.

On mobile, use the header menu, evidence cards and sticky action bars to work in the restaurant. Staff users should focus on "Mes preuves a fournir", uploading photos or PDFs only for assigned restaurants.

From an evidence task, use "Imprimer ticket preuve" on web when the restaurant needs a physical reminder. In the Android app, staff use the simpler action "Imprimer et prendre photo": TENNET prints the ticket on the paired Bluetooth receipt printer, then opens the camera so the proof goes to the right task.

TENNET always prefers a clear action, readable status and guided workflow over a technical table. It does not guarantee reimbursement and does not invent proof, amounts or order numbers.

## Native mobile app

The native app in `mobile/tennet-native` is for daily field work: open urgent actions, upload proof photos, print an evidence ticket on Android Bluetooth ESC/POS printers, scan its QR code and check recovery actions from a phone. Staff users see a minimal "A faire maintenant" station instead of financial screens. It keeps the same TENNET permissions as the web app and does not send email automatically from the evidence station.

