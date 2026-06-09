# PRD - TENNET

## Objectif

TENNET aide a centraliser le suivi des reclamations liees aux commandes Uber Eats d'un ou plusieurs restaurants.

La V1 pose la base applicative et les premiers objets metier :

- backend FastAPI ;
- base PostgreSQL ;
- migrations Alembic ;
- frontend Next.js TypeScript ;
- stockage local de fichiers en developpement ;
- tests backend metier.

## Utilisateurs cibles

- proprietaire ou operateur de restaurant ;
- equipe administrative chargee du suivi des remboursements ;
- futur support interne pour traiter les pieces justificatives.

## Perimetre fonctionnel vise pour une V1 produit

- creation et mise a jour des restaurants ;
- creation et suivi des commandes a reclamer ;
- prevention des doublons par restaurant et numero de commande Uber Eats ;
- upload de preuves locales securisees ;
- import massif CSV/XLSX des commandes annulees ;
- consultation de brouillons internes d'emails ;
- creation de brouillons Gmail avec pieces jointes, sans envoi automatique ;
- envoi manuel approuve de brouillons Gmail ;
- lecture et rattachement des reponses Gmail entrantes ;
- traitement manuel des reponses Uber pour accepter, refuser, demander des preuves ou confirmer un paiement ;
- workflow de relances controlees pour dossiers non resolus ;
- file de demandes de preuves et upload mobile par lien tokenise ;
- detection et contestation controlee des remboursements clients, chargebacks et ajustements negatifs Uber ;
- traitement manuel des outcomes de deductions Uber ;
- cockpit unifie de recuperation d'argent ;
- reporting commercial et exports CSV/XLSX ;
- journalisation des creations importantes ;
- authentification et roles utilisateurs ;
- dashboard de synthese.

## Roles utilisateurs V1

- `owner` : acces global, gestion restaurants, gestion utilisateurs, commandes, validation, brouillons et dashboard global.
- `manager` : acces aux restaurants assignes, commandes, preuves, validation, brouillons et dashboard filtre.
- `staff` : acces aux restaurants assignes, creation de commandes, ajout de preuves et consultation. Pas de gestion utilisateurs, pas de creation restaurant, pas de generation de brouillon.

## Workflow utilisateur V1

1. L'utilisateur ouvre le dashboard.
2. Le premier owner initialise l'application via `/setup-owner`.
3. Un owner cree les restaurants et les utilisateurs internes.
4. Un owner assigne les restaurants aux managers et staff concernes.
5. L'utilisateur cree une commande contestee rattachee a un restaurant autorise ou importe un fichier CSV/XLSX.
6. Pour un import massif, il analyse le fichier, corrige les lignes invalides si necessaire, puis confirme les lignes valides.
7. Il ouvre le detail de la commande.
8. Il upload les preuves obligatoires :
   - `cancellation_proof` ;
   - `preparation_proof` ou `waste_photo`.
