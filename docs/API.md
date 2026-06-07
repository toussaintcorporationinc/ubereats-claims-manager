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
- `POST /v1/orders/{id}/validate`

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

### Validation d'un dossier

`POST /v1/orders/{id}/validate`

Verifie si la commande est prete pour une reclamation. La validation ne genere aucun email et ne lance aucune relance.

Reponse complete :

```json
{
  "order_id": 123,
  "is_complete": true,
  "previous_status": "draft",
  "new_status": "ready_to_send",
  "missing_items": [],
  "blocking_reasons": []
}
```

Un dossier complet doit avoir :

- un restaurant ;
- un numero de commande Uber Eats ;
- un montant ;
- une devise ;
- au moins une preuve `cancellation_proof` ;
- au moins une preuve `preparation_proof` ou `waste_photo` ;
- un statut non final.

Si le dossier est incomplet, son statut devient `missing_evidence`, la reponse contient `missing_items` et `blocking_reasons`, et un `AuditLog` est cree.

Si le dossier est complet, son statut devient `ready_to_send` et un `AuditLog` est cree.

Statuts finaux non revalidables :

- `accepted`
- `payment_confirmed`
- `refused`
- `closed`

Elements manquants possibles :

- `restaurant`
- `uber_order_number`
- `order_amount`
- `currency`
- `cancellation_proof`
- `preparation_or_waste_proof`

Raisons bloquantes possibles :

- `missing_restaurant`
- `missing_uber_order_number`
- `missing_order_amount`
- `missing_currency`
- `missing_cancellation_proof`
- `missing_preparation_or_waste_proof`
- `final_status_cannot_be_validated`
- `order_not_found`

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
- `POST /v1/orders/{id}/drafts`

Les brouillons sont internes. Aucun envoi reel d'email n'est implemente.

Types prevus :

- `initial_claim`
- `followup_1`
- `followup_2`
- `escalation`
- `proof_reply`

### Creation d'un brouillon

`POST /v1/orders/{id}/drafts`

Body :

```json
{
  "draft_type": "initial_claim"
}
```

Reponse :

```json
{
  "id": 123,
  "order_id": 456,
  "draft_type": "initial_claim",
  "subject": "Demande de paiement - commande annulee apres preparation - UBER-123",
  "body": "...",
  "status": "created",
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

Regles :

- `initial_claim` exige une commande `ready_to_send`, complete selon le service de validation, avec restaurant, numero Uber, montant, devise, preuve d'annulation et preuve de preparation ou gaspillage ;
- si `initial_claim` est cree, la commande passe a `draft_email_created` ;
- `followup_1` exige un brouillon `initial_claim` et un statut `draft_email_created`, `sent` ou `waiting_uber_response` ;
- `followup_2` exige des brouillons `initial_claim` et `followup_1` ;
- `escalation` exige un brouillon `initial_claim` et un statut non final ;
- `proof_reply` exige au moins une preuve rattachee et un statut non final ;
- les statuts finaux `accepted`, `payment_confirmed`, `refused` et `closed` refusent toute generation de brouillon ;
- chaque creation ajoute un `AuditLog` avec `action = create_email_draft`.

Les brouillons sont generes depuis des templates locaux. Les champs optionnels absents ne sont pas inventes ni ajoutes au corps du message.

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
- pas de generation d'email par la validation ;
- pas de relance automatique.
