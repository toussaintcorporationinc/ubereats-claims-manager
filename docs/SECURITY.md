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

## Roles

### owner

- acces global ;
- gestion des restaurants ;
- gestion des utilisateurs ;
- creation et modification des commandes ;
- validation des dossiers ;
- generation des brouillons internes ;
- dashboard global.

### manager

- acces aux restaurants assignes ;
- creation et modification des commandes de ses restaurants ;
- ajout de preuves ;
- validation des dossiers ;
- generation des brouillons internes ;
- dashboard filtre sur ses restaurants.

### staff

- acces aux restaurants assignes ;
- creation de commandes ;
- ajout de preuves ;
- consultation commandes et brouillons ;
- pas de gestion utilisateurs ;
- pas de creation restaurant ;
- pas de validation dossier ;
- pas de generation de brouillon.

## Audit

Un `AuditLog` est cree pour :

- creation utilisateur ;
- modification utilisateur ;
- assignation restaurant a un utilisateur ;
- suppression d'acces restaurant ;
- login reussi ;
- tentative de login echouee sans stocker le mot de passe.

## Limites V1

- pas de refresh token ;
- pas de rotation de cle automatisee ;
- pas d'auth multi-facteur ;
- pas de stockage cloud ;
- pas d'envoi reel d'email ;
- pas d'integration Gmail ou OpenAI.
