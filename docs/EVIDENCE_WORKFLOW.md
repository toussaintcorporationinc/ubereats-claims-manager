# Evidence workflow V1.1

TENNET utilise les preuves pour verifier qu'un dossier de reclamation Uber Eats est complet avant generation de brouillon.

## Preuves bloquantes

Un dossier n'est pas pret sans :

- `cancellation_proof` ;
- `preparation_proof` ou `waste_photo`.

Le ticket `receipt` reste recommande mais non bloquant dans cette version.

## File de demandes

La page `/evidence-tasks` permet a un owner ou manager de recalculer les preuves manquantes.

TENNET cree une tache par preuve bloquante manquante :

- `cancellation_proof` si la preuve d'annulation manque ;
- `preparation_proof` si aucune preuve de preparation ou photo de gaspillage n'existe ;
- `waste_photo` si le type de perte indique clairement du gaspillage.

Les resultats Uber reconciliation avec `evidence_required=true` peuvent alimenter la priorite quand un dossier TENNET existe deja.

Les deductions Uber detectees depuis transactions financieres creent aussi des exigences de preuves :

- `order_not_received` : `receipt` et `delivery_proof` obligatoires ;
- `missing_item` : `receipt` et `preparation_proof` obligatoires ;
- `incorrect_item` : `receipt` et `preparation_proof` obligatoires ;
- `damaged_order` : `receipt` et `packaging_photo` obligatoires ;
- `quality_issue` : `receipt` et `preparation_proof` obligatoires ;
- `customer_refund`, `order_error_adjustment`, `chargeback` et `unknown` : `receipt` et `uber_screenshot` obligatoires.

Les preuves recommandees comme `sealed_bag_photo`, `order_details_screenshot`, `gps_or_route_proof`, `customer_contact_proof` ou `courier_statement` peuvent renforcer le dossier mais ne sont pas toutes bloquantes en V1.1.

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

## Import massif de preuves

La page `/evidence-imports` permet a un owner ou manager d'importer des fichiers existants en vrac ou via ZIP.

TENNET :

- stocke les fichiers dans le stockage evidence ;
- calcule un checksum SHA256 ;
- refuse les fichiers trop lourds, extensions interdites ou ZIP dangereux ;
- analyse les fichiers avec un fournisseur controle ;
- propose des candidats vers `ClaimOrder`, `EvidenceRequestTask`, `UberCustomerRefundDispute` ou `UberReconciliationResult` ;
- cree une preuve rattachee uniquement apres acceptation manuelle ou seuil haut explicitement valide ;
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
