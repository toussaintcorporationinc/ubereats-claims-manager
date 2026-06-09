# Uber Reconciliation Rules V1.1

TENNET rapproche les commandes Uber Eats importees et les transactions financieres importees depuis des exports CSV/XLSX fournis par l'utilisateur.

Aucun scraping, aucune connexion tablette Uber, aucun mot de passe Uber et aucun appel API Uber reel ne sont utilises dans cette version.

## Periode

La periode par defaut est de 180 jours via `UBER_RECONCILIATION_DEFAULT_LOOKBACK_DAYS`. L'utilisateur peut filtrer par restaurant et par dates.

## Commandes annulees

Une commande est analysee comme annulee si `canceled_at` est renseigne ou si le statut importe correspond a une annulation reconnue : `canceled`, `cancelled`, `cancel`, `annule`, `annulee`, `cancellation`, `customer_cancelled`, `eater_cancelled`, `unfulfilled` ou `failed_delivery`.

## Montants

- `paid_amount` est la somme des transactions positives reconnues comme paiement ou compensation.
- `refunded_amount` est la somme absolue des transactions reconnues comme refund, chargeback ou deduction.
- `missing_amount = max(order_amount - paid_amount, 0)`.
- Si `missing_amount` est inferieur ou egal a `UBER_RECONCILIATION_AMOUNT_TOLERANCE`, le resultat est `compensated`.

## Statuts

- `compensated` : compensation suffisante.
- `not_compensated` : commande annulee, montant connu, aucun paiement positif lie.
- `partially_compensated` : paiement positif partiel et montant manquant restant.
- `already_claimed` : un dossier TENNET existe deja pour le meme restaurant et numero Uber/display id.
- `needs_evidence` : resultat eligible mais preuves a completer dans le workflow TENNET.
- `manual_review` : montant absent, statut ambigu, type transaction inconnu critique, conflit ou dossier existant cloture/refuse.
- `ignored` : resultat ignore manuellement.

## Creation de dossiers

L'analyse ne cree jamais de `ClaimOrder` automatiquement. L'utilisateur doit creer un dossier individuellement ou par selection groupée.

Les resultats `compensated`, `already_claimed`, `ignored` et `manual_review` ne sont pas eligibles en V1.1.

Quand un resultat eligible cree un `ClaimOrder` avec `evidence_required=true`, TENNET peut ensuite creer des `EvidenceRequestTask` via `/v1/evidence-tasks/recalculate`.

Ces taches demandent les preuves bloquantes manquantes et renvoient le dossier dans le workflow standard de validation. Aucune preuve n'est inventee depuis les donnees Uber et aucune reclamation n'est envoyee automatiquement.

## Limites

Les exports Uber peuvent changer de format. TENNET ne doit jamais inventer un montant, un paiement ou une preuve. En cas de doute, le resultat reste en revue manuelle.

## Deductions clients et ajustements negatifs

Les transactions negatives importees peuvent aussi alimenter le module Customer Refund Disputes.

Ce module est distinct de la reconciliation de compensation :

- la reconciliation detecte les commandes annulees non compensees ;
- les disputes de deductions detectent les refunds, chargebacks, remboursements clients et ajustements negatifs sur versement ;
- aucune action ne clique dans Uber Eats Manager ;
- aucune contestation, aucun email et aucune relance ne sont envoyes automatiquement ;
- les dossiers crees depuis une deduction restent soumis aux preuves et au workflow TENNET standard.

## Cockpit recuperation

Les resultats de reconciliation alimentent `/recovery` avec la categorie `cancellation_not_compensated`.

Regles :

- un resultat `not_compensated`, `partially_compensated` ou `needs_evidence` peut contribuer au montant contestable ;
- un resultat `compensated` est assimile a une etape de paiement confirme pour le cockpit ;
- un resultat `already_claimed`, `manual_review` ou ambigu reste en revue humaine ;
- aucun `ClaimOrder`, brouillon, email ou relance n'est cree automatiquement depuis le cockpit ;
- les exports recovery ne doivent pas contenir de token, secret ou chemin disque brut de preuve.
