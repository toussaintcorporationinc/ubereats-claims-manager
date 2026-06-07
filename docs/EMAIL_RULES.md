# Email Rules

Ce document cadre les regles de brouillons email internes et de brouillons Gmail. Aucun envoi reel d'email n'est implemente dans la base actuelle.

## Principes cible

- preparer des brouillons avant tout envoi ;
- demander une validation utilisateur avant transmission ;
- conserver une trace du contenu envoye quand l'envoi reel sera ajoute ;
- separer la generation de contenu, la validation et l'envoi.
- creer un brouillon Gmail uniquement apres action explicite d'un utilisateur autorise.

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
- date d'envoi, uniquement quand un vrai service d'envoi sera implemente.

