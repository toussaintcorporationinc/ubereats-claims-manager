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

## Authentification

Tous les endpoints `/v1/*` sont proteges par un token Bearer, sauf :

- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `GET /v1/email/gmail/oauth/callback`, protege par `state` OAuth signe

`GET /health` reste public.

### Bootstrap premier owner

- `POST /v1/auth/register`

Body :

```json
{
  "email": "owner@example.com",
  "password": "mot-de-passe-long",
  "full_name": "Owner"
}
```

Ce endpoint cree uniquement le premier utilisateur owner. Si un utilisateur existe deja, l'inscription publique est refusee.

### Login

- `POST /v1/auth/login`

Retour :

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "owner@example.com",
    "full_name": "Owner",
    "role": "owner",
    "active": true,
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:00:00Z"
  }
}
```

### Utilisateur courant

- `GET /v1/auth/me`

## Users

Endpoints reserves au role `owner` :

- `GET /v1/users`
- `POST /v1/users`
- `GET /v1/users/{id}`
- `PATCH /v1/users/{id}`
- `POST /v1/users/{id}/restaurants`
- `DELETE /v1/users/{id}/restaurants/{restaurant_id}`

Roles autorises :

- `owner`
- `manager`
- `staff`

`POST /v1/users` cree un utilisateur interne avec mot de passe hash et ajoute un `AuditLog`.

`POST /v1/users/{id}/restaurants` assigne un restaurant a un manager ou staff via `UserRestaurantAccess` et ajoute un `AuditLog`.

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

Acces :

- `owner` voit et gere tous les restaurants ;
- `manager` et `staff` voient uniquement les restaurants assignes ;
- seul `owner` peut creer ou modifier un restaurant.

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

Acces :

- `owner` voit et modifie toutes les commandes ;
- `manager` voit et modifie les commandes des restaurants assignes ;
- `staff` voit les commandes des restaurants assignes, peut creer une commande et ajouter des preuves, mais ne peut pas modifier, valider ou generer de brouillon.

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

La validation est autorisee pour `owner` et `manager`.

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
- `POST /v1/orders/{id}/evidence` pour compatibilite metadonnees
- `POST /v1/orders/{id}/evidence/upload`
- `GET /v1/evidence/{id}/download`

Types autorises :

- `receipt`
- `cancellation_proof`
- `preparation_proof`
- `waste_photo`
- `uber_screenshot`
- `other`

L'ajout d'une preuve ajoute un `AuditLog`.

L'ajout d'une preuve est autorise aux utilisateurs ayant acces au restaurant de la commande.

### Upload fichier preuve

`POST /v1/orders/{id}/evidence/upload`

Content-Type : `multipart/form-data`

Champs :

- `evidence_type`
- `file`

Formats acceptes :

- `application/pdf`
- `image/jpeg`
- `image/png`
- `image/webp`
- `image/heic`
- `image/heif`

Extensions acceptees :

- `.pdf`
- `.jpg`
- `.jpeg`
- `.png`
- `.webp`
- `.heic`
- `.heif`

Reponse :

```json
{
  "id": 123,
  "order_id": 456,
  "evidence_type": "cancellation_proof",
  "original_filename": "capture-annulation.png",
  "storage_path": "restaurant_1/order_456/...",
  "storage_backend": "local",
  "mime_type": "image/png",
  "file_size": 123456,
  "checksum_sha256": "...",
  "uploaded_by_user_id": 1,
  "uploaded_at": "2026-06-07T10:00:00Z",
  "created_at": "2026-06-07T10:00:00Z",
  "deleted_at": null,
  "download_url": "/v1/evidence/123/download"
}
```

Regles :

- le fichier vide est refuse ;
- les fichiers trop lourds sont refuses selon `MAX_EVIDENCE_FILE_SIZE_MB` ;
- l'extension et le MIME sont controles ;
- le nom utilisateur n'est jamais utilise comme chemin disque ;
- le telechargement exige un token et les droits sur le restaurant de la commande.

### Download preuve

`GET /v1/evidence/{id}/download`

Endpoint protege. La reponse retourne le fichier si l'utilisateur a acces au restaurant de la commande.

## Imports commandes

- `POST /v1/imports/orders/preview`
- `GET /v1/imports`
- `GET /v1/imports/{id}`
- `GET /v1/imports/{id}/rows`
- `POST /v1/imports/{id}/confirm`
- `POST /v1/imports/{id}/cancel`

Formats acceptes :

- `.csv`
- `.xlsx`

Colonnes minimales :

- `restaurant_id` ou `restaurant_name`
- `uber_order_number`
- `order_amount`

Le preview ne cree aucune commande. Il cree un batch d'import avec les lignes parsees et limite `rows_preview` a 50 lignes.

### Preview import

`POST /v1/imports/orders/preview`

Content-Type : `multipart/form-data`

Champs :

- `file`

Reponse :

```json
{
  "batch_id": 123,
  "status": "parsed",
  "original_filename": "commandes_annulees.xlsx",
  "total_rows": 100,
  "valid_rows": 80,
  "invalid_rows": 10,
  "duplicate_rows": 5,
  "unauthorized_rows": 5,
  "created_orders_count": 0,
  "rows_preview": [
    {
      "id": 1,
      "batch_id": 123,
      "row_number": 2,
      "status": "valid",
      "normalized_data": {},
      "errors": [],
      "warnings": []
    }
  ]
}
```

### Lignes import

`GET /v1/imports/{id}/rows`

Query params :

- `status`
- `limit`
- `offset`

### Confirmation

`POST /v1/imports/{id}/confirm`

La confirmation cree uniquement les lignes `valid`. Les lignes `invalid`, `duplicate`, `unauthorized` et `skipped` ne creent pas de commande.

```json
{
  "batch_id": 123,
  "status": "confirmed",
  "created_orders_count": 80,
  "skipped_rows": 20,
  "errors": []
}
```

Regles :

- un utilisateur non connecte ne peut pas importer ;
- `owner` peut importer pour tous les restaurants ;
- `manager` et `staff` importent uniquement pour les restaurants assignes ;
- les doublons existants et internes au fichier sont detectes ;
- le meme numero Uber est autorise sur deux restaurants differents ;
- les montants francais comme `12,50` et `1 234,56` sont normalises ;
- les dates `YYYY-MM-DD` et `DD/MM/YYYY` sont acceptees ;
- les heures `HH:MM` sont acceptees.

## Drafts

- `GET /v1/drafts`
- `GET /v1/orders/{id}/drafts`
- `POST /v1/orders/{id}/drafts`

Les brouillons sont internes. Aucun envoi reel d'email n'est implemente.

La creation de brouillon est autorisee a `owner` et `manager`. `staff` peut consulter les brouillons des restaurants assignes, mais ne peut pas en generer.

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
  "provider": null,
  "provider_status": null,
  "provider_draft_id": null,
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

### Liste globale des brouillons

`GET /v1/drafts`

Retourne tous les brouillons internes avec les informations minimales utiles a l'administration.

```json
[
  {
    "id": 123,
    "order_id": 456,
    "draft_type": "initial_claim",
    "subject": "Demande de paiement - commande annulee apres preparation - UBER-123",
    "status": "created",
    "created_at": "2026-06-07T10:00:00Z",
    "restaurant_name": "Restaurant Exemple",
    "uber_order_number": "UBER-123",
    "provider": "gmail",
    "provider_status": "provider_draft_created",
    "provider_draft_id": "r123..."
  }
]
```

## Gmail drafts

L'integration Gmail est limitee a la creation de brouillons dans Gmail. Elle n'envoie jamais l'email.

Variables attendues :

- `EMAIL_PROVIDER_ENABLED`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_OAUTH_REDIRECT_URI`
- `GMAIL_SCOPES`
- `DEFAULT_UBER_EATS_SUPPORT_EMAIL`
- `EMAIL_MAX_ATTACHMENT_TOTAL_MB`

