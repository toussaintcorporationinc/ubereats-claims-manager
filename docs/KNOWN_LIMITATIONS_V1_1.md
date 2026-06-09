# Known Limitations V1.1

TENNET V1.1 RC is designed for staging acceptance before production rollout.

## Product Limits

- TENNET does not guarantee reimbursement.
- TENNET guarantees detection, tracking, review and traceability of detected losses.
- Uber decisions still require human review.
- Final closure requires an owner decision.
- Customer refund disputes depend on the quality of imported Uber financial exports.
- Reconciliation can leave ambiguous cases in manual review.

## Data Import Limits

- Uber report formats may vary by account, country or export version.
- Column mapping is tolerant but still needs staging validation with real-format exports.
- Store mapping is required before reliable reconciliation.
- Missing order amounts or missing order identifiers remain manual-review cases.
- The default lookback is 180 days, configurable by environment.

## Evidence Limits

- Bulk evidence analysis is deterministic/fake by default for CI and staging.
- OpenAI/Vision is disabled by default and must be explicitly enabled by environment.
- OCR/local analysis may not read every PDF or image format.
- Ambiguous evidence matches should remain manual.
- No proof is invented.

## Email and Appeal Limits

- Gmail must be configured separately and stays manual.
- No email is sent automatically.
- No follow-up or appeal loop sends automatically.
- Persistent appeals help keep refusals active, but do not ensure a favorable Uber outcome.

## Infrastructure Limits

- Staging uses local Docker volumes in the provided compose file.
- Production V1 still uses local file storage unless a future S3/KMS backend is added.
- No antivirus scanning of uploaded files is implemented in V1.1.
- Moderate npm audit findings may remain until dependency remediation is scheduled.
