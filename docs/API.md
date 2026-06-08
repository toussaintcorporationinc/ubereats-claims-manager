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
  "provider_message_id": null,
  "provider_sent_at": null,
  "provider_to_email": null,
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
    "provider_draft_id": "r123...",
    "provider_message_id": null,
    "provider_sent_at": null,
    "provider_to_email": "merchants@uber.com"
  }
]
```

## Gmail drafts

L'integration Gmail cree des brouillons dans Gmail et peut envoyer un brouillon uniquement apres confirmation manuelle explicite.

Variables attendues :

- `EMAIL_PROVIDER_ENABLED`
- `GMAIL_OAUTH_CLIENT_ID`
- `GMAIL_OAUTH_CLIENT_SECRET`
- `GMAIL_OAUTH_REDIRECT_URI`
- `GMAIL_SCOPES`
- `DEFAULT_UBER_EATS_SUPPORT_EMAIL`
- `EMAIL_MAX_ATTACHMENT_TOTAL_MB`
- `GMAIL_INBOUND_SYNC_ENABLED`
- `GMAIL_INBOUND_SYNC_LOOKBACK_DAYS`
- `GMAIL_INBOUND_MAX_MESSAGES_PER_SYNC`
- `GMAIL_SUPPORT_SENDER_FILTER`

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
  "provider_message_id": null,
  "to_email": "merchants@uber.com",
  "subject": "Demande de paiement - commande annulee apres preparation - UBER-123",
  "status": "provider_draft_created",
  "created_by_user_id": 1,
  "sent_by_user_id": null,
  "sent_at": null,
  "error_message": null,
  "last_error": null,
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

### Envoyer manuellement un brouillon Gmail

- `POST /v1/email/gmail/provider-drafts/{provider_draft_id}/send`

Body :

```json
{
  "confirm_send": true
}
```

Reponse :

```json
{
  "provider_draft_id": "r123...",
  "status": "sent",
  "provider_message_id": "msg-123",
  "provider_thread_id": "thread-123",
  "sent_at": "2026-06-08T10:30:00Z"
}
```

Regles :

- aucun envoi n'est automatique ;
- `confirm_send` doit valoir `true` ;
- `EMAIL_PROVIDER_ENABLED` doit etre actif ;
- le brouillon Gmail doit exister en base comme `EmailProviderDraft` connu ;
- un compte Gmail connecte est obligatoire ;
- `owner` peut envoyer pour tous les restaurants accessibles globalement ;
- `manager` peut envoyer uniquement pour ses restaurants assignes ;
- `staff` ne peut pas envoyer ;
- un brouillon deja `sent` est refuse ;
- un brouillon `failed` est refuse, aucun retry automatique n'est lance ;
- les commandes finales `accepted`, `payment_confirmed`, `refused` et `closed` sont refusees ;
- un envoi reussi met `EmailProviderDraft.status` a `sent`, renseigne `sent_at`, `sent_by_user_id`, `provider_message_id` si disponible, passe la commande a `sent`, cree un `EmailThread` outbound et ajoute un `AuditLog` ;
- un echec provider controle met le brouillon a `failed`, renseigne `last_error` et ajoute un `AuditLog` `send_gmail_draft_failed`.

## Gmail inbound replies

La sync inbound lit les reponses Gmail apres envoi manuel d'une reclamation. Elle ne repond jamais automatiquement et ne modifie pas Gmail cote utilisateur.

Variables attendues :

- `EMAIL_PROVIDER_ENABLED=false` par defaut ;
- `GMAIL_INBOUND_SYNC_ENABLED=false` par defaut ;
- `GMAIL_INBOUND_SYNC_LOOKBACK_DAYS=30` ;
- `GMAIL_INBOUND_MAX_MESSAGES_PER_SYNC=100` ;
- `GMAIL_SUPPORT_SENDER_FILTER=uber.com` ;
- `GMAIL_SCOPES` doit inclure `https://www.googleapis.com/auth/gmail.readonly` en plus des scopes de brouillon/envoi.

Les comptes connectes avant l'ajout de `gmail.readonly` doivent se reconnecter pour autoriser la lecture.

### Status inbound

- `GET /v1/email/gmail/inbound/status`

```json
{
  "enabled": true,
  "connected": true,
  "last_sync_at": "2026-06-08T10:00:00Z",
  "last_success_at": "2026-06-08T10:00:00Z",
  "status": "success",
  "last_error": null
}
```

### Synchroniser les reponses Gmail

- `POST /v1/email/gmail/inbound/sync`

Body optionnel :

```json
{
  "lookback_days": 30,
  "max_messages": 100
}
```

Reponse :

```json
{
  "status": "success",
  "synced_messages": 10,
  "linked_messages": 7,
  "unlinked_messages": 2,
  "ignored_messages": 1,
  "errors": []
}
```