### Status Gmail

- `GET /v1/email/gmail/status`

Retour :

```json
{
  "connected": false,
  "email_address": null,
  "provider": "gmail",
  "enabled": false
}
```

### Demarrer OAuth Gmail

- `GET /v1/email/gmail/oauth/start`

Retourne une URL d'autorisation Google si le provider est active et configure.

```json
{
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

### Callback OAuth Gmail

- `GET /v1/email/gmail/oauth/callback?code=...&state=...`

Le callback verifie le `state` signe, echange le code OAuth, stocke les tokens sous forme protegee et retourne une page HTML simple.

### Deconnexion Gmail

- `POST /v1/email/gmail/disconnect`

Deconnecte le compte Gmail de l'utilisateur courant sans supprimer l'historique des brouillons provider.

### Creer un brouillon Gmail

- `POST /v1/drafts/{draft_id}/gmail-draft`

Body :

```json
{
  "to_email": "merchants@uber.com",
  "include_evidence": true
}
```

Reponse :

```json
{
  "id": 12,
  "email_draft_id": 123,
  "provider": "gmail",
  "provider_draft_id": "r123...",
  "provider_thread_id": "thread-123",
  "to_email": "merchants@uber.com",
  "subject": "Demande de paiement - commande annulee apres preparation - UBER-123",
  "status": "provider_draft_created",
  "created_by_user_id": 1,
  "error_message": null,
  "created_at": "2026-06-08T10:00:00Z",
  "updated_at": "2026-06-08T10:00:00Z"
}
```

Regles :

- `owner` peut creer un brouillon Gmail pour tous les restaurants ;
- `manager` peut creer un brouillon Gmail pour ses restaurants assignes ;
- `staff` ne peut pas creer de brouillon Gmail ;
- un compte Gmail connecte est obligatoire ;
- les preuves sont jointes si `include_evidence=true` ;
- la limite totale de pieces jointes est controlee par `EMAIL_MAX_ATTACHMENT_TOTAL_MB` ;
- chaque creation ajoute un `AuditLog`.

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

`owner` obtient une vue globale. `manager` et `staff` obtiennent une vue filtree sur leurs restaurants assignes.

## Hors perimetre V1 actuelle

- pas d'integration OpenAI API ;
- pas d'envoi reel d'email ;
- pas d'envoi automatique Gmail ;
- pas de generation d'email par la validation ;
- pas de relance automatique.
