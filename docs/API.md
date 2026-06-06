# API - Uber Eats Claims Manager

Base URL locale backend : `http://localhost:8000`

## Health

- `GET /health`

Retour attendu :

```json
{
  "status": "ok",
  "service": "Uber Eats Claims Manager"
}
```

## Restaurants

- `GET /v1/restaurants`
- `POST /v1/restaurants`
- `GET /v1/restaurants/{id}`
- `PATCH /v1/restaurants/{id}`

Champs principaux :

- `name` obligatoire ;
- `sender_email` obligatoire ;
- `active` vaut `true` par defaut.

La creation d'un restaurant ajoute un `AuditLog`.

## Orders

- `GET /v1/orders`
- `POST /v1/orders`
- `GET /v1/orders/{id}`
- `PATCH /v1/orders/{id}`

Regles :

- `restaurant_id` est obligatoire ;
- `uber_order_number` est obligatoire ;
- `order_amount` est obligatoire ;
- `currency` vaut `EUR` par defaut ;
- `status` vaut `draft` par defaut ;
- `retry_count` vaut `0` par defaut ;
- un meme `uber_order_number` ne peut pas etre cree deux fois pour le meme restaurant ;
- le meme `uber_order_number` reste autorise pour deux restaurants differents.

La creation d'une commande ajoute un `AuditLog`.

## Evidence

- `GET /v1/orders/{id}/evidence`
- `POST /v1/orders/{id}/evidence`

Types autorises :

- `receipt`
- `cancellation_proof`
- `preparation_proof`
- `waste_photo`
- `uber_screenshot`
- `other`

L'ajout d'une preuve ajoute un `AuditLog`.

## Drafts

- `GET /v1/orders/{id}/drafts`

Les brouillons sont internes. Aucun envoi reel d'email n'est implemente.

Types prevus :

- `initial_claim`
- `followup_1`
- `followup_2`
- `escalation`
- `proof_reply`

## Dashboard

- `GET /v1/dashboard/summary`

Retourne :

- `total_orders`
- `total_claimed_amount`
- `total_recovered_amount`
- `total_pending_amount`
- `total_refused_amount`
- `orders_by_status`
- `orders_by_restaurant`

## Hors perimetre V1 actuelle

- pas d'integration Gmail ;
- pas d'integration OpenAI API ;
- pas d'envoi reel d'email ;
- pas de relance automatique.
