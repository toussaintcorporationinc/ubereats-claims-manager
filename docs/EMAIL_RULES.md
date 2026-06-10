# Email Rules

Ce document cadre les regles de brouillons email internes, de brouillons Gmail et d'envoi Gmail manuel approuve.

## Principes cible

- preparer des brouillons avant tout envoi ;
- demander une validation utilisateur avant transmission ;
- conserver une trace du contenu envoye quand l'envoi reel sera ajoute ;
- separer la generation de contenu, la validation et l'envoi.
- creer un brouillon Gmail uniquement apres action explicite d'un utilisateur autorise.
- envoyer un brouillon Gmail uniquement apres confirmation manuelle explicite.
- lire les reponses Gmail uniquement apres sync manuelle explicite, sans reponse automatique.
- preparer les relances uniquement sous forme de taches et brouillons, jamais sous forme d'envoi automatique.

## Brouillons disponibles V1

- `initial_claim`
- `followup_1`
- `followup_2`
- `escalation`
- `proof_reply`
- `customer_refund_order_not_received`
- `customer_refund_missing_item`
- `customer_refund_order_error_adjustment`
- `customer_refund_generic`
- `appeal_generic_refusal`
- `appeal_missing_evidence_reply`
- `appeal_order_prepared_before_cancellation`
- `appeal_order_not_received_delivery_proof`
- `appeal_missing_item_preparation_proof`
- `appeal_escalation`
- `appeal_payment_verification`

Les brouillons sont crees depuis des templates locaux dans `backend/app/templates/emails`.

## Brouillons deductions Uber V1.1

Les disputes de remboursements clients et ajustements negatifs peuvent creer des brouillons internes specifiques :

- commande non recue ;
- article manquant ;
- ajustement negatif ou erreur de commande ;
- deduction generique.

Regles :

- le brouillon est cree uniquement apres action explicite d'un owner ou manager ;
- les preuves requises doivent etre completes avant creation, sauf future revue manuelle documentee ;
- le brouillon reprend uniquement les donnees connues : restaurant, numero commande, type deduction, montant deduit et preuves existantes ;
- aucune fausse preuve, aucun montant invente et aucune promesse de remboursement ne sont ajoutes ;
- un brouillon Gmail peut ensuite etre cree si Gmail est configure, mais aucun email n'est envoye automatiquement.

## Brouillons Gmail V1

Un brouillon interne peut etre transforme en vrai brouillon Gmail via OAuth si `EMAIL_PROVIDER_ENABLED=true` et si l'utilisateur a connecte son compte Gmail.

Regles :

- aucun email n'est envoye automatiquement ;
- les scopes Gmail attendus incluent `https://www.googleapis.com/auth/gmail.compose` et `https://www.googleapis.com/auth/gmail.readonly` ;
- `owner` peut creer un brouillon Gmail pour tous les restaurants ;
- `manager` peut creer un brouillon Gmail pour ses restaurants assignes ;
- `staff` ne peut pas creer de brouillon Gmail ;
- le destinataire par defaut est `DEFAULT_UBER_EATS_SUPPORT_EMAIL` ;
- les preuves peuvent etre jointes si `include_evidence=true` ;
- seules les preuves existantes et accessibles via le service de stockage sont jointes ;
- la taille totale des pieces jointes est limitee par `EMAIL_MAX_ATTACHMENT_TOTAL_MB` ;
- chaque creation cree un `EmailProviderDraft` et un `AuditLog`.

## Appels apres refus V1.1

Un refus Uber cree une action de revue/appel. Il ne cloture pas automatiquement le dossier.

Regles :

- le workflow d'appel est cree depuis un refus de reclamation ou de deduction Uber ;
- l'analyse de refus est deterministe en V1.1 et n'appelle pas OpenAI ;
- un brouillon interne d'appel est cree uniquement apres action `owner` ou `manager` ;
- un brouillon Gmail d'appel peut etre cree ensuite, mais aucun email n'est envoye automatiquement ;
- l'envoi d'un appel reste une action manuelle et tracee via `mark-sent` ou le workflow Gmail existant ;
- les tentatives sont limitees par `APPEAL_MAX_ATTEMPTS_BEFORE_MANUAL_REVIEW` et espacees par `APPEAL_MIN_DAYS_BETWEEN_ATTEMPTS` ;
- `APPEAL_AUTO_SEND_ENABLED=false` par defaut et ne declenche aucun envoi en V1.1 ;
- un owner peut cloturer ou reouvrir manuellement un workflow.

