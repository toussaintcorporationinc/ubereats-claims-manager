# Smart Import TENNET

Smart Import permet de deposer un fichier sans le renommer. TENNET analyse le contenu, detecte le type probable et propose une action.

Formats acceptes :
- CSV et XLSX pour rapports Uber.
- PDF, JPG, JPEG, PNG, WEBP, HEIC, HEIF pour preuves.
- ZIP pour import massif de preuves.

TENNET peut detecter :
- rapport Uber commandes ;
- rapport Uber paiements ;
- rapport Uber ajustements ;
- remboursement client ;
- ticket ;
- preuve annulation ;
- preuve preparation ;
- photo gaspillage ;
- capture Uber ;
- preuve livraison ;
- document inconnu.

Pour les exports Uber avec deux lignes d'en-tete, TENNET scanne les cinq premieres lignes, choisit la ligne qui ressemble le plus a un vrai header et ignore le preambule.

Le resultat affiche :
- type detecte ;
- restaurant probable ;
- periode probable ;
- ligne d'en-tete detectee ;
- colonnes reconnues ;
- niveau de confiance ;
- action recommandee.

Depuis Mission 31, la confirmation lance le vrai workflow TENNET :
- un rapport Uber cree un `UberReportingImportBatch` en statut `parsed`, puis renvoie vers `/uber/reporting/{batch_id}` ;
- une preuve, un PDF ou un ZIP cree un `EvidenceImportBatch`, puis renvoie vers `/evidence-imports/{batch_id}` ;
- un fichier douteux reste en revue manuelle ;
- un fichier ignore est audite.

Exemple :
1. L'utilisateur depose `download.csv`.
2. TENNET detecte "Rapport Uber detecte".
3. L'utilisateur confirme.
4. TENNET cree l'import Uber.
5. L'utilisateur ouvre le batch et confirme les lignes valides.

Smart Import ne confirme jamais automatiquement les lignes financieres Uber. Les preuves ne sont pas auto-attachees, sauf reglage explicite ulterieur et confiance suffisante. OpenAI reste desactive par defaut.

Les fichiers de preview sont conserves temporairement jusqu'a confirmation, avec expiration par defaut apres 24 heures (`SMART_IMPORT_PREVIEW_EXPIRY_HOURS=24`).

Quand TENNET doute, l'action recommandee devient `manual_review`. Aucune preuve, aucun montant et aucun numero de commande ne sont inventes.