9. Un owner ou manager valide le dossier.
10. Si le dossier est incomplet, l'interface affiche les elements manquants et les raisons bloquantes.
11. Si le dossier est complet, le statut passe a `ready_to_send`.
12. Un owner ou manager genere un brouillon interne initial.
13. Le brouillon apparait dans le detail commande et dans la page globale des brouillons.
14. Si Gmail est configure, un owner ou manager connecte son compte dans `/settings/email`.
15. Il cree un brouillon Gmail depuis le brouillon interne et choisit d'inclure ou non les preuves.
16. Le brouillon Gmail apparait dans le compte Gmail de l'utilisateur, sans envoi automatique.
17. Il coche la confirmation d'envoi manuel dans l'application.
18. Il clique sur l'envoi Gmail ; la commande passe a `sent`, un `EmailThread` outbound et un `AuditLog` sont crees.
19. Plus tard, un owner ou manager ouvre `/inbox` et lance la synchronisation des reponses Gmail.
20. Les reponses Uber sont rattachees automatiquement par thread Gmail ou numero de commande Uber si le match est fiable.
21. Les messages non rattaches restent visibles comme `unlinked` et peuvent etre rattaches manuellement par un utilisateur autorise.
22. L'historique email apparait dans le detail de la commande, sans reponse automatique.
23. Un owner ou manager traite manuellement la reponse Uber avec un type de decision : `accepted`, `payment_to_verify`, `payment_confirmed`, `refused`, `evidence_requested`, `information_requested`, `followup_needed`, `ignored` ou `manual_review`.
24. L'application met a jour le statut et le resultat de la commande selon la decision, marque le message comme revu si applicable et cree un `AuditLog`.
25. Le dashboard affiche les compteurs de suivi : acceptes, paiements a verifier, paiements confirmes, refuses, revue manuelle et attente de reponse.
26. Si le dossier reste non resolu, un owner ou manager ouvre `/followups` et recalcule les relances controlees.
27. L'application cree au maximum une tache par type : `followup_1` a J+2, `followup_2` a J+5, `escalation` a J+10, puis `manual_review` a J+15.
28. L'utilisateur cree un brouillon interne, puis eventuellement un brouillon Gmail, sans envoi automatique.
29. L'envoi Gmail d'une relance reste manuel, avec confirmation explicite, et la tache peut etre marquee terminee ou ignoree.
30. Un owner ou manager ouvre `/reports` pour analyser les montants reclames, recuperes, en attente et refuses.
31. Il filtre par restaurant, periode, statut, resultat ou montant pour isoler les dossiers prioritaires.
32. Il exporte les commandes, relances, reponses traitees ou le resume commercial en CSV/XLSX selon ses droits.
33. Un owner ou manager ouvre `/uber` pour preparer l'acces officiel aux donnees Uber Eats.
34. Un owner mappe les restaurants TENNET avec leurs stores Uber Eats dans `/uber/stores`.
35. En attendant l'approbation API Uber, un owner ou manager importe des exports Uber Eats Manager dans `/uber/reconciliation`.
36. Pour un backfill de plusieurs mois, il passe par `/uber/reporting/new`, choisit le type de rapport, controle la preview, corrige les stores non mappes puis confirme l'import.
37. TENNET cree des snapshots commandes et transactions financieres uniquement apres confirmation.
38. TENNET rapproche commandes annulees et transactions financieres pour detecter les commandes non compensees.
39. Un owner ou manager cree un dossier TENNET depuis un resultat non compense, puis suit le workflow de preuves et validation existant.
40. Un owner ou manager ouvre `/evidence-tasks` et recalcule les preuves manquantes.
41. TENNET cree une demande par preuve bloquante manquante, sans inventer de justificatif.
42. L'utilisateur peut uploader la preuve depuis la tache ou creer un lien mobile tokenise.
43. Le lien mobile permet uniquement l'upload de la preuve demandee, expire automatiquement et ne stocke que le hash du token.
44. Apres upload, TENNET rattache la preuve, complete la tache, audite l'action et relance la validation du dossier.
45. Un owner ou manager ouvre `/customer-refunds` pour detecter les deductions Uber depuis les transactions financieres importees.
46. TENNET classe les deductions en commande non recue, article manquant, mauvaise commande, probleme qualite, remboursement client, ajustement negatif ou revue manuelle.
47. TENNET cree les exigences de preuves selon le type de deduction et, si un dossier existe, les taches de preuves associees.
48. L'utilisateur cree manuellement un dossier TENNET depuis une deduction eligible.
49. Une fois les preuves completees, l'utilisateur cree un brouillon interne, puis eventuellement un brouillon Gmail.
50. Quand Uber repond ou quand une decision est connue, un owner ou manager traite manuellement la deduction : `accepted`, `payment_to_verify`, `payment_confirmed`, `refused`, `evidence_requested`, `information_requested`, `followup_needed`, `ignored` ou `manual_review`.
51. TENNET conserve un `CustomerRefundDisputeReview`, met a jour le statut de la deduction et du dossier lie si present, puis cree un `AuditLog`.
52. Un owner ou manager ouvre `/recovery` pour visualiser les pertes detectees, contestables, bloquees par preuve, envoyees, recuperees, refusees et en revue manuelle.
53. Il ouvre `/recovery/cases` pour filtrer les cas par restaurant, categorie, etape, montant ou preuve requise.
54. Il ouvre `/recovery/actions` pour traiter la file de travail : preuves, dossiers, brouillons, reponses, relances et revues manuelles.
55. Aucun email, aucune relance et aucune contestation Uber ne sont envoyes automatiquement.

