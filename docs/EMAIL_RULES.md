# Email Rules

Ce document cadre les regles de brouillons email internes, de brouillons Gmail et d'envoi Gmail manuel approuve.

## Principes cible

- preparer des brouillons avant tout envoi ;
- demander une validation utilisateur avant transmission ;
- conserver une trace du contenu envoye quand l'envoi reel sera ajoute ;
- separer la generation de contenu, la validation et l'envoi.
- creer un brouillon Gmail uniquement apres action explicite d'un utilisateur autorise.
- envoyer un brouillon Gmail uniquement apres confirmation manuelle explicite.

## Brouillons disponibles V1

- `initial_claim`
- `followup_1`
- `followup_2`
- `escalation`
- `proof_reply`

Les brouillons sont crees depuis des templates locaux dans `backend/app/templates/emails`.

## Brouillons Gmail V1

Un brouillon interne peut etre transforme en vrai brouillon Gmail via OAuth si `EMAIL_PROVIDER_ENABLED=true` et si l'utilisateur a connecte son compte Gmail.

Regles :

- aucun email n'est envoye automatiquement ;
- le scope Gmail attendu est `https://www.googleapis.com/auth/gmail.compose` ;
- `owner` peut creer un brouillon Gmail pour tous les restaurants ;
- `manager` peut creer un brouillon Gmail pour ses restaurants assignes ;
- `staff` ne peut pas creer de brouillon Gmail ;
- le destinataire par defaut est `DEFAULT_UBER_EATS_SUPPORT_EMAIL` ;
- les preuves peuvent etre jointes si `include_evidence=true` ;
- seules les preuves existantes et accessibles via le service de stockage sont jointes ;
- la taille totale des pieces jointes est limitee par `EMAIL_MAX_ATTACHMENT_TOTAL_MB` ;
- chaque creation cree un `EmailProviderDraft` et un `AuditLog`.

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
- envoi automatique ;
- relances automatiques ;
- generation OpenAI de contenu d'email.

## Donnees minimales futures

- destinataire ;
- sujet ;
- corps du message ;
- pieces jointes ;
- reclamation associee ;
- date de creation du brouillon ;
- date d'envoi manuel.