## Reponses Gmail inbound V1

Les reponses Gmail peuvent etre synchronisees depuis l'application uniquement si `EMAIL_PROVIDER_ENABLED=true` et `GMAIL_INBOUND_SYNC_ENABLED=true`.

Regles :

- aucune reponse automatique n'est envoyee ;
- aucune relance automatique n'est creee ;
- aucune classification IA n'est executee ;
- la sync est lancee manuellement par `owner` ou `manager` ;
- `staff` ne peut pas lancer la sync ;
- les messages sont dedupliques par compte Gmail et id message provider ;
- les messages sont rattaches par thread Gmail connu, puis par numero de commande Uber dans le sujet ou le corps ;
- en cas de doute, le message reste `unlinked` ;
- les messages envoyes par notre propre compte Gmail sont marques `ignored` ;
- un message rattache cree un `EmailThread` inbound ;
- un rattachement manuel est possible pour `owner` et pour `manager` sur ses restaurants assignes ;
- aucun token Gmail, secret ou mot de passe n'est stocke dans l'historique ou l'audit.

## Traitement manuel des reponses Uber V1

Une reponse Gmail rattachee peut etre traitee manuellement depuis l'application par un owner ou manager autorise.

Regles :

- le traitement ne repond jamais a l'email Gmail ;
- le traitement ne modifie jamais Gmail cote utilisateur ;
- le traitement ne declenche aucun envoi, aucune relance et aucune classification IA ;
- `staff` ne peut pas traiter une reponse ;
- un traitement cree un `ClaimResponseReview` ;
- un message inbound fourni passe a `review_status=reviewed` ou `review_status=ignored` ;
- les decisions possibles sont `accepted`, `payment_to_verify`, `payment_confirmed`, `refused`, `evidence_requested`, `information_requested`, `followup_needed`, `ignored` et `manual_review` ;
- `ignored` ne change pas le statut de la commande ;
- `payment_confirmed` et `closed` protegent la commande contre une nouvelle decision non ignoree ;
- chaque traitement ajoute un `AuditLog` sans token, secret, mot de passe ni contenu sensible inutile.

## Traitement manuel des deductions Uber V1.1

Les deductions Uber et remboursements clients peuvent recevoir une decision manuelle depuis le detail de la dispute.

Regles :

- le traitement ne cree aucune reponse automatique ;
- le traitement ne cree aucun nouvel email automatiquement ;
- le traitement peut mettre la dispute en `accepted`, `payment_to_verify`, `payment_confirmed`, `refused`, `needs_evidence`, `ignored` ou `manual_review` ;
- une demande de preuve recalcule les taches de preuve, mais n'envoie rien ;
- `payment_confirmed` et `ignored` protegent la dispute contre une nouvelle transition en V1.1 ;
- chaque decision cree un `CustomerRefundDisputeReview` et un `AuditLog` sans token, secret ou mot de passe.

## Envoi Gmail manuel V1

Un brouillon Gmail deja cree peut etre envoye uniquement depuis l'application, par un owner ou manager autorise, avec `confirm_send=true`.

Regles :

- aucun email n'est envoye automatiquement ;
- aucune relance automatique n'est creee ;
- aucun retry automatique n'est lance ;
- `staff` ne peut pas envoyer ;
- un brouillon deja `sent` ne peut pas etre renvoye ;
- un brouillon `failed` ne peut pas etre renvoye dans cette mission ;
- les commandes finales `accepted`, `payment_confirmed`, `refused` et `closed` bloquent l'envoi ;
- apres envoi, la commande passe a `sent` ;
- un `EmailThread` outbound conserve le sujet, le corps, le message id et le thread id disponibles ;
- un `AuditLog` trace le succes ou l'echec controle ;
- les tokens Gmail, secrets et mots de passe ne sont jamais stockes dans l'audit.

## Relances controlees V1

La politique de relance aide a preparer des brouillons pour les dossiers non resolus. Elle ne cree aucune boucle infinie et n'envoie jamais automatiquement.

Delais par defaut :

