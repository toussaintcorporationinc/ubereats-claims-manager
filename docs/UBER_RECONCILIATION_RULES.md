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

## Limites

Les exports Uber peuvent changer de format. TENNET ne doit jamais inventer un montant, un paiement ou une preuve. En cas de doute, le resultat reste en revue manuelle.
