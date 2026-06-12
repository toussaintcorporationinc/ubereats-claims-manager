# Live Evidence Station

La Station preuves terrain transforme TENNET en poste rapide pour collecter les preuves au restaurant.

Objectif : eviter que le staff cherche le bon dossier, le bon type de preuve ou la bonne commande. TENNET affiche les preuves actives, recommande la prochaine action, imprime un ticket avec QR code, puis classe l'upload mobile dans le bon dossier.

## Workflow

1. Ouvrir `/live-evidence`.
2. Choisir la prochaine preuve recommandee.
3. Cliquer `Imprimer ticket`.
4. Imprimer le ticket TENNET via le dialogue systeme du navigateur.
5. Photographier le ticket avec la preuve demandee.
6. Scanner le QR code ou ouvrir le lien d'upload.
7. TENNET rattache la preuve a la bonne tache et relance la validation du dossier.

## Imprimante et Bluetooth

En V1, TENNET utilise `browser_print`, donc le navigateur et le systeme gerent l'imprimante disponible. Cela peut fonctionner avec une imprimante ticket deja installee sur le poste ou la tablette.

Le support Bluetooth direct ESC/POS doit rester cote application native ou connecteur dedie futur. Il ne doit servir qu'a imprimer les tickets TENNET. Il ne doit jamais lire une tablette Uber Eats, contourner une authentification Uber ou aspirer des commandes depuis une app tierce.

Le endpoint station expose `native_printer_bridge_ready=true` pour signaler que l'app native peut utiliser `POST /v1/evidence-tasks/{id}/print-ticket`, recuperer le QR/lien upload, puis rendre le ticket en ESC/POS selon le modele d'imprimante.

## Camera directe

Les pages upload TENNET utilisent un input mobile avec `capture=environment`. Sur les navigateurs compatibles, le bouton ouvre directement la camera arriere. En cas de navigateur non compatible, l'utilisateur peut toujours choisir une photo ou un PDF.

## Securite

- aucun scraping Uber ;
- aucune lecture de mot de passe ;
- aucune preuve inventee ;
- aucun montant invente ;
- aucun email envoye par cette station ;
- le lien mobile est tokenise et limite ;
- le token brut n'est retourne qu'a la creation ;
- le staff voit uniquement les restaurants qui lui sont assignes.

## Endpoints

- `GET /v1/live-evidence/station` : retourne la file active terrain, les compteurs, la prochaine tache recommandee et les regles de capture.
- `POST /v1/evidence-tasks/{id}/print-ticket` : cree le ticket imprimable et le QR code d'upload mobile.

Voir aussi `docs/NATIVE_DEVICE_BRIDGE.md` pour le contrat app native camera + imprimante ticket.

## Limites

La station facilite la collecte des preuves mais ne confirme jamais qu'une reclamation sera acceptee. TENNET garantit la detection, le suivi et la tracabilite, pas le remboursement.
