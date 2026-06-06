# Status Flow

Ce document decrit les statuts V1 des commandes a reclamer.

## Statuts autorises

- `draft` : reclamation creee mais incomplete ;
- `missing_evidence` : preuves obligatoires manquantes ;
- `ready_to_send` : dossier pret pour brouillon ou validation ;
- `draft_email_created` : brouillon interne cree ;
- `sent` : statut reserve a un futur envoi valide ;
- `waiting_uber_response` : attente d'une reponse Uber Eats ;
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
draft -> missing_evidence -> ready_to_send -> draft_email_created
draft_email_created -> sent -> waiting_uber_response
waiting_uber_response -> accepted -> payment_to_verify -> payment_confirmed -> closed
waiting_uber_response -> refused -> manual_review -> closed
```

## Regles de base

- une reclamation doit rester modifiable tant qu'elle est en `draft` ;
- aucun envoi reel ne doit etre declenche automatiquement dans cette premiere base ;
- les relances automatiques ne sont pas implementees ;
- les actions importantes doivent etre journalisees.

