# Utilisation Mobile Et Tablette

TENNET est concu pour etre utilisable au restaurant, en deplacement et au bureau.

Sur mobile :
- le menu principal est dans un drawer ;
- les tableaux critiques ont une lecture en cartes ;
- les boutons principaux sont larges ;
- les pages operationnelles peuvent afficher une barre d'action sticky ;
- les uploads acceptent images, PDF et ZIP selon le contexte.

Sur tablette :
- les listes peuvent s'afficher a cote du detail quand l'espace le permet ;
- les filtres restent accessibles sans prendre tout l'ecran ;
- les actions rapides restent visibles.

Mode terrain staff :
- priorite aux preuves a fournir ;
- page `/live-evidence` pour imprimer un ticket preuve, scanner un QR code et uploader la photo au bon dossier ;
- prise de photo ou upload simple ;
- pas de cockpit financier avance ;
- pas d'action Gmail, AutoPilot ou appel.

La station preuves peut utiliser une imprimante deja reconnue par le navigateur ou le systeme. Une integration Bluetooth native pourra etre ajoutee plus tard pour imprimer les tickets TENNET, mais elle ne doit jamais lire la tablette Uber Eats ni contourner les imports officiels.

TENNET ne stocke pas de donnees sensibles offline. La PWA legere sert uniquement a faciliter l'ajout a l'ecran d'accueil.
