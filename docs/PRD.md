# PRD - Uber Eats Claims Manager

## Objectif

Uber Eats Claims Manager aide a centraliser le suivi des reclamations liees aux commandes Uber Eats d'un ou plusieurs restaurants.

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

## Modeles metier V1

- `Restaurant` : etablissement, email expediteur et identifiant marchand Uber ;
- `ClaimOrder` : commande annulee apres preparation, montant reclame, statut et resultat ;
- `EvidenceFile` : fichier de preuve local attache a une commande avec metadonnees, checksum et acces securise ;
- `EmailDraft` : brouillon interne, sans envoi reel ;
- `EmailAccount` : connexion OAuth Gmail utilisateur, tokens proteges et jamais exposes ;
- `EmailProviderDraft` : historique des brouillons Gmail crees et envoyes manuellement depuis un brouillon interne ;
- `GmailSyncState` : etat de la derniere synchronisation inbound Gmail par compte email ;
- `InboundEmailMessage` : reponse Gmail recue, rattachement automatique ou manuel et extrait stocke ;
- `ClaimResponseReview` : decision humaine prise sur une reponse Uber, avec transition de statut, montant recupere eventuel et notes internes ;
- `FollowUpTask` : tache de relance limitee et auditee, avec echeance, statut et liens vers brouillons internes/provider ;
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

## Exigences techniques

- API HTTP exposee avec FastAPI ;
- configuration par variables d'environnement ;
- PostgreSQL comme base de donnees cible ;
- SQLAlchemy comme couche ORM ;
- Alembic pour les migrations ;
- Pytest pour les tests ;
- Next.js TypeScript pour l'interface ;
- Docker Compose pour lancer backend, frontend et base de donnees.

