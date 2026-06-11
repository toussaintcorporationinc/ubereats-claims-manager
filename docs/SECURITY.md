# Security - Auth and Roles V1

## Authentification

La V1 utilise une authentification simple par JWT Bearer.

- `POST /v1/auth/register` cree uniquement le premier `owner`.
- `POST /v1/auth/login` retourne un `access_token`.
- `GET /v1/auth/me` retourne l'utilisateur courant.

Les mots de passe ne sont pas stockes en clair. Ils sont hashes avec PBKDF2-HMAC-SHA256, un sel aleatoire et une comparaison constante a la verification.

## Configuration

Variables attendues :

- `SECRET_KEY` : obligatoire hors environnements `development`, `local`, `test` et `ci`.
- `ACCESS_TOKEN_EXPIRE_MINUTES` : duree de vie du token.
- `ENVIRONMENT=production` active les validations production.
- `DEBUG=false` est obligatoire en production.
- `BACKEND_CORS_ORIGINS` ne doit jamais contenir `*` en production.
- `DATABASE_URL` doit utiliser PostgreSQL en production.

Le frontend ne recoit aucun secret. `NEXT_PUBLIC_API_BASE_URL` reste la seule variable publique attendue.

## Production deployment security

Regles minimales :

- secrets jamais dans GitHub ;
- `.env.production` non commite ;
- `.env.production.example` contient uniquement des placeholders ;
- `SECRET_KEY` doit etre long, aleatoire et different du template ;
- HTTPS obligatoire devant frontend et backend ;
- Caddy ajoute des headers de securite basiques ;
- l'API ajoute `X-Request-ID`, `X-Content-Type-Options`, `X-Frame-Options` et `Referrer-Policy` ;
- `Strict-Transport-Security` est ajoute en environnement production ;
- rate limit activable via `RATE_LIMIT_ENABLED`, avec limite specifique login ;
- `/version` ne retourne aucun secret ;
- `/ready` verifie DB et stockage persistant sans exposer de donnees sensibles.

Rotation `SECRET_KEY` :

- planifier une fenetre courte ;
- remplacer `SECRET_KEY` dans `.env.production` ;
- redemarrer backend ;
- demander aux utilisateurs de se reconnecter.

La suppression complete restaurant/utilisateur n'est pas encore implementee comme workflow RGPD. En attendant, reduire les donnees stockees au strict necessaire et documenter toute demande de suppression manuelle.

## Stockage des preuves

La V1 stocke les preuves en local avec une interface preparee pour un backend type S3 plus tard.

Variables attendues :

- `EVIDENCE_STORAGE_BACKEND=local`
- `EVIDENCE_STORAGE_DIR`
- `MAX_EVIDENCE_FILE_SIZE_MB`

Regles appliquees :

- les uploads sont proteges par JWT ;
- l'acces est verifie sur le restaurant de la commande ;
- les noms de fichiers internes sont generes par l'application ;
- le nom original est conserve uniquement comme metadonnee ;
- les fichiers vides, trop lourds, avec extension interdite ou MIME interdit sont refuses ;
- un SHA256 est calcule et stocke ;
- le chemin disque absolu n'est pas expose par l'API ;
- les telechargements passent par `GET /v1/evidence/{id}/download`.

## Demandes de preuves et liens mobiles

Les demandes de preuves permettent de collecter les justificatifs manquants sans exposer le reste de l'application.

Regles appliquees :

- `owner` peut recalculer et gerer les demandes de preuves de tous les restaurants ;
- `manager` peut recalculer et gerer les demandes de ses restaurants assignes ;
- `staff` peut consulter et uploader les preuves des restaurants assignes, mais ne peut pas creer de lien mobile, ignorer ou completer manuellement une demande ;
- les liens mobiles sont crees uniquement par `owner` ou `manager` ;
- le token brut est retourne une seule fois a la creation ;
- seul un SHA256 du token est stocke en base ;
- un lien expire via `EVIDENCE_UPLOAD_LINK_EXPIRY_HOURS` ;
- un lien limite le nombre d'usages via `EVIDENCE_UPLOAD_LINK_MAX_USES` ;
- un lien revoque ou expire ne peut plus uploader ;
- l'upload public ajoute uniquement le type de preuve demande par la tache ;
- aucun chemin disque brut n'est expose sur la page publique ;
- chaque creation de tache, creation de lien, revocation, upload et completion est auditee ;
- la page publique n'expose jamais de token Gmail, JWT, secret, mot de passe ou donnees d'un autre dossier.