Regles :

- `owner` et `manager` peuvent lancer la sync ;
- `staff` ne peut pas lancer la sync ;
- `EMAIL_PROVIDER_ENABLED` et `GMAIL_INBOUND_SYNC_ENABLED` doivent etre actifs ;
- un compte Gmail connecte est obligatoire ;
- les messages sont dedupliques par `email_account_id` + `provider_message_id` ;
- un message est rattache par `provider_thread_id` si un `EmailThread` ou `EmailProviderDraft` connu existe ;
- sinon, le numero Uber est recherche dans le sujet puis le corps ;
- si aucun rattachement fiable n'existe, le message reste `unlinked` ;
- les messages sortants de notre propre compte Gmail sont marques `ignored`.

Si un message inbound est rattache et que la commande est `sent` ou `waiting_uber_response`, le statut passe a `response_received`. Les statuts finaux `accepted`, `payment_confirmed`, `refused` et `closed` restent inchanges.

### Liste messages inbound

- `GET /v1/email/inbound-messages`

Query params :

- `match_status`
- `order_id`
- `limit`
- `offset`

`owner` voit tout. `manager` voit les messages lies a ses restaurants assignes et ses messages non rattaches. `staff` voit seulement les messages lies aux restaurants assignes.

### Historique email commande

- `GET /v1/orders/{order_id}/email-messages`

Retourne les `EmailThread` inbound/outbound et les `InboundEmailMessage` rattaches a la commande.

### Rattachement manuel

- `POST /v1/email/inbound-messages/{message_id}/link`

Body :

```json
{
  "order_id": 123
}
```

Regles :

- `owner` peut rattacher un message a toute commande ;
- `manager` peut rattacher uniquement vers ses restaurants assignes ;
- `staff` ne peut pas rattacher ;
- le message passe a `match_status=linked` et `match_reason=manual_link` ;
- un `EmailThread` inbound et un `AuditLog` sont crees.

## Traitement manuel des reponses Uber

Le traitement manuel transforme une reponse Uber rattachee en decision commerciale sur la commande. Il ne lit pas Gmail, ne repond pas a Uber et n'envoie aucun email.

### Creer une revue de reponse

- `POST /v1/orders/{order_id}/response-reviews`

Body :

```json
{
  "inbound_message_id": 123,
  "review_type": "accepted",
  "recovered_amount": "24.90",
  "expected_payment_date": "2026-06-15",
  "refusal_reason": null,
  "evidence_requested": null,
  "notes": "Remboursement annonce par Uber"
}
```

Reponse :

```json
{
  "id": 1,
  "order_id": 456,
  "inbound_message_id": 123,
  "reviewed_by_user_id": 2,
  "review_type": "accepted",
  "previous_order_status": "response_received",
  "new_order_status": "accepted",
  "recovered_amount": "24.90",
  "expected_payment_date": "2026-06-15",
  "refusal_reason": null,
  "evidence_requested": null,
  "notes": "Remboursement annonce par Uber",
  "created_at": "2026-06-08T10:00:00Z",
  "updated_at": "2026-06-08T10:00:00Z"
}
```

Types `review_type` autorises :

- `accepted`
- `payment_to_verify`
- `payment_confirmed`
- `refused`
- `evidence_requested`
- `information_requested`
- `followup_needed`
- `ignored`
- `manual_review`

Transitions appliquees :

- `accepted` -> commande `accepted`, `result=accepted` ;
- `payment_to_verify` -> commande `payment_to_verify`, `result=payment_to_verify` ;
- `payment_confirmed` -> commande `payment_confirmed`, `result=payment_confirmed` ;
- `refused` -> commande `refused`, `result=refused` ;
- `evidence_requested` -> commande `manual_review`, `result=evidence_requested` ;
- `information_requested` -> commande `manual_review`, `result=information_requested` ;
- `followup_needed` -> commande `manual_review`, `result=followup_needed` ;
- `manual_review` -> commande `manual_review`, `result=manual_review` ;
- `ignored` ne change pas le statut ni le resultat de la commande.

Regles :

- seuls `owner` et `manager` peuvent creer une revue ;
- `manager` est limite a ses restaurants assignes ;
- `staff` ne peut pas traiter une reponse ;
- `payment_confirmed` et `closed` sont proteges contre une nouvelle decision non ignoree ;
- si `inbound_message_id` est fourni, le message passe a `review_status=reviewed` ou `review_status=ignored` ;
- chaque revue cree un `AuditLog`.

### Lister les revues d'une commande

- `GET /v1/orders/{order_id}/response-reviews`

Retourne les `ClaimResponseReview` de la commande.

### Lister les revues visibles

- `GET /v1/response-reviews`

Query params :

- `review_type`
- `restaurant_id`
- `order_id`
- `limit`
- `offset`

