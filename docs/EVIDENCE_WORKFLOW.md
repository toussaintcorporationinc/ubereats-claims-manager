# Evidence workflow V1.1

TENNET utilise les preuves pour verifier qu'un dossier de reclamation Uber Eats est complet avant generation de brouillon.

## Preuves bloquantes

Un dossier n'est pas pret sans une preuve unique `receipt` exploitable.

Dans TENNET V1.2, `receipt` signifie : une seule photo nette du ticket de caisse agrafe ou pose sur la commande du
client, avec restaurant, numero de commande/client et commande preparee visibles.

Les anciens dossiers restent compatibles avec l'ancien ensemble de preuves :

- `cancellation_proof` ;
- `preparation_proof` ou `waste_photo`.

## File de demandes

La page `/evidence-tasks` permet a un owner ou manager de recalculer les preuves manquantes.

TENNET cree par defaut une seule tache `receipt` par dossier bloque : imprimer le ticket si necessaire, l'agrafer ou le
poser sur la commande, prendre une seule photo nette, puis importer les preuves en masse.

Chaque tache doit indiquer le contexte metier lisible : remboursement ou annulation, restaurant, numero de commande, client quand il est connu, montant et preuve attendue. L'objectif terrain est que l'utilisateur sache exactement quel ticket imprimer ou quelle photo prendre avant de renvoyer les preuves en masse a TENNET.

Les resultats Uber reconciliation avec `evidence_required=true` peuvent alimenter la priorite quand un dossier TENNET existe deja.

Les deductions Uber detectees depuis transactions financieres creent aussi une exigence obligatoire `receipt`.

Les preuves comme `delivery_proof`, `preparation_proof`, `sealed_bag_photo`, `order_details_screenshot`,
`gps_or_route_proof`, `customer_contact_proof`, `courier_statement` ou `uber_screenshot` peuvent renforcer le dossier si
Uber les redemande, mais elles ne sont plus demandees par defaut.

## Priorites

Les priorites sont configurees par variables d'environnement :

- `EVIDENCE_TASK_HIGH_AMOUNT` ;
- `EVIDENCE_TASK_URGENT_AMOUNT`.

Si le montant manquant issu de la reconciliation est disponible, il est utilise. Sinon TENNET utilise le montant de la commande.

Pour les deductions Uber, la priorite utilise le montant deduit rattache a la dispute.

Si Uber demande une preuve supplementaire sur une deduction, une review `evidence_requested` remet la dispute en `needs_evidence`, recalcule les exigences et cree les taches manquantes quand un dossier TENNET est lie.

## Upload protege

Un utilisateur connecte peut uploader une preuve depuis une tache s'il a acces au restaurant de la commande.

L'upload :

- utilise les controles de `FileStorageService` ;
- refuse fichiers vides, trop lourds, extension interdite et MIME interdit ;
- cree un `EvidenceFile` ;
- marque la tache `completed` ;
- cree un `AuditLog` ;
- relance la validation du dossier.

## Upload mobile tokenise

Un owner ou manager peut creer un lien mobile depuis une tache active.

Regles :

- le token brut est retourne uniquement a la creation ;
- seul un hash SHA256 est stocke ;
- le lien expire via `EVIDENCE_UPLOAD_LINK_EXPIRY_HOURS` ;
- le nombre d'usages est limite via `EVIDENCE_UPLOAD_LINK_MAX_USES` ;
- le lien peut etre revoque ;
- la page publique n'exige pas de JWT ;
- la page publique ne permet d'ajouter que le type de preuve demande.

## Ticket preuve imprimable

La page detail d'une tache preuve permet aussi de creer un ticket preuve imprimable.

Le ticket sert au terrain :

- imprimer un rappel simple de la commande et de la preuve attendue ;
- afficher un QR code vers l'upload mobile tokenise ;
- demander au staff de photographier le ticket avec la preuve reelle ;
- eviter les confusions entre commandes, restaurants et types de preuves.

Par defaut, le ticket cree un lien mobile limite a un usage. Le token brut n'est pas stocke, seul son hash est conserve. La creation du ticket cree un `AuditLog` et ne declenche aucun email, aucune contestation et aucune relance.

Le staff assigne peut creer ce ticket sur ses restaurants, car c'est une action de collecte de preuve. Il ne peut toujours pas ignorer une tache, la completer manuellement, creer de brouillon ou traiter une decision financiere.

## Station preuves terrain

La page `/live-evidence` expose une file terrain plus directe que `/evidence-tasks`.

Elle permet de :

- voir la prochaine preuve recommandee ;
- filtrer par priorite ;
- imprimer un ticket TENNET en un clic ;
- ouvrir le lien d'upload photo cree par le ticket ;
- rappeler les regles de capture sure au staff.

Le backend expose `GET /v1/live-evidence/station`. La reponse contient uniquement des taches accessibles a l'utilisateur connecte, les compteurs de priorite et les regles terrain. Elle ne retourne pas de `storage_path`, de token brut ou de secret.

L'impression directe Bluetooth reste un sujet d'application native future. En V1, TENNET utilise l'impression navigateur et ne se connecte jamais a une tablette Uber Eats.

## Import massif de preuves

La page `/evidence-imports` permet a un owner ou manager d'importer des fichiers existants en vrac ou via ZIP.

TENNET :

- stocke les fichiers dans le stockage evidence ;
- calcule un checksum SHA256 ;
- refuse les fichiers trop lourds, extensions interdites ou ZIP dangereux ;
- analyse les fichiers avec un fournisseur controle ;
- propose des candidats vers `ClaimOrder`, `EvidenceRequestTask`, `UberCustomerRefundDispute` ou `UberReconciliationResult` ;
- cree une preuve rattachee automatiquement uniquement si une seule tache de preuve compatible ressort avec un signal deterministe fort ;
- garde le fichier en revue si le numero de commande, le restaurant, le client, le montant ou le type de preuve ne sont pas assez fiables ;
- relance la validation du dossier apres rattachement ;
- complete la tache preuve si le type correspond.

L'analyse OpenAI reste desactivee par defaut. Le fournisseur `fake` permet les tests et la recette sans appel externe.

## Statuts

- `pending` : preuve attendue ;
- `uploaded` : reserve pour une future moderation d'upload ;
- `completed` : preuve ajoutee ou tache terminee manuellement ;
- `skipped` : preuve ignoree avec raison ;
- `cancelled` : tache annulee par une action administrative future.

## Permissions

- `owner` : recalcul, consultation, upload, lien mobile, skip, complete sur tous les restaurants ;
- `manager` : memes actions sur restaurants assignes ;
- `staff` : consultation et upload sur restaurants assignes uniquement ;
- public token : upload limite a une tache precise, sans acces au reste de l'application.

## Garanties

TENNET ne doit jamais inventer une preuve. Aucun email, aucune relance et aucune contestation ne sont envoyes automatiquement par ce workflow.

## Mobile field workflow

On mobile, staff should open `/evidence-tasks`, choose the task card, then upload the requested photo or PDF. Smart Import can also route unknown images or ZIP files toward the evidence import workflow.

TENNET must keep the action simple for field users: take or upload the proof, then let owner/manager continue the financial review.
