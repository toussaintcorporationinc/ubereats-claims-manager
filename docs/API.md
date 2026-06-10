# API - TENNET

Base URL locale backend : `http://localhost:8000`

## Health

- `GET /health`
- `GET /ready`
- `GET /version`

Retour attendu :

```json
{
  "status": "ok",
  "service": "TENNET"
}
```

`GET /ready` verifie que le backend peut joindre la base de donnees et ecrire dans les dossiers de stockage evidence/import.

Retour attendu :

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "evidence_storage": "ok",
    "import_storage": "ok"
  }
}
```

`GET /version` retourne uniquement des informations non sensibles :

```json
{
  "app": "TENNET",
  "version": "1.1.0-tennet",
  "environment": "production",
  "commit": "unknown"
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
- `active` vaut `true` par defaut ;
- `autopilot_enabled` vaut `false` par defaut et doit etre active explicitement par restaurant.

La creation d'un restaurant ajoute un `AuditLog`.

Acces :

- `owner` voit et gere tous les restaurants ;
- `manager` et `staff` voient uniquement les restaurants assignes ;
- seul `owner` peut creer ou modifier un restaurant.

## AutoPilot

Endpoints reserves aux roles `owner` et `manager` :

- `GET /v1/autopilot/status`
- `POST /v1/autopilot/dry-run`
- `POST /v1/autopilot/run`
- `POST /v1/autopilot/stop`
- `GET /v1/autopilot/runs`
- `GET /v1/autopilot/runs/{id}`
- `GET /v1/autopilot/actions`

Body de run :

```json
{
  "mode": "initial_claims",
  "restaurant_id": 123,
  "dry_run": true
}
```

Modes autorises : `initial_claims`, `followups`, `appeals`, `all`.

Regles :

- `dry-run` cree une previsualisation sans envoyer ;
- `run` refuse si `AUTOPILOT_ENABLED=false` ;
- Gmail doit etre active et connecte si `AUTOPILOT_REQUIRE_GMAIL_CONNECTED=true` ;
- chaque restaurant doit avoir `autopilot_enabled=true` ;
- les limites quotidiennes et par restaurant sont appliquees ;
- `stop` active un arret d'urgence persistant ;
- aucun secret Gmail ou token n'est retourne.

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

## Evidence request tasks

Les demandes de preuves structurent les justificatifs manquants avant validation ou apres reconciliation Uber. Elles ne creent aucun email et ne declenchent aucun envoi.

Endpoints :

- `POST /v1/evidence-tasks/recalculate`
- `GET /v1/evidence-tasks`
- `GET /v1/evidence-tasks/{task_id}`
- `POST /v1/evidence-tasks/{task_id}/upload`
- `POST /v1/evidence-tasks/{task_id}/skip`
- `POST /v1/evidence-tasks/{task_id}/complete`
- `POST /v1/evidence-tasks/{task_id}/upload-link`
- `GET /v1/evidence-upload-links/{token}`
- `POST /v1/evidence-upload-links/{token}/upload`
- `POST /v1/evidence-upload-links/{id}/revoke`

Types de preuves geres :

- `receipt`
- `cancellation_proof`
- `preparation_proof`
- `waste_photo`
- `uber_screenshot`
- `other`

Statuts :

- `pending`
- `uploaded`
- `completed`
- `skipped`
- `cancelled`

Priorites :

- `low`
- `normal`
- `high`
- `urgent`

### Recalculer les demandes

`POST /v1/evidence-tasks/recalculate`

Body optionnel :

```json
{
  "restaurant_id": 123,
  "order_id": 456,
  "dry_run": false
}
```

Retour :

```json
{
  "created_tasks": 2,
  "existing_tasks": 0,
  "completed_tasks": 0,
  "skipped_orders": 1,
  "errors": []
}
```

Regles :

- `owner` peut recalculer tous les restaurants ;
- `manager` peut recalculer uniquement ses restaurants assignes ;
- `staff` ne peut pas recalculer ;
- les statuts finaux `accepted`, `payment_confirmed`, `refused`, `closed` sont ignores ;
- TENNET cree des taches pour `cancellation_proof` et `preparation_proof` ou `waste_photo` quand elles bloquent la validation ;
- les resultats Uber reconciliation avec `evidence_required=true` alimentent la priorite si un `ClaimOrder` existe ;
- aucune tache active en doublon n'est creee pour la meme commande et le meme type de preuve.

### Lister les demandes

`GET /v1/evidence-tasks`

Query params :

- `restaurant_id`
- `status`
- `required_evidence_type`
- `priority`
- `assigned_to_me`
- `limit`
- `offset`

`owner` voit tout. `manager` et `staff` voient uniquement les restaurants assignes.

### Upload depuis une demande protegee

`POST /v1/evidence-tasks/{task_id}/upload`

Content-Type : `multipart/form-data`

Champs :

- `file`

Retour :

```json
{
  "task": {
    "id": 1,
    "order_id": 123,
    "restaurant_id": 12,
    "task_type": "missing_cancellation_proof",
    "required_evidence_type": "cancellation_proof",
    "title": "Preuve d'annulation requise",
    "status": "completed"
  },
  "evidence_file": {
    "id": 10,
    "order_id": 123,
    "evidence_type": "cancellation_proof",
    "checksum_sha256": "..."
  },
  "validation": {
    "order_id": 123,
    "is_complete": false,
    "missing_items": ["preparation_or_waste_proof"],
    "blocking_reasons": ["missing_preparation_or_waste_proof"]
  }
}
```

L'upload utilise les memes controles que `POST /v1/orders/{id}/evidence/upload`, marque la tache comme `completed`, cree un `AuditLog` et relance la validation du dossier.

### Lien mobile tokenise

`POST /v1/evidence-tasks/{task_id}/upload-link`

Body optionnel :

```json
{
  "expires_in_hours": 48,
  "max_uses": 3
}
```

Retour :

```json
{
  "id": 5,
  "task_id": 1,
  "expires_at": "2026-06-12T10:00:00Z",
  "max_uses": 3,
  "use_count": 0,
  "token": "raw-token-returned-once",
  "upload_url": "https://app.example.com/evidence-upload/raw-token-returned-once"
}
```

Regles :

- seuls `owner` et `manager` peuvent creer ou revoquer un lien ;
- le token brut n'est jamais stocke, seul `token_hash` est conserve ;
- le token brut est retourne uniquement a la creation ;
- le lien public est limite par expiration, nombre d'usages et statut de la tache ;
- l'upload public n'exige pas de JWT mais ne peut ajouter que le type de preuve demande ;
- un upload public cree `EvidenceFile`, complete la tache, audite l'action et relance la validation ;
- `POST /v1/evidence-upload-links/{id}/revoke` revoque un lien sans supprimer l'historique.

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

## Reports commerciaux et exports

Les rapports commerciaux sont reserves aux roles `owner` et `manager`. `owner` voit tous les restaurants. `manager` voit uniquement ses restaurants assignes. `staff` ne peut pas acceder aux rapports commerciaux ni aux exports.

Filtres communs :

- `restaurant_id`
- `date_from`
- `date_to`
- `status`
- `result`
- `min_amount`
- `max_amount`
- `include_customer_names=false`

Une requete avec un `restaurant_id` non autorise retourne `403`.

### Resume commercial

- `GET /v1/reports/commercial-summary`

Retour :

```json
{
  "filters": {},
  "totals": {
    "orders_count": 0,
    "total_claimed_amount": "0.00",
    "total_recovered_amount": "0.00",
    "total_pending_amount": "0.00",
    "total_refused_amount": "0.00",
    "average_claim_amount": "0.00",
    "success_rate": "0.00"
  },
  "by_status": [],
  "by_result": [],
  "by_restaurant": [],
  "followups": {
    "due_count": 0,
    "pending_count": 0,
    "escalation_due_count": 0,
    "manual_review_count": 0
  },
  "responses": {
    "accepted_count": 0,
    "refused_count": 0,
    "payment_to_verify_count": 0,
    "payment_confirmed_count": 0,
    "manual_review_count": 0
  },
  "customer_refunds": {
    "total_deducted_amount": "0.00",
    "disputes_count": 0,
    "needs_evidence_count": 0,
    "evidence_ready_count": 0,
    "sent_count": 0,
    "accepted_count": 0,
    "refused_count": 0
  }
}
```

Definitions :

- `total_claimed_amount` : somme `ClaimOrder.order_amount` ;
- `total_recovered_amount` : somme `ClaimOrder.recovered_amount` ;
- `total_pending_amount` : montant des dossiers non finaux et non confirmes payes ;
- `total_refused_amount` : montant des dossiers `refused` ;
- `success_rate` : dossiers `accepted` ou `payment_confirmed` divises par dossiers traites `accepted`, `payment_confirmed` ou `refused`.

`by_restaurant` contient `restaurant_id`, `restaurant_name`, `orders_count`, `claimed_amount`, `recovered_amount`, `pending_amount`, `refused_amount`, `accepted_count`, `refused_count` et `manual_review_count`.

### Commandes reportees

- `GET /v1/reports/orders`

Retour pagine :

- `order_id`
- `restaurant_name`
- `uber_order_number`
- `order_date`
- `order_amount`
- `currency`
- `status`
- `result`
- `recovered_amount`
- `retry_count`
- `last_followup_sent_at`
- `next_action_at`
- `evidence_count`
- `drafts_count`
- `inbound_messages_count`
- `response_reviews_count`

`customer_name` est absent par defaut. Il est retourne uniquement avec `include_customer_names=true` pour un `owner` ou `manager`.

### Relances reportees

- `GET /v1/reports/followups`

Retourne les taches de relance visibles avec `task_id`, `restaurant_name`, `order_id`, `uber_order_number`, `task_type`, `task_status`, `due_at`, `claim_status`, `order_amount`, `currency` et `retry_count`.

### Reponses traitees reportees

- `GET /v1/reports/responses`

Retourne les revues de reponses visibles avec `review_id`, `restaurant_name`, `order_id`, `uber_order_number`, `review_type`, anciens/nouveaux statuts, `recovered_amount`, `refusal_reason`, `evidence_requested`, `created_at` et `reviewed_by_user_id`.

### Exports

- `GET /v1/reports/export/orders.csv`
- `GET /v1/reports/export/orders.xlsx`
- `GET /v1/reports/export/followups.csv`
- `GET /v1/reports/export/responses.csv`
- `GET /v1/reports/export/commercial-summary.xlsx`

Les exports appliquent les memes filtres et permissions que les endpoints JSON. `EXPORT_MAX_ROWS` limite le nombre de lignes exportables. Si la limite est depassee, l'API retourne une erreur claire et demande des filtres plus precis.

L'export `commercial-summary.xlsx` contient plusieurs feuilles :

- `Summary`
- `By Restaurant`
- `By Status`
- `By Result`
- `Followups`
- `Responses`

Les exports n'incluent jamais les tokens Gmail, secrets, chemins disque bruts de preuves ou champs `access_token` / `refresh_token`.

## Deductions Uber et remboursements clients

Le module Customer Refund Disputes detecte des deductions dans les transactions financieres Uber importees. Il ne scrape pas Uber Eats Manager, ne demande aucun mot de passe Uber et ne declenche aucun email automatique.

Permissions :

- `owner` : detection, creation de dossiers, brouillons, brouillons Gmail et ignore sur tous les restaurants ;
- `manager` : memes actions sur restaurants assignes ;
- `staff` : peut consulter et uploader des preuves via les taches autorisees, mais ne peut pas detecter, creer de dossier, brouillon, brouillon Gmail ou ignorer.

Endpoints :

- `POST /v1/customer-refunds/detect`
- `GET /v1/customer-refunds`
- `GET /v1/customer-refunds/{id}`
- `POST /v1/customer-refunds/{id}/recalculate-evidence`
- `POST /v1/customer-refunds/{id}/create-claim-order`
- `POST /v1/customer-refunds/{id}/create-draft`
- `POST /v1/customer-refunds/{id}/create-gmail-draft`
- `POST /v1/customer-refunds/{id}/reviews`
- `GET /v1/customer-refunds/{id}/reviews`
- `GET /v1/customer-refund-reviews`
- `POST /v1/customer-refunds/{id}/ignore`
- `POST /v1/customer-refunds/bulk-create-claim-orders`
- `POST /v1/customer-refunds/bulk-create-drafts`

### Detecter les deductions

`POST /v1/customer-refunds/detect`

Body optionnel :

```json
{
  "restaurant_id": 123,
  "date_from": "2026-01-01",
  "date_to": "2026-06-30"
}
```

Retour :

```json
{
  "detected_count": 10,
  "needs_evidence_count": 8,
  "manual_review_count": 2,
  "total_deducted_amount": "250.75",
  "errors": []
}
```

La detection analyse les `UberFinancialTransaction` negatives ou de type `refund`, `chargeback`, `adjustment_negative`, `eater_refund` ou `order_error`. Les motifs reconnus incluent commande non recue, article manquant, mauvaise commande et probleme qualite. En cas de doute, la dispute reste `manual_review`.

### Lister et filtrer

`GET /v1/customer-refunds`

Filtres :

- `restaurant_id`
- `dispute_type`
- `status`
- `evidence_status`
- `date_from`
- `date_to`
- `min_amount`
- `limit`
- `offset`

### Detail

`GET /v1/customer-refunds/{id}` retourne :

- la dispute ;
- le restaurant ;
- le snapshot Uber lie si disponible ;
- la transaction financiere liee ;
- le dossier TENNET lie si disponible ;
- les exigences de preuves ;
- les fichiers de preuve ;
- les taches de preuve associees.

### Actions controlees

`POST /v1/customer-refunds/{id}/recalculate-evidence` recalcule `evidence_status` et cree les taches de preuves manquantes quand un dossier TENNET existe.

`POST /v1/customer-refunds/{id}/create-claim-order` cree un `ClaimOrder` lie a la dispute. Le montant du dossier correspond au montant deduit a contester. Le dossier reste dans le workflow TENNET standard.

`POST /v1/customer-refunds/{id}/create-draft` cree un brouillon interne de contestation si les preuves sont completes. Aucun email n'est envoye.

`POST /v1/customer-refunds/{id}/create-gmail-draft` cree un brouillon Gmail a partir du brouillon interne existant, si Gmail est active et connecte. Aucun email n'est envoye.

`POST /v1/customer-refunds/{id}/ignore` marque la dispute `ignored` avec une raison obligatoire.

Les endpoints bulk appliquent les memes validations et retournent `created_count`, `skipped_count`, `errors` et `created_ids`.

### Reviews de deductions

`POST /v1/customer-refunds/{id}/reviews`

Body :

```json
{
  "inbound_message_id": 123,
  "review_type": "payment_confirmed",
  "recovered_amount": "24.90",
  "expected_payment_date": "2026-06-15",
  "refusal_reason": null,
  "evidence_requested": false,
  "notes": "Uber confirme la regularisation."
}
```

`review_type` accepte :

- `accepted`
- `payment_to_verify`
- `payment_confirmed`
- `refused`
- `evidence_requested`
- `information_requested`
- `followup_needed`
- `ignored`
- `manual_review`

Effets :

- met a jour `UberCustomerRefundDispute.status` ;
- met a jour le `ClaimOrder` lie si present ;
- renseigne `recovered_amount`, `expected_payment_date`, `last_reviewed_at` et `last_reviewed_by_user_id` si applicable ;
- recalcule les preuves et taches si `evidence_requested` ;
- cree un `CustomerRefundDisputeReview` ;
- cree un `AuditLog`.

Les statuts `payment_confirmed` et `ignored` protegent la dispute contre une nouvelle transition en V1.1.

`GET /v1/customer-refunds/{id}/reviews` retourne l'historique d'une dispute.

`GET /v1/customer-refund-reviews` retourne les reviews visibles, filtrees par `restaurant_id`, `review_type`, `dispute_id`, `date_from`, `date_to`, `limit` et `offset`.

## Recovery Cockpit

Le cockpit recuperation unifie les pertes issues des `ClaimOrder`, `UberReconciliationResult` et `UberCustomerRefundDispute`.

Endpoints :

- `GET /v1/recovery/summary`
- `GET /v1/recovery/cases`
- `GET /v1/recovery/actions`
- `GET /v1/recovery/export/summary.xlsx`
- `GET /v1/recovery/export/cases.csv`

Filtres communs :

- `restaurant_id`
- `date_from`
- `date_to`
- `loss_category`
- `include_ignored`

`GET /v1/recovery/summary` retourne :

- `totals.detected_amount`
- `totals.claimable_amount`
- `totals.missing_evidence_amount`
- `totals.sent_amount`
- `totals.recovered_amount`
- `totals.refused_amount`
- `totals.pending_amount`
- `totals.recovery_rate`
- `totals.review_coverage_rate`
- `by_restaurant`
- `by_loss_category`
- `by_recovery_stage`
- `top_recoverable_cases`

`GET /v1/recovery/cases` retourne une liste paginee de cas recuperables avec `case_type`, `case_id`, restaurant, commande, categorie, etape, montants, statut preuve, prochaine action et URL frontend. Filtres supplementaires : `case_type`, `recovery_stage`, `min_amount`, `max_amount`, `needs_evidence`, `limit`, `offset`.

`GET /v1/recovery/actions` retourne les actions operationnelles : preuve a uploader, dossier a creer, brouillon a creer, brouillon Gmail a creer, reponse a traiter, relance ou revue manuelle.

Exports :

- `summary.xlsx` contient `Summary`, `By Restaurant`, `By Category`, `By Stage`, `Top Recoverable`, `Actions` ;
- `cases.csv` exporte les cas filtres.

Les exports sont reserves a `owner` et `manager`, respectent les restaurants autorises et ne contiennent jamais tokens, secrets, mots de passe, chemins disque bruts ou donnees Gmail sensibles.

## Bulk Evidence Import

Les imports de preuves permettent de stocker, analyser et rattacher en masse des justificatifs existants.

Endpoints :

- `POST /v1/evidence-imports` : upload multi-fichiers.
- `POST /v1/evidence-imports/zip` : upload ZIP avec extraction controlee.
- `GET /v1/evidence-imports` : liste les batches visibles.
- `GET /v1/evidence-imports/{batch_id}` : detail batch.
- `GET /v1/evidence-imports/{batch_id}/files` : fichiers du batch, filtre optionnel `status`.
- `POST /v1/evidence-imports/{batch_id}/analyze` : analyse les fichiers avec `provider=fake`, `local_ocr` ou `openai_vision`.
- `POST /v1/evidence-imports/{batch_id}/bulk-accept-high-confidence` : accepte les candidats fiables selon seuil.
- `GET /v1/evidence-imported-files/{file_id}` : detail fichier, analyses et candidats.
- `GET /v1/evidence-imported-files/{file_id}/preview` : telechargement protege du fichier importe.
- `POST /v1/evidence-imported-files/{file_id}/attach` : rattachement manuel vers commande, tache, deduction ou reconciliation.
- `POST /v1/evidence-imported-files/{file_id}/ignore` : ignore un fichier avec raison.
- `POST /v1/evidence-match-candidates/{candidate_id}/accept` : accepte un candidat propose.
- `POST /v1/evidence-match-candidates/{candidate_id}/reject` : rejette un candidat propose.

`POST /v1/evidence-imports/{batch_id}/analyze` body :

```json
{
  "provider": "fake",
  "limit": 100
}
```

`POST /v1/evidence-imported-files/{file_id}/attach` body :

```json
{
  "candidate_type": "claim_order",
  "candidate_id": 123,
  "evidence_type": "receipt"
}
```

Regles :

- `owner` et `manager` uniquement ;
- aucun rattachement automatique si `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false` ;
- les chemins ZIP dangereux sont refuses ;
- OpenAI vision retourne une erreur si `AI_EVIDENCE_ANALYSIS_ENABLED=false` ;
- chaque analyse, rattachement, rejet ou ignore est audite.

## Persistent Appeals

Les appels persistants evitent qu'un refus Uber cloture automatiquement un dossier.

Endpoints :

- `GET /v1/appeals`
- `GET /v1/appeals/{workflow_id}`
- `POST /v1/appeals/recalculate`
- `POST /v1/appeals/{workflow_id}/analyze-refusal`
- `POST /v1/appeals/{workflow_id}/create-draft`
- `POST /v1/appeals/{workflow_id}/create-gmail-draft`
- `POST /v1/appeals/{workflow_id}/mark-sent`
- `POST /v1/appeals/{workflow_id}/pause`
- `POST /v1/appeals/{workflow_id}/manual-close`
- `POST /v1/appeals/{workflow_id}/reopen`

`POST /v1/appeals/{workflow_id}/create-draft` body :

```json
{
  "appeal_type": "evidence_reply"
}
```

Regles :

- un `ClaimResponseReview` ou `CustomerRefundDisputeReview` refuse cree un `AppealWorkflow` ;
- le service analyse le motif et recommande une action ;
- un brouillon interne peut etre cree depuis template local ;
- un brouillon Gmail peut etre prepare, sans envoi automatique ;
- `mark-sent` enregistre uniquement l'envoi manuel deja effectue dans le workflow controle ;
- cooldown et limite de tentatives evitent les boucles ;
- `owner` peut cloturer ou reouvrir manuellement ;
- `staff` ne gere pas les appels.

Le cockpit recovery expose aussi `active_appeals_count`, `appeal_needed_count`, `escalations_needed_count`, `refused_under_appeal_amount` et `manually_closed_amount`.

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
- `success_rate`
- `top_restaurants_by_claimed_amount`
- `top_restaurants_by_pending_amount`
- `orders_by_status`
- `orders_by_restaurant`

`owner` obtient une vue globale. `manager` et `staff` obtiennent une vue filtree sur leurs restaurants assignes.

## Uber Connector

Mission 18 expose une fondation de connecteur Uber Eats sans appel API Uber reel.

- `GET /v1/uber/status` : retourne l'etat d'integration, l'obligation d'approbation Uber et le nombre de mappings.
- `GET /v1/uber/store-mappings` : liste les mappings visibles `restaurant_id` -> `uber_store_id`.
- `POST /v1/uber/store-mappings` : cree un mapping. Owner uniquement.
- `PATCH /v1/uber/store-mappings/{id}` : modifie un mapping. Owner uniquement.
- `POST /v1/uber/reporting/import` : importe un rapport CSV/XLSX Uber Eats Manager fictif ou generique.
- `POST /v1/uber/reporting/preview` : analyse un CSV/XLSX avec `report_type`, cree un batch parse et retourne `rows_preview`, `detected_columns` et `unmapped_store_ids`.
- `GET /v1/uber/reporting/batches` : liste les batches visibles.
- `GET /v1/uber/reporting/batches/{batch_id}` : retourne le resume d'un batch.
- `GET /v1/uber/reporting/batches/{batch_id}/rows` : liste les lignes avec filtre optionnel `status`.
- `POST /v1/uber/reporting/batches/{batch_id}/confirm` : cree snapshots et transactions pour les lignes valides/warning.
- `POST /v1/uber/reporting/batches/{batch_id}/cancel` : annule un batch non confirme.
- `GET /v1/uber/reporting/unmapped-stores` : liste les stores detectes mais non mappes.
- `POST /v1/uber/reporting/unmapped-stores/{uber_store_id}/map` : mappe un store vers un restaurant TENNET. Owner uniquement.
- `POST /v1/uber/reconciliation/run` : lance une analyse controlee des snapshots et transactions Uber importes. Body optionnel : `restaurant_id`, `date_from`, `date_to`, `dry_run`.
- `GET /v1/uber/reconciliation/runs` : liste les analyses visibles selon les droits.
- `GET /v1/uber/reconciliation/runs/{run_id}` : retourne le resume d'une analyse.
- `GET /v1/uber/reconciliation/results` : liste les resultats filtres par `run_id`, `restaurant_id`, `status`, dates, montant manquant ou besoin de preuve.
- `GET /v1/uber/reconciliation/results/{result_id}` : detail resultat avec snapshot, transactions rapprochees et dossier TENNET lie.
- `POST /v1/uber/reconciliation/results/{result_id}/claim-order` : cree manuellement un dossier TENNET depuis un resultat eligible.
- `POST /v1/uber/reconciliation/results/bulk-create-claim-orders` : cree plusieurs dossiers TENNET eligibles.
- `POST /v1/uber/reconciliation/results/{result_id}/ignore` : ignore manuellement un resultat.

Permissions :

- `owner` : configuration mappings, imports, reconciliation globale.
- `manager` : lecture/import/reconciliation sur restaurants assignes.
- `staff` : pas d'acces au connecteur Uber.

Les endpoints ne retournent aucun secret Uber et ne stockent aucun mot de passe Uber.

## Smart Import Et Workspace

Smart Import permet de deposer un fichier sans renommage obligatoire.

- `POST /v1/smart-import/preview` : multipart `files[]`, accepte CSV, XLSX, PDF, JPG, JPEG, PNG, WEBP, HEIC, HEIF et ZIP. Retourne un `batch_preview_id`, les types detectes, la ligne d'en-tete, les colonnes reconnues, la confiance et l'action recommandee.
- `GET /v1/smart-import/previews/{batch_id}` : relit une preview accessible a l'utilisateur.
- `POST /v1/smart-import/confirm` : confirme une preview avec body `{ "batch_preview_id": 123 }`.

Les exports Uber a deux lignes d'en-tete sont supportes : TENNET scanne les cinq premieres lignes, choisit le meilleur header et ignore le preambule.

- `GET /v1/workspace/next-actions` : retourne les actions prioritaires par bucket `urgent`, `today`, `this_week`, `blocked` et `high_value`.

Permissions :

- `owner` et `manager` peuvent utiliser Smart Import.
- `staff` voit seulement les actions de preuves autorisees dans `next-actions`.
- Aucun endpoint Smart Import n'expose de secret, token, chemin disque brut ou contenu client reel.

## Hors perimetre V1 actuelle

- pas d'integration OpenAI API ;
- pas d'envoi automatique Gmail ;
- pas de generation d'email par la validation ;
- pas de relance automatique.
