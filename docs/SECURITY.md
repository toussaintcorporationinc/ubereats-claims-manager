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

Le frontend ne recoit aucun secret. `NEXT_PUBLIC_API_BASE_URL` reste la seule variable publique attendue.

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

## Gmail OAuth, brouillons provider et envoi manuel

La V1 Gmail cree des brouillons Gmail avec le scope `gmail.compose` et permet leur envoi manuel approuve. Aucun endpoint n'envoie automatiquement un email.

Variables attendues :

- `EMAIL_PROVIDER_ENABLED=false` par defaut ;
- `GMAIL_OAUTH_CLIENT_ID` ;
- `GMAIL_OAUTH_CLIENT_SECRET` ;
- `GMAIL_OAUTH_REDIRECT_URI` ;
- `GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.compose` ;
- `DEFAULT_UBER_EATS_SUPPORT_EMAIL` ;
- `EMAIL_MAX_ATTACHMENT_TOTAL_MB`.

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

Le chiffrement des tokens est encapsule dans `TokenCipherService`. La V1 fournit une protection isolee et remplacable ; une version production plus avancee pourra brancher un KMS ou un gestionnaire de secrets sans changer les routes.

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
- dashboard global.

### manager

- acces aux restaurants assignes ;
- creation et modification des commandes de ses restaurants ;
- ajout de preuves ;
- validation des dossiers ;
- generation des brouillons internes ;
- creation de brouillons Gmail pour ses restaurants ;
- envoi manuel de brouillons Gmail pour ses restaurants ;
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
- pas d'envoi Gmail.

## Audit

Un `AuditLog` est cree pour :

- creation utilisateur ;
- modification utilisateur ;
- assignation restaurant a un utilisateur ;
- suppression d'acces restaurant ;
- login reussi ;
- tentative de login echouee sans stocker le mot de passe.

## Limites V1

- pas de refresh token applicatif pour les sessions JWT ;
- pas de rotation de cle automatisee ;
- pas d'auth multi-facteur ;
- pas de stockage cloud ;
- pas d'envoi automatique ;
- pas de retry automatique d'envoi Gmail ;
- pas d'integration OpenAI.
