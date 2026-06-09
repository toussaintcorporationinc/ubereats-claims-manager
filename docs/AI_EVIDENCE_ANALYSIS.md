# AI Evidence Analysis V1.1

L'analyse des preuves est preparee pour classer tickets, photos, captures Uber Eats et justificatifs, mais l'appel OpenAI reel est desactive par defaut.

## Configuration

Variables :

- `AI_EVIDENCE_ANALYSIS_ENABLED=false`
- `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false`
- `AI_EVIDENCE_HIGH_CONFIDENCE_THRESHOLD=0.90`
- `AI_EVIDENCE_MEDIUM_CONFIDENCE_THRESHOLD=0.65`
- `OCR_LOCAL_ENABLED=true`
- `OPENAI_API_KEY=`
- `OPENAI_EVIDENCE_MODEL=`

En CI et en production par defaut, aucun appel OpenAI reel n'est effectue.

## Fournisseurs

- `fake` : analyse deterministe pour tests et recette.
- `local_ocr` : reserve a une analyse locale quand activee.
- `openai_vision` : refuse si `AI_EVIDENCE_ANALYSIS_ENABLED=false` ou si la cle n'est pas configuree.

## Donnees extraites

TENNET peut extraire ou proposer :

- type de preuve ;
- numero de commande Uber ;
- display id ;
- date ;
- montant ;
- devise ;
- mots cles ;
- score classification ;
- score matching.

Les resultats restent des propositions. Les candidats ambigus doivent etre revus par un utilisateur autorise.

## Securite

- les fichiers restent dans le stockage evidence ;
- les chemins disque bruts ne sont pas exposes ;
- les prompts ou resultats ne doivent jamais contenir de secret ;
- les tokens Gmail, JWT, mots de passe et variables d'environnement ne sont jamais envoyes au fournisseur ;
- les actions d'analyse et rattachement sont auditees.

## Regle produit

TENNET ne doit jamais inventer une preuve, un montant, une date ou un numero de commande. Si l'analyse est incertaine, le dossier reste en revue manuelle.
