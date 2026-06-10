# Recovery Cockpit V1.1

Le cockpit recuperation donne une vue unifiee des pertes detectees et des actions a traiter dans TENNET.

Il regroupe :

- commandes annulees non compensees ;
- resultats de reconciliation Uber ;
- deductions Uber et remboursements clients ;
- preuves manquantes ;
- relances controlees ;
- dossiers acceptes, refuses, payes ou en revue manuelle.

TENNET ne garantit pas le remboursement. TENNET garantit le suivi, la revue systematique et la tracabilite des pertes detectees.

## Montants

- `detected_amount` : montant total des pertes detectees.
- `claimable_amount` : montant encore eligible a une contestation ou action de recuperation.
- `missing_evidence_amount` : montant bloque par des preuves manquantes ou partielles.
- `sent_amount` : montant deja envoye ou conteste.
- `recovered_amount` : montant confirme comme recupere.
- `refused_amount` : montant refuse.
- `pending_amount` : montant contestable restant apres recuperations et refus.
- `recovery_rate` : montant recupere / montant envoye.
- `review_coverage_rate` : part des pertes detectees ayant recu une decision ou une revue.
- `active_appeals_count` : workflows d'appel ouverts.
- `appeal_needed_count` : appels demandant une action.
- `escalations_needed_count` : appels arrives au niveau escalade.
- `refused_under_appeal_amount` : montant refuse encore sous appel actif.
- `manually_closed_amount` : montant cloture manuellement.

## Categories

Categories de perte :

- `cancellation_not_compensated`
- `customer_refund`
- `order_not_received`
- `missing_item`
- `incorrect_item`
- `order_error_adjustment`
- `chargeback`
- `manual_review`
- `under_appeal`

Etapes de recuperation :

- `detected`
- `needs_evidence`
- `evidence_ready`
- `draft_created`
- `gmail_draft_created`
- `sent`
- `response_received`
- `accepted`
- `payment_to_verify`
- `payment_confirmed`
- `refused`
- `ignored`
- `manual_review`

## Workflow commercial

1. Importer les donnees Uber et detecter les pertes.
2. Ouvrir `/recovery`.
3. Identifier les montants detectes, contestables, bloques par preuves et recuperes.
4. Ouvrir `/recovery/cases` pour filtrer par restaurant, categorie, etape ou montant.
5. Ouvrir `/recovery/actions` pour traiter les preuves, dossiers, brouillons, reponses ou relances.
6. Creer les dossiers TENNET uniquement par action humaine.
7. Ajouter les preuves necessaires.
8. Creer les brouillons internes ou Gmail draft si le dossier est pret.
9. Envoyer seulement via le workflow Gmail manuel existant.
10. Traiter les decisions Uber et conserver l'audit.

## Exports

Endpoints :

- `GET /v1/recovery/export/summary.xlsx`
- `GET /v1/recovery/export/cases.csv`

Les exports respectent les permissions restaurant, sont reserves a `owner` et `manager`, et n'incluent pas de token, secret, mot de passe, chemin disque brut de preuve ou donnee Gmail sensible.

## Permissions

- `owner` : cockpit complet, cases, actions et exports.
- `manager` : cockpit filtre sur restaurants assignes, cases, actions et exports.
- `staff` : pas de cockpit financier ni export ; peut voir les actions de preuve autorisees si exposees par le workflow.

## Limites

- Aucune promesse de remboursement.
- Aucun envoi automatique.
- Aucune relance automatique infinie.
- Aucune decision irreversible sans action utilisateur.
- Aucun scraping Uber.
- Aucun mot de passe Uber.
- Aucun montant, motif ou preuve invente.

## V1.1 RC acceptance

During staging acceptance, verify that the cockpit includes:

- canceled orders from reconciliation;
- customer refund disputes;
- missing evidence tasks;
- bulk evidence attachments;
- active appeals and escalations;
- refused amounts under appeal;
- manual-review cases.

The cockpit remains an operational tracking view, not a promise of recovery.

## A faire maintenant

`GET /v1/workspace/next-actions` provides a simplified action queue for dashboard and mobile usage.

Buckets:

- `urgent` ;
- `today` ;
- `this_week` ;
- `blocked` ;
- `high_value`.

Staff users receive only evidence actions. Owner and manager users also receive recovery, import, report and AutoPilot guidance.
