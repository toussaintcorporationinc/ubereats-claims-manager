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
- pas d'upload binaire ;
- pas d'envoi reel d'email ;
- pas d'integration Gmail ou OpenAI.
