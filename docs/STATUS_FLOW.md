# Status Flow

Ce document decrit les statuts V1 des commandes a reclamer.

## Statuts autorises

- `draft` : reclamation creee mais incomplete ;
- `missing_evidence` : preuves obligatoires manquantes ;
- `ready_to_send` : dossier pret pour brouillon ou validation ;
- `draft_email_created` : brouillon interne cree ;
- `sent` : statut reserve a un futur envoi valide ;
- `waiting_uber_response` : attente d'une reponse Uber Eats ;
- `response_received` : reponse Uber Eats recue et rattachee au dossier ;
- `followup_1_sent` : premiere relance tracee dans le futur ;
- `followup_2_sent` : deuxieme relance tracee dans le futur ;
- `escalation_sent` : escalade tracee dans le futur ;
- `accepted` : reclamation acceptee ;
- `payment_to_verify` : remboursement a verifier ;
- `payment_confirmed` : remboursement confirme ;
- `refused` : reclamation refusee ;
- `manual_review` : traitement manuel requis ;
- `closed` : dossier archive ou termine.

## Transitions cible indicatives

```text
draft -> validate -> missing_evidence
draft -> validate -> ready_to_send
missing_evidence -> validate -> ready_to_send
ready_to_send -> create initial_claim draft -> draft_email_created
draft_email_created -> sent -> waiting_uber_response
sent -> inbound Gmail linked -> response_received
waiting_uber_response -> inbound Gmail linked -> response_received
response_received -> manual response review accepted -> accepted
response_received -> manual response review payment_to_verify -> payment_to_verify -> payment_confirmed -> closed
response_received -> manual response review refused -> refused
response_received -> manual response review evidence_requested -> manual_review
response_received -> manual response review information_requested -> manual_review
response_received -> manual response review followup_needed -> manual_review
response_received -> manual response review manual_review -> manual_review
```

## Regles de base

- une reclamation doit rester modifiable tant qu'elle est en `draft` ;
- aucun envoi reel ne doit etre declenche automatiquement dans cette premiere base ;
- la validation ne genere pas de brouillon d'email ;
- la validation d'un statut final est refusee ;
- les relances automatiques ne sont pas implementees ;
- la synchronisation inbound Gmail ne repond jamais automatiquement ;
- les actions importantes doivent etre journalisees.

## Validation automatique V1

Le service `POST /v1/orders/{id}/validate` verifie les preuves et informations bloquantes.

Un dossier complet passe a `ready_to_send`.

Un dossier incomplet passe a `missing_evidence`.

Les preuves bloquantes sont :

- au moins une preuve `cancellation_proof` ;
- au moins une preuve `preparation_proof` ou `waste_photo`.

Le ticket `receipt` est recommande mais non bloquant dans cette mission.

## Brouillons email internes V1

Le service `POST /v1/orders/{id}/drafts` cree des brouillons internes uniquement.

Transition actuellement active :

- `ready_to_send` + `initial_claim` valide -> `draft_email_created`.

Les autres types de brouillons (`followup_1`, `followup_2`, `escalation`, `proof_reply`) ne changent pas le statut de commande dans cette mission. Ils ne declenchent aucun envoi reel, aucune integration Gmail et aucune relance automatique.

Les statuts finaux suivants refusent la generation de brouillon et restent inchanges :

- `accepted`
- `payment_confirmed`
- `refused`
- `closed`

## Reponses Gmail inbound V1

La synchronisation Gmail entrante rattache les reponses recues apres envoi manuel.

Transitions actives :

- `sent` + message inbound rattache -> `response_received` ;
- `waiting_uber_response` + message inbound rattache -> `response_received`.

Les statuts finaux suivants ne sont jamais modifies par la sync inbound :

- `accepted`
- `payment_confirmed`
- `refused`
- `closed`

Les messages sans rattachement fiable restent `unlinked` et ne changent pas le statut de la commande.

## Traitement manuel des reponses Uber V1

Le traitement manuel des reponses Uber se fait via `POST /v1/orders/{order_id}/response-reviews`.

Il ne genere aucune reponse automatique, aucun email et aucune relance. Un owner ou manager lit la reponse, choisit un `review_type`, puis l'application applique la transition de statut correspondante.

Transitions actives :

- `accepted` -> `accepted` ;
- `payment_to_verify` -> `payment_to_verify` ;
- `payment_confirmed` -> `payment_confirmed` ;
- `refused` -> `refused` ;
- `evidence_requested` -> `manual_review` ;
- `information_requested` -> `manual_review` ;
- `followup_needed` -> `manual_review` ;
- `manual_review` -> `manual_review` ;
- `ignored` -> aucun changement de statut de commande.

Le champ `result` de la commande reprend le `review_type`, sauf pour `ignored` qui ne modifie pas la commande.

Les statuts `payment_confirmed` et `closed` protegent la commande contre une nouvelle decision non ignoree.

Chaque traitement cree un `ClaimResponseReview`, marque le message inbound comme `reviewed` ou `ignored` si un message est fourni, et ajoute des `AuditLog`.

