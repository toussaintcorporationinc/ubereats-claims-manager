# TENNET native device bridge

Ce document decrit le contrat propre pour transformer la Station preuves TENNET en experience native avec camera et imprimante ticket Bluetooth.

## Objectif

L'app native TENNET doit permettre au restaurant de :

- voir les preuves a collecter ;
- imprimer un ticket TENNET sur imprimante ticket Bluetooth ou reseau ;
- ouvrir directement la camera ;
- envoyer la preuve vers la bonne tache ;
- laisser TENNET poursuivre validation, brouillon, suivi, Gmail et appels selon les regles configurees.

## Ce que le bridge ne doit jamais faire

- lire l'ecran d'une tablette Uber Eats ;
- automatiser l'application Uber Eats Manager ;
- capturer un mot de passe Uber ;
- contourner l'authentification Uber ;
- inventer une commande, un montant ou une preuve ;
- envoyer un email si les regles AutoPilot/Gmail ne sont pas explicitement remplies.

Les donnees commandes doivent venir par sources autorisees : API/Webhooks Uber officiels, imports Uber Reporting, exports Manager ou emails Gmail connectes.

## Endpoints utilises par l'app native

1. `GET /v1/live-evidence/station`

Retourne les taches terrain priorisees et les capacites :

- `camera_capture_supported=true` ;
- `printer_mode=browser_print` pour le web ;
- `native_printer_bridge_ready=true` pour l'app native ;
- `native_printer_bridge_contract` avec le endpoint ticket.

2. `POST /v1/evidence-tasks/{id}/print-ticket`

Retourne :

- `ticket_reference` ;
- `upload_url` ;
- `qr_svg` ;
- `print_html` ;
- donnees commande/restaurant/preuve.

L'app native peut convertir ces donnees en ESC/POS selon le modele d'imprimante. Le QR code doit pointer vers `upload_url`.

3. `POST /v1/evidence-tasks/{id}/upload`

Upload connecte avec JWT pour staff/manager/owner.

4. `POST /v1/evidence-upload-links/{token}/upload`

Upload public limite au token du ticket imprime.

## Camera

Le web utilise `input type=file` avec `capture=environment`. L'app native peut utiliser la camera native et envoyer directement le fichier vers l'endpoint d'upload.

## Imprimante Bluetooth

Le web utilise le dialogue d'impression systeme. L'app native devra gerer :

- appairage Bluetooth par le systeme ;
- detection modele imprimante ;
- conversion ticket vers ESC/POS ;
- impression QR lisible ;
- erreur claire si imprimante absente.

L'utilisateur doit toujours valider l'impression localement. TENNET ne doit pas imprimer des preuves sans action terrain claire.

## Source live Uber

TENNET ne doit pas se connecter a la tablette Uber pour aspirer les commandes. Le live propre passe par :

- Uber Orders API et Webhooks apres approbation Uber ;
- Uber Reporting API ;
- exports CSV/XLSX ;
- Gmail pour les reponses et notifications.

La tablette peut etre utilisee par l'humain comme reference visuelle, mais TENNET ne doit pas la piloter ni la lire automatiquement.