## Import massif et analyse de preuves

L'import massif de preuves est reserve aux utilisateurs connectes et autorises.

Variables attendues :

- `BULK_EVIDENCE_MAX_FILES_PER_BATCH`
- `BULK_EVIDENCE_MAX_ZIP_SIZE_MB`
- `BULK_EVIDENCE_MAX_FILE_SIZE_MB`
- `BULK_EVIDENCE_ALLOWED_EXTENSIONS`
- `AI_EVIDENCE_ANALYSIS_ENABLED=false`
- `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false`
- `AI_EVIDENCE_HIGH_CONFIDENCE_THRESHOLD`
- `AI_EVIDENCE_MEDIUM_CONFIDENCE_THRESHOLD`
- `OCR_LOCAL_ENABLED`
- `OPENAI_API_KEY`
- `OPENAI_EVIDENCE_MODEL`

Regles appliquees :

- `owner` peut importer et rattacher pour tous les restaurants ;
- `manager` est limite a ses restaurants assignes ;
- `staff` ne gere pas les imports en masse ;
- les extensions et tailles sont controlees avant stockage ;
- les ZIP avec chemin absolu, `..` ou archive imbriquee sont refuses ;
- un checksum SHA256 est stocke pour chaque fichier ;
- le chemin disque brut n'est pas expose ;
- OpenAI vision est refuse tant que `AI_EVIDENCE_ANALYSIS_ENABLED=false` ;
- aucun secret, token, mot de passe ou variable d'environnement ne doit etre envoye a un fournisseur d'analyse ;
- l'attachement automatique reste desactive par defaut ;
- les candidats ambigus restent en revue manuelle ;
- chaque analyse, candidat, decision d'attachement, rejet ou ignore cree une trace auditable.

## Imports CSV/XLSX

Les imports de commandes sont proteges par JWT et ne doivent contenir aucune donnee client reelle dans le code ou les exemples.

Regles appliquees :

- le preview ne cree aucune commande ;
- la confirmation cree uniquement les lignes valides ;
- `owner` peut importer tous les restaurants ;
- `manager` et `staff` sont limites aux restaurants assignes ;
- les lignes hors droits sont marquees `unauthorized` ;
- les doublons existants et internes au fichier sont marques `duplicate` ;
- la taille maximale est controlee par `IMPORT_MAX_FILE_SIZE_MB` ;
- les fichiers acceptes sont limites a `.csv` et `.xlsx`.

## Gmail OAuth, brouillons provider, envoi manuel et lecture inbound

La V1 Gmail cree des brouillons Gmail, permet leur envoi manuel approuve et lit les reponses entrantes. Aucun endpoint n'envoie automatiquement un email et aucune reponse automatique n'est generee.

Variables attendues :

- `EMAIL_PROVIDER_ENABLED=false` par defaut ;
- `GMAIL_OAUTH_CLIENT_ID` ;
- `GMAIL_OAUTH_CLIENT_SECRET` ;
- `GMAIL_OAUTH_REDIRECT_URI` ;
- `GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly` ;
- `DEFAULT_UBER_EATS_SUPPORT_EMAIL` ;
- `EMAIL_MAX_ATTACHMENT_TOTAL_MB` ;
- `GMAIL_INBOUND_SYNC_ENABLED=false` par defaut ;
- `GMAIL_INBOUND_SYNC_LOOKBACK_DAYS` ;
- `GMAIL_INBOUND_MAX_MESSAGES_PER_SYNC` ;
- `GMAIL_SUPPORT_SENDER_FILTER`.

