# TENNET Native Evidence Station + SUNMI Printing

## Objectif

La station native Android transforme TENNET en poste terrain simple :

1. TENNET choisit la prochaine preuve a fournir.
2. Le staff appuie sur `Imprimer et prendre photo`.
3. TENNET imprime un ticket preuve sur l'imprimante ticket Bluetooth appairee.
4. TENNET ouvre directement la camera.
5. La photo est envoyee au bon dossier.

Cote utilisateur, il n'y a pas de tableau technique a comprendre. Cote systeme, le ticket reste trace, tokenise, rattache a une tache de preuve et audite.

## Impression reelle

L'app Android embarque un module natif React Native :

- permissions Android Bluetooth ;
- detection des peripheriques Bluetooth appaires ;
- selection prioritaire des imprimantes `SUNMI`, `Printer`, `POS`, `Ticket` ou `Receipt` ;
- connexion RFCOMM/SPP ;
- ecriture d'un flux ESC/POS ;
- impression du QR code d'upload ;
- retour d'erreur clair si Bluetooth ou imprimante absent.

Le module est ajoute au build Android via `mobile/tennet-native/plugins/withTennetNativePrinter.js`.

## Donnees imprimees

Le ticket imprime uniquement les donnees TENNET connues :

- restaurant ;
- numero commande Uber ;
- montant si connu ;
- type de preuve attendue ;
- reference TENNET ;
- QR code du lien upload tokenise.

TENNET ne fabrique pas un faux ticket Uber. Si les details articles/client ne sont pas presents dans les imports Uber officiels, ils ne sont pas inventes.

## Ce que TENNET ne fait pas

- pas de lecture automatique de tablette Uber Eats ;
- pas de scraping ;
- pas de mot de passe Uber ;
- pas de preuve inventee ;
- pas de montant invente ;
- pas d'email envoye par la station preuves ;
- pas de relance declenchee par l'impression.

Les commandes viennent des sources autorisees : imports Uber Reporting, Gmail connecte, API officielle Uber si approuvee plus tard.

## Verification terrain

1. Installer un build Android contenant le plugin natif.
2. Appairer l'imprimante SUNMI/Bluetooth dans Android.
3. Se connecter dans TENNET mobile avec un compte staff assigne au restaurant.
4. Ouvrir l'app : le premier ecran doit etre `A faire maintenant`.
5. Appuyer sur `Imprimer et prendre photo`.
6. Verifier que le ticket sort de l'imprimante.
7. Prendre la photo quand la camera s'ouvre.
8. Verifier dans TENNET web que la preuve est rattachee a la bonne tache.

## Fallback

Si le build ne contient pas le module natif, l'app peut encore utiliser l'impression systeme via Expo Print. Ce fallback est utile en developpement, mais le mode terrain attendu pour SUNMI/Bluetooth est `android_bluetooth_escpos`.
