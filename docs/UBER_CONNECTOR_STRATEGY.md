# Uber Connector Strategy

## Objectif

TENNET doit reduire la saisie manuelle en recuperant les donnees Uber Eats utiles a la detection des commandes annulees non compensees. Le workflow cible est :

1. importer ou recevoir les commandes Uber Eats ;
2. importer ou recevoir les transactions financieres ;
3. rapprocher annulations, paiements, remboursements et ajustements ;
4. detecter les commandes non compensees ou partiellement compensees ;
5. creer un dossier TENNET uniquement si les donnees sont suffisantes ;
6. demander au restaurateur les preuves manquantes avant toute reclamation.

## Pourquoi eviter le scraping

TENNET ne doit pas scraper la tablette Uber Eats, automatiser Uber Eats Manager avec un mot de passe, ni contourner l'authentification Uber. Ces pratiques sont fragiles, risquent de violer les conditions d'utilisation, exposent les identifiants du restaurateur et ne donnent pas une base fiable pour une production commerciale.

## Integration officielle Uber Eats

La cible long terme est l'integration officielle Uber Eats Marketplace API, avec approbation Uber. Les scopes devront couvrir selon disponibilite :

- lecture des stores/merchants ;
- lecture des commandes recentes ;
- webhooks d'evenements de commande ;
- reporting financier, paiements, remboursements et ajustements.

Les credentials et tokens Uber devront etre chiffres, jamais exposes au frontend, jamais logs, et revocables.

## Orders API et webhooks

Les Orders API/webhooks sont utiles pour les donnees operationnelles recentes : numero de commande, etat, montant, heure de commande et annulation. Elles ne suffisent pas toujours pour l'historique long ni pour la reconciliation financiere complete.

## Reporting API

La Reporting API est la source attendue pour l'historique, les paiements, remboursements, ajustements et references de payout. Elle sert a calculer si une commande annulee a ete compensee, partiellement compensee ou non compensee.

## Fallback imports Uber Eats Manager

En attendant les credentials officiels, TENNET supporte l'import CSV/XLSX de rapports Uber Eats Manager. Ce fallback permet de tester la reconciliation sans appel Uber reel et sans secret Uber.

Mission 19 structure ce fallback en workflow robuste :

1. upload d'un rapport ;
2. choix du type interne TENNET : `orders_report`, `payments_report`, `adjustments_report` ou `combined_report` ;
3. preview des colonnes detectees, lignes valides, erreurs, warnings et stores non mappes ;
4. mapping explicite des stores non mappes vers restaurants TENNET ;
5. confirmation manuelle ;
6. creation de `UberOrderSnapshot` et `UberFinancialTransaction` ;
7. reconciliation financiere.

Ce workflow est adapte au backfill des 6 derniers mois, mais ne code aucune limite de restaurant ni aucune limite stricte de periode.

## Limites Mission 18

- Aucun appel API Uber reel.
- Aucun stockage de mot de passe Uber.
- Aucun scraping.
- Aucun email automatique.
- Les dossiers crees depuis reconciliation restent dans le workflow TENNET existant et exigent les preuves avant reclamation.
