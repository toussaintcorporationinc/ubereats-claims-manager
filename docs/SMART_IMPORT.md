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

Doublons :
- TENNET calcule le checksum SHA-256 de chaque fichier depose ;
- si deux fichiers ont exactement le meme contenu, TENNET garde le meilleur fichier canonique selon la detection et la confiance ;
- si le meme fichier a deja ete vu dans un depot precedent encore exploitable, TENNET ignore le nouveau depot et pointe vers le fichier canonique deja connu ;
- les copies exactes sont marquees `ignore`, auditees, et leur fichier temporaire est supprime ;
- TENNET ne supprime pas un fichier seulement parce que son nom ressemble a un autre.

Depuis Mission 31, Smart Import lance le vrai workflow TENNET :
- un rapport Uber cree un `UberReportingImportBatch`, applique automatiquement les lignes valides et conserve les lignes a completer pour revue ;
- une preuve, un PDF ou un ZIP cree un `EvidenceImportBatch`, lance l'analyse locale/fake et renvoie vers `/evidence-imports/{batch_id}` ;
- un fichier douteux reste en revue manuelle ;
- un fichier ignore est audite.

Exports officiels Uber Order Accuracy / Top Inaccurate Items :
- si le fichier contient restaurant, commande, date et montant, TENNET le route comme ajustement Uber et cree une transaction de deduction exploitable ;
- si le fichier est agrege et ne contient pas de numero de commande ou de montant fiable, TENNET ne l'ignore pas et ne le supprime pas : il le conserve comme source officielle dans l'import Uber, avec lignes a completer ;
- TENNET n'invente jamais les commandes absentes d'un export agrege.

Depuis le cockpit autonome, Smart Import enchaine ensuite la machine TENNET :
- detection des deductions Uber exploitables ;
- creation des dossiers quand les informations minimales existent ;
- creation des brouillons internes quand les preuves sont completes ;
- recalcul des relances et appels ;
- synchronisation Gmail et AutoPilot uniquement si les flags serveur, Gmail et les limites de securite l'autorisent.

Les fichiers douteux ne sont pas refuses. Ils sont conserves comme sources a completer, visibles dans le resultat, afin de ne jamais perdre un export officiel.

Exemple :
1. L'utilisateur depose `download.csv`.
2. TENNET detecte "Rapport Uber detecte".
3. TENNET cree l'import Uber et applique les lignes fiables.
4. L'utilisateur ouvre le detail uniquement si des lignes sont bloquees ou si TENNET demande une verification.

Smart Import ne confirme pas une information incertaine et n'invente jamais de montant, preuve ou numero de commande. Les preuves ne sont pas auto-attachees, sauf reglage explicite ulterieur et confiance suffisante. OpenAI reste desactive par defaut.

Les fichiers de preview sont conserves temporairement jusqu'a confirmation, avec expiration par defaut apres 24 heures (`SMART_IMPORT_PREVIEW_EXPIRY_HOURS=24`).

Quand TENNET doute, l'action recommandee devient `manual_review`. Aucune preuve, aucun montant et aucun numero de commande ne sont inventes.