Regles appliquees :

- OAuth `state` est obligatoire et signe ;
- les tokens Gmail ne sont jamais retournes par l'API ;
- les tokens Gmail ne doivent jamais etre logges ;
- les secrets OAuth restent uniquement dans l'environnement serveur ;
- `EmailProviderDraft` conserve l'historique des brouillons crees sans exposer les tokens ;
- la deconnexion supprime les tokens stockes et conserve l'historique provider ;
- les pieces jointes sont lues via le service de stockage des preuves ;
- la limite totale de pieces jointes est controlee avant appel Gmail ;
- `owner` peut creer un brouillon Gmail pour tous les restaurants ;
- `manager` peut creer un brouillon Gmail pour ses restaurants assignes ;
- `staff` ne peut pas creer de brouillon Gmail.
- l'envoi exige `confirm_send=true` ;
- `owner` peut envoyer pour tous les restaurants ;
- `manager` peut envoyer pour ses restaurants assignes ;
- `staff` ne peut pas envoyer ;
- un `EmailProviderDraft` deja `sent` ne peut pas etre renvoye ;
- les statuts finaux de commande bloquent l'envoi ;
- un `EmailThread` outbound est cree apres envoi ;
- `AuditLog` trace `send_gmail_draft` et `send_gmail_draft_failed` sans tokens ni secrets.
- la lecture inbound requiert `gmail.readonly` et peut exiger une reconnexion OAuth des comptes deja connectes ;
- les reponses Gmail sont stockees dans `InboundEmailMessage` sans tokens ni secrets ;
- les messages sont dedupliques par compte Gmail et id message provider ;
- les messages non rattaches restent `unlinked` tant qu'aucun match fiable n'existe ;
- `owner` et `manager` peuvent lancer la sync inbound, `staff` ne peut pas ;
- `staff` peut consulter uniquement les messages rattaches aux restaurants assignes ;
- un `EmailThread` inbound est cree pour chaque message rattache ;
- aucun endpoint inbound ne supprime, modifie ou repond a un email Gmail.
- le traitement manuel d'une reponse cree un `ClaimResponseReview` et ne modifie jamais Gmail ;
- `owner` peut traiter les reponses de tous les restaurants ;
- `manager` peut traiter les reponses de ses restaurants assignes ;
- `staff` ne peut pas traiter une reponse Uber ;
- les statuts `payment_confirmed` et `closed` protegent la commande contre une nouvelle decision non ignoree ;
- les audits de traitement ne stockent aucun token, secret ou mot de passe.

## Relances controlees

Les relances V1 sont des taches et des brouillons, pas des envois.

Regles appliquees :

- `owner` peut recalculer et gerer les relances de tous les restaurants ;
- `manager` peut recalculer et gerer les relances de ses restaurants assignes ;
- `staff` peut consulter selon ses droits mais ne peut pas recalculer, creer, ignorer ou terminer une relance ;
- une seule tache par `order_id + task_type` limite les doublons ;
- `MAX_FOLLOWUPS_PER_ORDER` limite le nombre de relances ;
- les statuts finaux ne sont jamais relances ;
- une reponse inbound non traitee dirige vers `manual_review` ;
- `FOLLOWUP_AUTOMATIC_SEND_ENABLED` ne declenche aucun envoi automatique ;
- chaque recalcul, creation de brouillon, skip et completion est audite.

## AutoPilot controle

AutoPilot V1.2 ajoute un envoi Gmail automatique strictement controle. Il est desactive par defaut et ne doit jamais etre active sans validation operationnelle.

Regles de securite :

