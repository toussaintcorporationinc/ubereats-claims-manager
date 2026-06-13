# Multi Gmail par restaurant

TENNET peut connecter plusieurs comptes Gmail a un meme utilisateur owner ou manager, puis choisir le compte Gmail a utiliser selon le restaurant du dossier.

Objectif operationnel :

- 4 restaurants peuvent utiliser `restaurant-groupe-a@example.com`.
- 2 restaurants peuvent utiliser `restaurant-groupe-b@example.com`.
- Les brouillons Gmail, envois manuels et synchronisations de reponses restent controles.

## Regles

- Gmail OAuth reste une autorisation manuelle par boite Gmail.
- Aucun mot de passe Gmail n'est stocke dans TENNET.
- Les tokens OAuth restent chiffres en base.
- Aucun email n'est envoye automatiquement par le simple fait de mapper un compte Gmail.
- Si aucun compte n'est mappe a un restaurant, TENNET utilise le compte Gmail actif par defaut de l'utilisateur.

## Workflow

1. Aller dans `Parametres > Email`.
2. Cliquer `Connecter Gmail` pour autoriser la premiere boite.
3. Cliquer `Connecter un autre Gmail` pour autoriser une autre boite.
4. Dans `Gmail par restaurant`, assigner chaque restaurant au compte Gmail attendu.
5. Creer les brouillons Gmail depuis les dossiers TENNET comme d'habitude.

## Limites

- Le mapping choisit le compte Gmail pour les brouillons Gmail lies a un restaurant.
- La synchronisation inbound parcourt les comptes Gmail connectes de l'utilisateur.
- La validation terrain reste necessaire avant de generaliser les mappings a tous les restaurants.
