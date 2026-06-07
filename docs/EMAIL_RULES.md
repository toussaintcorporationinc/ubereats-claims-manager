# Email Rules

Ce document cadre les regles de brouillons email internes. Aucun envoi reel d'email n'est implemente dans la base actuelle.

## Principes cible

- preparer des brouillons avant tout envoi ;
- demander une validation utilisateur avant transmission ;
- conserver une trace du contenu envoye quand l'envoi reel sera ajoute ;
- separer la generation de contenu, la validation et l'envoi.

## Brouillons disponibles V1

- `initial_claim`
- `followup_1`
- `followup_2`
- `escalation`
- `proof_reply`

Les brouillons sont crees depuis des templates locaux dans `backend/app/templates/emails`.

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

- integration Gmail ;
- OAuth Google ;
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