`owner` voit tout. `manager` voit les revues des restaurants assignes. `staff` n'a pas acces a cette liste globale.

## Follow-ups controles

Les relances controlees creent des taches et des brouillons. Elles ne declenchent aucun envoi automatique.

Politique par defaut :

- `followup_1` : J+2 apres premier envoi ;
- `followup_2` : J+5 apres premier envoi si `followup_1` existe ;
- `escalation` : J+10 apres premier envoi si `followup_1` et `followup_2` existent ;
- `manual_review` : J+15, limite de relances atteinte ou reponse inbound non traitee.

Variables :

- `FOLLOWUP_1_DELAY_DAYS=2`
- `FOLLOWUP_2_DELAY_DAYS=5`
- `ESCALATION_DELAY_DAYS=10`
- `MANUAL_REVIEW_AFTER_DAYS=15`
- `MAX_FOLLOWUPS_PER_ORDER=3`
- `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false`

`FOLLOWUP_AUTOMATIC_SEND_ENABLED` ne declenche aucun envoi dans cette V1.

### Lister les taches

- `GET /v1/followups/due`

Query params :

- `restaurant_id`
- `status`
- `task_type`
- `limit`
- `offset`

Retour :

```json
{
  "tasks": [
    {
      "id": 1,
      "order_id": 123,
      "restaurant_id": 10,
      "restaurant_name": "Restaurant Test",
      "uber_order_number": "UBER-TEST-001",
      "order_amount": "24.90",
      "currency": "EUR",
      "claim_status": "waiting_uber_response",
      "retry_count": 0,
      "next_action_at": "2026-06-03T10:00:00Z",
      "last_followup_sent_at": null,
      "task_type": "followup_1",
      "status": "pending",
      "due_at": "2026-06-03T10:00:00Z",
      "generated_email_draft_id": null,
      "generated_provider_draft_id": null
    }
  ],
  "limit": 50,
  "offset": 0
}
```

### Recalculer les relances

- `POST /v1/followups/recalculate`

Body optionnel :

```json
{
  "restaurant_id": 123,
  "dry_run": false
}
```

Retour :

```json
{
  "created_tasks": 10,
  "skipped_orders": 5,
  "manual_review_orders": 2,
  "errors": []
}
```

Regles :

- `owner` peut recalculer tous les restaurants ;
- `manager` peut recalculer ses restaurants assignes ;
- `staff` ne peut pas recalculer ;
- aucun doublon `order_id + task_type` n'est cree ;
- les statuts finaux `accepted`, `payment_confirmed`, `refused`, `closed` sont ignores ;
- une reponse inbound non traitee propose `manual_review` avant relance.

### Creer le brouillon interne

- `POST /v1/followups/{task_id}/create-draft`

Regles :

- `owner` ou `manager` seulement ;
- la tache doit etre `pending` ;
- `followup_1`, `followup_2` et `escalation` creent un `EmailDraft` ;
- `manual_review` ne cree pas d'email et passe la commande en `manual_review` ;
- aucun email n'est envoye.

### Creer le brouillon Gmail

- `POST /v1/followups/{task_id}/create-gmail-draft`

Regles :

- `owner` ou `manager` seulement ;
- un brouillon interne doit deja exister ;
- le compte Gmail doit etre connecte et provider actif ;
- cree un `EmailProviderDraft` ;
- aucun email n'est envoye.

### Ignorer une relance

- `POST /v1/followups/{task_id}/skip`

Body :

```json
{
  "skip_reason": "Deja traite manuellement"
}
```

### Marquer terminee

- `POST /v1/followups/{task_id}/complete`

Si le provider draft lie est deja `sent`, la commande est mise a jour :

- `followup_1` -> `followup_1_sent` ;
- `followup_2` -> `followup_2_sent` ;
- `escalation` -> `escalation_sent` ;
- `retry_count` est incremente ;
- `last_followup_sent_at` et `next_action_at` sont mis a jour.

Chaque action cree un `AuditLog`.

## Dashboard

- `GET /v1/dashboard/summary`

Retourne :

- `total_orders`
- `total_claimed_amount`
- `total_recovered_amount`
- `total_pending_amount`
- `total_refused_amount`
- `accepted_count`
- `payment_to_verify_count`
- `payment_confirmed_count`
- `refused_count`
- `manual_review_count`
- `pending_response_count`
- `followups_due_count`
- `followups_pending_count`
- `escalations_due_count`
- `manual_review_due_count`
- `orders_by_status`
- `orders_by_restaurant`

`owner` obtient une vue globale. `manager` et `staff` obtiennent une vue filtree sur leurs restaurants assignes.

## Hors perimetre V1 actuelle

- pas d'integration OpenAI API ;
- pas d'envoi automatique Gmail ;
- pas de generation d'email par la validation ;
- pas de relance automatique.