- `AUTOPILOT_ENABLED=false` par defaut ;
- `AUTOPILOT_INITIAL_CLAIMS_ENABLED=false`, `AUTOPILOT_FOLLOWUPS_ENABLED=false` et `AUTOPILOT_APPEALS_ENABLED=false` par defaut ;
- chaque restaurant doit avoir `autopilot_enabled=true` avant d'etre eligible ;
- Gmail doit etre active et connecte si `AUTOPILOT_REQUIRE_GMAIL_CONNECTED=true` ;
- les preuves completes sont requises si `AUTOPILOT_REQUIRE_COMPLETE_EVIDENCE=true` ;
- les limites quotidiennes globale et par restaurant bloquent le spam ;
- le cooldown limite les relances et appels repetes ;
- l'arret d'urgence `POST /v1/autopilot/stop` bloque les nouveaux runs ;
- un refus Uber ne cloture jamais automatiquement un dossier ;
- aucune preuve, commande ou montant ne peut etre invente ;
- aucun token Gmail, secret, mot de passe ou contenu `.env` n'est expose par les endpoints AutoPilot ;
- chaque run et chaque action sont traces par `AutopilotRun`, `AutopilotAction` et `AuditLog`.

TENNET ne garantit pas le remboursement. AutoPilot automatise une execution controlee, pas une decision commerciale irreversible.

## Resend

Resend est supporte comme provider transactionnel serveur, desactive par defaut.

Regles de securite :

- `RESEND_ENABLED=false` par defaut ;
- `RESEND_API_KEY` ne doit jamais etre commitee, affichee dans l'UI ou stockee dans l'audit ;
- `RESEND_FROM_EMAIL` doit utiliser un domaine verifie, par exemple `TENNET <notifications@mail.thetennet.com>` ;
- l'envoi via Resend exige une action manuelle avec `confirm_send=true` ;
- Resend ne remplace pas Gmail inbound et ne lit pas les reponses ;
- AutoPilot ne bascule pas automatiquement sur Resend ;
- les logs d'echec ne doivent contenir que des erreurs controlees sans secret.

## Appels persistants apres refus

Un refus Uber ne cloture pas un dossier automatiquement. Il cree ou alimente un workflow d'appel controle.

Variables attendues :

- `APPEAL_AUTO_SEND_ENABLED=false`
- `APPEAL_MIN_DAYS_BETWEEN_ATTEMPTS`
- `APPEAL_MAX_ATTEMPTS_BEFORE_ESCALATION`
- `APPEAL_MAX_ATTEMPTS_BEFORE_MANUAL_REVIEW`
- `APPEAL_REQUIRE_NEW_ARGUMENT_AFTER_REFUSAL`
- `APPEAL_ALLOW_SAME_TEMPLATE_RESEND`

Regles appliquees :

- `owner` peut gerer tous les appels et cloturer/reouvrir manuellement ;
- `manager` gere uniquement ses restaurants assignes ;
- `staff` ne cree pas de brouillon d'appel et ne marque pas d'appel envoye ;
- `APPEAL_AUTO_SEND_ENABLED` ne declenche aucun envoi automatique en V1.1 ;
- les tentatives sont limitees et espacees par cooldown ;
- une meme template non traitee ne peut pas etre recreree en boucle ;
- apres trop de refus, le workflow passe en escalade ou revue manuelle ;
- les brouillons d'appel utilisent uniquement les donnees existantes ;
- les audits ne stockent ni token Gmail, ni secret, ni mot de passe.

## Reporting et exports commerciaux

Les rapports et exports commerciaux sont proteges par JWT et reserves a `owner` et `manager`.

Regles appliquees :

- `owner` peut consulter et exporter tous les restaurants ;
- `manager` peut consulter et exporter uniquement ses restaurants assignes ;
- `staff` ne peut pas acceder aux rapports commerciaux ni exporter ;
- toute requete avec un `restaurant_id` non autorise est refusee ;
- les exports appliquent les memes filtres et permissions que les rapports JSON ;
- `EXPORT_MAX_ROWS` limite le volume exportable ;
- `customer_name` est exclu par defaut des rapports et exports ;
- `include_customer_names=true` est reserve a `owner` et `manager` ;
- aucun export ne contient tokens Gmail, secrets, mots de passe, `access_token`, `refresh_token` ou chemin disque brut de preuve ;
- les fichiers exportes sont generes en memoire pour la V1 et ne sont pas stockes dans le depot.

## Deductions Uber et remboursements clients

