# Status Flow

Ce document decrit un flux cible simple pour les futures reclamations. Il n'est pas encore implemente dans cette base technique.

## Statuts envisages

- `draft` : reclamation creee mais incomplete ;
- `ready_to_submit` : pieces et informations minimales presentes ;
- `submitted` : reclamation envoyee ou declaree comme envoyee ;
- `waiting_response` : attente d'une reponse ;
- `accepted` : reclamation acceptee ;
- `rejected` : reclamation rejetee ;
- `closed` : dossier archive ou termine.

## Transitions cible

```text
draft -> ready_to_submit -> submitted -> waiting_response
waiting_response -> accepted -> closed
waiting_response -> rejected -> closed
```

## Regles de base cible

- une reclamation doit rester modifiable tant qu'elle est en `draft` ;
- aucun envoi reel ne doit etre declenche automatiquement dans cette premiere base ;
- les transitions definitives devront etre journalisees quand la logique metier sera ajoutee.

