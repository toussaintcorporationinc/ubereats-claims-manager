# Evidence ticket printing

TENNET peut generer un ticket preuve imprimable depuis une tache de preuve active.

Objectif terrain :

- eviter de melanger les preuves entre commandes ;
- imprimer un rappel clair pour le staff ;
- photographier le ticket avec la preuve reelle ;
- scanner un QR code qui ouvre directement la page d'upload mobile de la bonne tache.

## Workflow

1. Ouvrir `/evidence-tasks/{id}`.
2. Cliquer `Imprimer ticket preuve`.
3. TENNET cree un lien mobile tokenise limite a un usage par defaut.
4. TENNET affiche un ticket avec QR code.
5. Le staff imprime le ticket, prend la photo demandee avec le ticket visible, puis scanne le QR code.
6. L'upload public rattache la preuve a la tache exacte.

## Contenu du ticket

Le ticket affiche :

- TENNET ;
- restaurant ;
- numero commande Uber ;
- montant connu ;
- type de preuve attendu ;
- echeance si disponible ;
- QR code ;
- reference `TENNET-{task_id}-{upload_link_id}` ;
- URL d'upload en secours.

## Securite

- Le token brut n'est jamais stocke, seul son hash SHA256 est conserve.
- Le lien expire selon la configuration des liens de preuves.
- Le ticket limite l'upload a la preuve demandee.
- Le lien est limite a un usage par defaut.
- La creation du ticket cree un `AuditLog`.
- Aucun email, aucune contestation et aucune relance ne sont declenches.

## Bluetooth / imprimantes ticket

Cette version produit un ticket HTML imprimable et compatible navigateur. C'est volontairement plus robuste que le Bluetooth direct, qui varie selon Android, iOS, navigateur et modele d'imprimante.

Une prochaine mission peut ajouter une couche ESC/POS pour imprimantes ticket Bluetooth ou Wi-Fi en reutilisant le meme contenu de ticket.