Le module Customer Refund Disputes exploite uniquement les transactions Uber deja importees dans TENNET. Il ne se connecte pas a Uber Eats Manager, ne scrape aucune page, ne demande aucun mot de passe Uber et ne declenche aucune contestation automatique.

Regles appliquees :

- `owner` peut detecter, creer des dossiers, creer des brouillons et ignorer les disputes pour tous les restaurants ;
- `manager` peut faire les memes actions uniquement sur restaurants assignes ;
- `staff` ne peut pas detecter, creer de dossier, creer de brouillon, creer de brouillon Gmail ou ignorer une dispute ;
- `staff` peut contribuer aux preuves uniquement via les taches de preuves autorisees ;
- les pieces justificatives restent stockees comme `EvidenceFile` et accessibles uniquement via API protegee ou lien tokenise limite ;
- les transactions brutes peuvent etre conservees dans `raw_payload_json` pour audit, sans token, secret ou mot de passe ;
- les brouillons de contestation restent internes ou Gmail draft, sans envoi automatique ;
- aucun module ne promet un remboursement automatique ou une decision sans validation humaine ;
- chaque detection, creation de dispute, recalcul preuve, creation de dossier, creation de brouillon, brouillon Gmail et ignore cree un `AuditLog`.
- les decisions sur deductions creent un `CustomerRefundDisputeReview` et un `AuditLog` ;
- `payment_confirmed` et `ignored` protegent la dispute contre une transition risquee en V1.1 ;
- les montants recuperes et refus sont saisis manuellement par utilisateur autorise.

## Cockpit recuperation

Le cockpit recuperation agrege des donnees financieres et reste protege.

Regles appliquees :

- `owner` voit tous les restaurants ;
- `manager` voit uniquement ses restaurants assignes ;
- `staff` ne peut pas exporter les rapports financiers recovery ;
- les exports `summary.xlsx` et `cases.csv` appliquent les memes droits que les endpoints JSON ;
- les exports ne contiennent pas tokens Gmail, secrets, mots de passe, `access_token`, `refresh_token`, chemin disque brut de preuve ou contenu de fichier ;
- les actions staff restent limitees aux preuves autorisees par le workflow existant ;
- aucune action du cockpit n'envoie un email, ne cree une relance automatique ou ne modifie Gmail automatiquement ;
- TENNET ne garantit pas le remboursement et ne doit pas presenter le cockpit comme une promesse de recuperation.

## Backups

- sauvegardes PostgreSQL quotidiennes recommandees ;
- sauvegardes preuves/imports quotidiennes recommandees ;
- retention minimale 30 jours ;
- sauvegardes chiffrees recommandees hors host applicatif ;
- restauration testee regulierement ;
- les archives de backup ne doivent pas etre commitees.

Le chiffrement des tokens est encapsule dans `TokenCipherService`. La V1 fournit une protection isolee et remplacable ; une version production plus avancee pourra brancher un KMS ou un gestionnaire de secrets sans changer les routes.

## V1.1 RC staging security

Staging must use `.env.staging`, never `.env.production`.

Rules:

- no production secret in staging;
- no real customer data in committed examples;
- OpenAI/Vision disabled by default;
- Gmail disabled by default;
- inbound Gmail disabled by default;
- follow-up automatic send disabled;
- appeal automatic send disabled;
- recovery and reporting exports still enforce owner/manager permissions;
- final manual closure of appeal workflows remains owner-only.

## Roles

### owner

- acces global ;
- gestion des restaurants ;
- gestion des utilisateurs ;
- creation et modification des commandes ;
- validation des dossiers ;
- generation des brouillons internes ;
- creation de brouillons Gmail ;
- envoi manuel de brouillons Gmail ;
- traitement manuel des reponses Uber ;
- gestion des relances controlees ;
- acces aux rapports et exports commerciaux ;
- dashboard global.

### manager

