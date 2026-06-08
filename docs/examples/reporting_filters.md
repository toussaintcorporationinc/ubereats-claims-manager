# Reporting filters examples

Examples use fictitious values only.

## Commercial summary for one restaurant

```text
GET /v1/reports/commercial-summary?restaurant_id=1&date_from=2026-06-01&date_to=2026-06-30
```

## Orders export without customer names

```text
GET /v1/reports/export/orders.csv?status=waiting_uber_response&min_amount=10&max_amount=100
```

## Orders export with customer names

```text
GET /v1/reports/export/orders.xlsx?include_customer_names=true
```

Customer names are excluded by default and should be included only when operationally necessary.
