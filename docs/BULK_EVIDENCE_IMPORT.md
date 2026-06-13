# Bulk Evidence Import V1.1

TENNET peut importer un volume de preuves existantes sans creer automatiquement de contestation ni envoyer d'email.

Objectif :

- stocker plusieurs fichiers ou un ZIP de preuves ;
- calculer les metadonnees et checksums ;
- supprimer les doublons exacts apres verification SHA256 en conservant un seul fichier canonique ;
- analyser les fichiers avec un fournisseur desactive par defaut ;
- proposer des rattachements vers commandes, taches de preuves, deductions Uber ou resultats de reconciliation ;
- laisser un owner ou manager accepter, rejeter ou ignorer les propositions.

## Formats acceptes

- PDF ;
- images JPEG, PNG, WebP, HEIC et HEIF ;
- ZIP contenant uniquement ces fichiers.

Les chemins dangereux dans un ZIP sont refuses :

- chemins absolus ;
- `..` ;
- ZIP imbriques ;
- fichiers systeme inutiles ignores quand ils sont sans risque.

## Workflow

1. Ouvrir `/evidence-imports/new`.
2. Selectionner un restaurant si l'import est cible.
3. Importer des fichiers ou un ZIP.
4. Ouvrir le batch.
5. Lancer l'analyse `fake` ou `local_ocr` selon configuration.
6. Examiner les fichiers et les candidats.
7. Accepter un rattachement ou ignorer le fichier.
8. TENNET cree alors un `EvidenceFile`, complete la tache preuve si applicable, relance la validation du dossier et cree un `AuditLog`.

## Endpoints

- `POST /v1/evidence-imports`
- `POST /v1/evidence-imports/zip`
- `GET /v1/evidence-imports`
- `GET /v1/evidence-imports/{batch_id}`
- `GET /v1/evidence-imports/{batch_id}/files`
- `POST /v1/evidence-imports/{batch_id}/analyze`
- `POST /v1/evidence-imports/{batch_id}/bulk-accept-high-confidence`
- `GET /v1/evidence-imported-files/{file_id}`
- `GET /v1/evidence-imported-files/{file_id}/preview`
- `POST /v1/evidence-imported-files/{file_id}/attach`
- `POST /v1/evidence-imported-files/{file_id}/ignore`
- `POST /v1/evidence-match-candidates/{candidate_id}/accept`
- `POST /v1/evidence-match-candidates/{candidate_id}/reject`

## Permissions

- `owner` peut importer et traiter toutes les preuves.
- `manager` peut importer et traiter les preuves de ses restaurants assignes.
- `staff` ne gere pas les imports en masse.

## Limites

- aucune preuve n'est inventee ;
- aucun rattachement faible n'est force ;
- l'attachement automatique reste desactive par defaut ;
- aucun email n'est cree ou envoye par l'import.

## V1.1 RC acceptance

Use fictitious PDF/image files or ZIP archives in staging first.

Validate:

- ZIP path traversal is refused;
- nested ZIP is refused;
- `fake` analysis creates deterministic extraction;
- OpenAI/Vision returns disabled unless explicitly enabled;
- high-confidence matches can be accepted;
- evidence tasks complete after attachment;
- claim order validation is retried.

## Smart Import entry point

Operators can start from `/smart-import` with images, PDFs or ZIP files. TENNET recommends `import_evidence_bulk` when the content looks like evidence. After confirmation, Smart Import creates a real `EvidenceImportBatch` and redirects to `/evidence-imports/{batch_id}`.

The normal bulk evidence workflow continues from there: analysis is manual/fake/local unless explicitly configured, attachment is reviewed, and OpenAI remains disabled by default.

The filename is only a hint. It is never required to match a specific naming convention.