- acces aux restaurants assignes ;
- creation et modification des commandes de ses restaurants ;
- ajout de preuves ;
- validation des dossiers ;
- generation des brouillons internes ;
- creation de brouillons Gmail pour ses restaurants ;
- envoi manuel de brouillons Gmail pour ses restaurants ;
- traitement manuel des reponses Uber pour ses restaurants ;
- gestion des relances controlees pour ses restaurants ;
- acces aux rapports et exports commerciaux de ses restaurants ;
- dashboard filtre sur ses restaurants.

### staff

- acces aux restaurants assignes ;
- creation de commandes ;
- ajout de preuves ;
- consultation commandes et brouillons ;
- pas de gestion utilisateurs ;
- pas de creation restaurant ;
- pas de validation dossier ;
- pas de generation de brouillon ;
- pas de creation de brouillon Gmail ;
- pas d'envoi Gmail ;
- pas de traitement manuel des reponses Uber ;
- pas de gestion des relances.
- pas d'acces aux rapports commerciaux ni aux exports.

## Audit

Un `AuditLog` est cree pour :

- creation utilisateur ;
- modification utilisateur ;
- assignation restaurant a un utilisateur ;
- suppression d'acces restaurant ;
- login reussi ;
- tentative de login echouee sans stocker le mot de passe ;
- creation de revue de reponse Uber ;
- changement de statut issu d'une revue de reponse Uber ;
- message inbound marque revu ou ignore.
- creation, skip et completion de taches de relance.
- detection, creation, recalcul, brouillon et ignore de disputes de deductions Uber.
- creation de reviews sur deductions Uber.
- changements de statut issus du cockpit ou des reviews de deductions.

## Limites V1

- pas de refresh token applicatif pour les sessions JWT ;
- pas de rotation de cle automatisee ;
- pas d'auth multi-facteur ;
- pas de stockage cloud ;
- pas d'envoi automatique ;
- pas de retry automatique d'envoi Gmail ;
- pas d'envoi automatique de relance ;
- pas de reponse automatique aux messages Gmail entrants ;
- pas de classification IA des reponses Uber ;
- pas d'integration OpenAI.

## Uber Eats Connector

La fondation Uber Mission 18 respecte les regles suivantes :

- aucun scraping de tablette Uber Eats ;
- aucune automatisation de navigateur Uber Eats Manager avec mot de passe ;
- aucun stockage d'identifiant Uber Eats en clair ;
- aucun appel API Uber reel tant que l'approbation et les credentials officiels ne sont pas disponibles ;
- les champs `client_id_encrypted`, `client_secret_encrypted` et `access_token_encrypted` sont reserves a une integration officielle future et ne sont jamais retournes au frontend ;
- les imports CSV/XLSX Uber Eats Manager sont le fallback controle ;
- `owner` seul configure les mappings stores ;
- `manager` voit et exploite uniquement ses restaurants assignes ;
- `staff` n'a pas acces au connecteur Uber ;
- la reconciliation ne cree pas de reclamation envoyee automatiquement ;
- un dossier cree depuis reconciliation reste soumis aux preuves obligatoires TENNET.
- les imports Uber Reporting se font par preview puis confirmation explicite ;
- aucun scraping, aucune connexion tablette Uber et aucune automatisation navigateur Uber Eats Manager ne sont autorises ;
- les resultats de reconciliation peuvent creer un dossier TENNET uniquement apres action manuelle explicite ;
- aucune creation d'email ou contestation Uber n'est declenchee par le moteur de reconciliation ;
- les colonnes inconnues sont ignorees, les colonnes manquantes produisent erreurs/warnings ;
- les stores non mappes ne creent pas automatiquement de restaurant ;
- les exemples CSV fournis sont fictifs et ne contiennent aucune vraie commande.

## Smart Import et UX mobile

- Smart Import stocke uniquement des metadonnees de preview, pas le contenu brut des fichiers.
- Les previews ne doivent jamais exposer token, secret, chemin disque brut ou credential Gmail.
- Les documents inconnus sont envoyes en revue manuelle.
- Les actions `staff` restent limitees a la collecte de preuves autorisee.
- La PWA legere ne stocke pas de donnees sensibles hors ligne.