- `followup_1` : J+2 apres le premier envoi ;
- `followup_2` : J+5 apres le premier envoi si `followup_1` existe ;
- `escalation` : J+10 apres le premier envoi si `followup_1` et `followup_2` existent ;
- `manual_review` : J+15, limite de relances atteinte ou reponse inbound non traitee.

Regles :

- les delais sont configurables par variables d'environnement ;
- `MAX_FOLLOWUPS_PER_ORDER` limite les relances ;
- `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false` par defaut et ne declenche aucun envoi dans cette V1 ;
- une seule tache par commande et type de relance est autorisee ;
- les statuts finaux `accepted`, `payment_confirmed`, `refused` et `closed` ne sont jamais relances ;
- une reponse inbound non traitee bloque la relance classique et propose `manual_review` ;
- les relances creent d'abord des `EmailDraft`, puis eventuellement des brouillons Gmail ;
- l'envoi Gmail reste manuel et confirme via le workflow d'envoi existant ;
- chaque recalcul, creation, skip ou completion de tache est audite.

## AutoPilot controle V1.2

AutoPilot peut envoyer automatiquement des contestations initiales, relances ou appels uniquement si toutes les conditions de securite sont remplies. Il reste desactive par defaut.

Flags obligatoires :

- `AUTOPILOT_ENABLED=true` ;
- `AUTOPILOT_INITIAL_CLAIMS_ENABLED=true` pour les contestations initiales ;
- `AUTOPILOT_FOLLOWUPS_ENABLED=true` pour les relances ;
- `AUTOPILOT_APPEALS_ENABLED=true` pour les appels ;
- `EMAIL_PROVIDER_ENABLED=true` et Gmail connecte si `AUTOPILOT_REQUIRE_GMAIL_CONNECTED=true`.

Regles :

- aucun dossier incomplet n'est envoye ;
- aucune preuve, montant ou commande n'est invente ;
- les limites `AUTOPILOT_DAILY_SEND_LIMIT` et `AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT` limitent le volume ;
- `AUTOPILOT_COOLDOWN_HOURS` espace les relances et appels ;
- un refus Uber ne cloture jamais automatiquement un dossier ;
- un renvoi identique sans nouvel argument est bloque quand `APPEAL_ALLOW_SAME_TEMPLATE_RESEND=false` ;
- `POST /v1/autopilot/dry-run` previsualise sans envoyer ;
- `POST /v1/autopilot/stop` active un arret d'urgence.

## Regles de generation

- `initial_claim` exige une commande `ready_to_send` et complete selon le service de validation ;
- un brouillon initial fait passer la commande a `draft_email_created` ;
- `followup_1` exige un brouillon `initial_claim` existant ;
- `followup_2` exige des brouillons `initial_claim` et `followup_1` existants ;
- `escalation` exige un brouillon `initial_claim` existant ;
- `proof_reply` exige au moins une preuve rattachee ;
- aucun brouillon n'est genere pour les statuts finaux `accepted`, `payment_confirmed`, `refused` ou `closed` ;
- chaque creation de brouillon ajoute un `AuditLog`.

## Anti-invention

- ne jamais inventer un numero de commande Uber ;
- ne jamais inventer un montant ;
- ne jamais inventer une preuve ;
- ne pas afficher les champs optionnels absents dans le corps du brouillon ;
- utiliser uniquement les donnees de `Restaurant`, `ClaimOrder` et `EvidenceFile`.

## Hors perimetre actuel

- SMTP ;
- envoi automatique hors AutoPilot controle ;
- relances automatiques hors AutoPilot controle ;
- generation OpenAI de contenu d'email.
- classification IA de reponses Uber ;
- reponse automatique aux emails entrants.

## Donnees minimales futures

- destinataire ;
- sujet ;
- corps du message ;
- pieces jointes ;
- reclamation associee ;
- date de creation du brouillon ;
- date d'envoi manuel.

## V1.1 RC reminders

- Refusals create review/appeal work, not automatic closure.
- Appeal drafts stay internal until an authorized user creates a Gmail draft.
- Gmail sending remains manual and explicit.
- AutoPilot V1.2 is opt-in, controlled by disabled-by-default flags and per-restaurant activation.
- `APPEAL_AUTO_SEND_ENABLED=false` must remain the default.
- `FOLLOWUP_AUTOMATIC_SEND_ENABLED=false` must remain the default.
- No spam loop is acceptable.

