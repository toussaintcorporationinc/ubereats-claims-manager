# TENNET user guide V1

TENNET helps restaurants prepare, track and document Uber Eats claims for orders cancelled after preparation.

Important: no email, reply or follow-up is sent automatically. Every Gmail send requires manual confirmation.

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

## Controlled follow-ups

1. Open `/followups`.
2. Recalculate follow-ups as owner or manager.
3. Create an internal follow-up draft.
4. Create a Gmail draft if needed.
5. Send manually through the Gmail send workflow.
6. Complete or skip the task.

Follow-ups are limited and traceable. There is no infinite follow-up loop.

## Reports and exports

1. Open `/reports`.
2. Filter by restaurant and date.
3. Review claimed, recovered, pending and refused amounts.
4. Export CSV or XLSX if your role allows it.

Customer names are excluded from reports and exports by default.

