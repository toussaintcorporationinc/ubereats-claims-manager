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

Quand TENNET doute, l'action recommandee devient `manual_review`. Aucune preuve, aucun montant et aucun numero de commande ne sont inventes.
