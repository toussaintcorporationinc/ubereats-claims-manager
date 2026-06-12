# Live Evidence Station

La Station preuves terrain transforme TENNET en poste rapide pour collecter les preuves au restaurant.

Objectif : eviter que le staff cherche le bon dossier, le bon type de preuve ou la bonne commande. TENNET affiche les preuves actives, recommande la prochaine action, imprime un ticket avec QR code, puis classe l'upload mobile dans le bon dossier.

## Workflow

1. Ouvrir `/live-evidence`.
2. Choisir la prochaine preuve recommandee.
3. Dans l'app Android terrain, cliquer `Imprimer et prendre photo`.
4. TENNET imprime le ticket sur l'imprimante Bluetooth ESC/POS appairee.
5. TENNET ouvre directement la camera pour photographier le ticket avec la preuve demandee.
6. Scanner le QR code ou ouvrir le lien d'upload.
7. TENNET rattache la preuve a la bonne tache et relance la validation du dossier.

## Imprimante et Bluetooth

La web app utilise `browser_print`, donc le navigateur et le systeme gerent l'imprimante disponible. Cela peut fonctionner avec une imprimante ticket deja installee sur le poste ou la tablette.

L'app Android native TENNET embarque maintenant un bridge `android_bluetooth_escpos`. Il liste les imprimantes Bluetooth appairees, choisit prioritairement les peripheriques SUNMI/POS/ticket, convertit le ticket TENNET en ESC/POS et imprime le QR code d'upload.

Ce bridge ne sert qu'a imprimer les tickets TENNET. Il ne lit jamais une tablette Uber Eats, ne contourne aucune authentification Uber et n'aspire pas des commandes depuis une app tierce.

Le endpoint station expose `native_printer_bridge_ready=true`, `bluetooth_supported=true`, `native_print_modes=["android_bluetooth_escpos"]` et `native_print_contract_version=2026-06-12.android-escpos.v1`.

## Camera directe

Les pages upload TENNET utilisent un input mobile avec `capture=environment`. L'app Android native utilise la camera native et l'ouvre automatiquement apres une impression reussie.

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
