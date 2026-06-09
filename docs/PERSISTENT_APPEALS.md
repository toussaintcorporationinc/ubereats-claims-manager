# Persistent Appeals V1.1

Un refus Uber ne cloture pas automatiquement un dossier dans TENNET. Il ouvre un workflow d'appel controle jusqu'a resolution, paiement confirme ou cloture manuelle explicite.

## Objectif

- detecter les refus sur les reclamations et deductions Uber ;
- analyser le motif de refus sans IA externe obligatoire ;
- recommander une action d'appel ;
- creer un brouillon interne d'appel ;
- creer un brouillon Gmail si l'utilisateur le demande ;
- marquer l'appel comme envoye seulement apres action humaine ;
- conserver l'historique des tentatives.

## Statuts workflow

- `appeal_needed`
- `evidence_needed`
- `draft_needed`
- `gmail_draft_needed`
- `appeal_sent`
- `response_received`
- `escalated`
- `payment_to_verify`
- `payment_confirmed`
- `accepted`
- `paused`
- `manually_closed`

## Actions recommandees

- `review_refusal`
- `request_more_evidence`
- `create_appeal_draft`
- `create_gmail_draft`
- `send_manual_appeal`
- `payment_verification`
- `escalation`
- `manual_review`

## Endpoints

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

## Anti-boucle

- nombre maximal de tentatives configure par `APPEAL_MAX_ATTEMPTS_BEFORE_MANUAL_REVIEW` ;
- escalade apres `APPEAL_MAX_ATTEMPTS_BEFORE_ESCALATION` ;
- delai minimum entre tentatives via `APPEAL_MIN_DAYS_BETWEEN_ATTEMPTS` ;
- pas de brouillon identique non traite si `APPEAL_ALLOW_SAME_TEMPLATE_RESEND=false` ;
- `APPEAL_AUTO_SEND_ENABLED=false` par defaut et aucun envoi automatique n'est implemente.

## TENNET V1.1 RC2 fixes

`POST /v1/appeals/{workflow_id}/create-gmail-draft` refuse maintenant :

- `email_provider_disabled` si `EMAIL_PROVIDER_ENABLED=false` ;
- `gmail_account_not_connected` si aucun compte Gmail actif n'est connecte.

Aucun `EmailProviderDraft` n'est cree et aucun `AppealAttempt` ne passe a `gmail_draft_created` dans ces deux cas.

## Permissions

- `owner` gere tous les workflows et peut cloturer/reouvrir manuellement ;
- `manager` gere les workflows de ses restaurants assignes ;
- `staff` ne cree pas d'appel ni de brouillon.

## Limites

- aucun resultat n'est garanti ;
- aucun email n'est envoye automatiquement ;
- aucun refus n'est transforme en cloture sans decision humaine ;
- les preuves et montants restent bases sur les donnees existantes.

## V1.1 RC acceptance

Validate in staging:

- refused claim response creates an appeal workflow;
- refused customer refund review creates an appeal workflow;
- create draft works from local templates;
- create Gmail draft does not send;
- mark sent is manual;
- cooldown blocks immediate duplicate attempts;
- owner can manually close and reopen.