## Modeles metier V1

- `Restaurant` : etablissement, email expediteur et identifiant marchand Uber ;
- `ClaimOrder` : commande annulee apres preparation, montant reclame, statut et resultat ;
- `EvidenceFile` : fichier de preuve local attache a une commande avec metadonnees, checksum et acces securise ;
- `EvidenceRequestTask` : demande de preuve manquante, priorisee, auditee et rattachee a une commande ;
- `EvidenceUploadLink` : lien d'upload mobile tokenise, stocke uniquement sous forme de hash ;
- `UberCustomerRefundDispute` : deduction Uber ou remboursement client detecte depuis une transaction financiere importee ;
- `CustomerRefundEvidenceRequirement` : preuve requise pour contester une deduction client ou ajustement negatif ;
- `CustomerRefundDisputeReview` : decision humaine sur une deduction Uber, avec montants, statuts avant/apres et trace de revue ;
- `RecoveryCockpitService` : service d'agregation des pertes, actions, montants et exports du cockpit recuperation ;
- `EmailDraft` : brouillon interne, sans envoi reel ;
- `EmailAccount` : connexion OAuth Gmail utilisateur, tokens proteges et jamais exposes ;
- `EmailProviderDraft` : historique des brouillons Gmail crees et envoyes manuellement depuis un brouillon interne ;
- `GmailSyncState` : etat de la derniere synchronisation inbound Gmail par compte email ;
- `InboundEmailMessage` : reponse Gmail recue, rattachement automatique ou manuel et extrait stocke ;
- `ClaimResponseReview` : decision humaine prise sur une reponse Uber, avec transition de statut, montant recupere eventuel et notes internes ;
- `FollowUpTask` : tache de relance limitee et auditee, avec echeance, statut et liens vers brouillons internes/provider ;
- `ReportingService` : service applicatif de calcul des indicateurs commerciaux, filtres, permissions et exports ;
- `UberIntegrationAccount` : preparation d'un compte d'integration officielle Uber Eats, sans secret expose ;
- `UberStoreMapping` : association restaurant TENNET vers store Uber Eats ;
- `UberOrderSnapshot` : snapshot de commande Uber importe par API future ou rapport manager ;
- `UberFinancialTransaction` : transaction financiere Uber importee pour reconciliation ;
- `UberReconciliationResult` : resultat de rapprochement compensation / non compensation ;
- `UberReportingImportBatch` : fichier Uber Reporting analyse avant confirmation ;
- `UberReportingImportRow` : ligne de rapport avec raw data, normalisation, erreurs et warnings ;
- `UberReconciliationRun` : execution d'analyse Uber sur une periode donnee ;
- `EmailThread` : historique des conversations email outbound et inbound ;
- `AuditLog` : trace des actions importantes.
- `User` : utilisateur interne avec role ;
- `UserRestaurantAccess` : association utilisateur restaurant.
- `ImportBatch` : fichier CSV/XLSX analyse avant confirmation ;
- `ImportRow` : ligne importee avec statut, erreurs, warnings et commande creee si applicable.

## Hors perimetre de cette premiere base

- integration OpenAI API ;
- envoi automatique Gmail ;
- reponse automatique aux emails entrants ;
- classification IA des reponses Uber ;
- relances automatiques ;
- boucles infinies de relance ;
- automatisation metier des decisions.
- appel API Uber reel sans approbation officielle Uber ;
- scraping tablette Uber Eats ou automatisation Uber Eats Manager par mot de passe.

## Exigences techniques

- API HTTP exposee avec FastAPI ;
- configuration par variables d'environnement ;
- PostgreSQL comme base de donnees cible ;
- SQLAlchemy comme couche ORM ;
- Alembic pour les migrations ;
- Pytest pour les tests ;
- Next.js TypeScript pour l'interface ;
- Docker Compose pour lancer backend, frontend et base de donnees.

