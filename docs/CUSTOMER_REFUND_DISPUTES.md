# Customer Refund Disputes V1.1

TENNET detecte les deductions Uber Eats depuis les transactions financieres importees par l'utilisateur. Le module cible les pertes liees aux remboursements clients, chargebacks et ajustements negatifs de versement.

Il ne scrape pas Uber Eats Manager, ne pilote pas de navigateur, ne demande aucun mot de passe Uber et n'envoie aucune contestation automatiquement.

## Types de deductions

Types geres :

- `order_not_received` : client indique commande non recue ;
- `missing_item` : client indique article manquant ;
- `incorrect_item` : mauvaise commande ou mauvais article ;
- `damaged_order` : commande endommagee ;
- `quality_issue` : probleme qualite ;
- `customer_refund` : remboursement client generique ;
- `order_error_adjustment` : ajustement net lie a une erreur de commande ;
- `chargeback` : deduction ou reprise sur versement ;
- `unknown` : motif insuffisant, revue manuelle.

TENNET utilise les montants negatifs et les champs importes comme `transaction_type` ou `raw_payload_json`. En cas de doute, il laisse la dispute en revue manuelle.

## TENNET V1.1 RC2 fixes

La detection analyse maintenant un texte normalise sans accents construit depuis `transaction_type`, `raw_payload_json`, description, line item, reason et notes quand ces champs sont disponibles.

Priorite de classification :

1. `order_not_received`
2. `missing_item`
3. `incorrect_item`
4. `quality_issue`
5. `order_error_adjustment`
6. `chargeback`
7. `customer_refund`
8. `unknown` / `manual_review`

Les motifs ambigus restent en revue manuelle. TENNET ne doit jamais inventer une raison absente.

## Preuves necessaires

Regles V1.2 :

- tous les types exigent `receipt` ;
- `receipt` signifie une photo unique du ticket de caisse agrafe ou pose sur la commande du client ;
- `delivery_proof`, `preparation_proof`, `packaging_photo`, `uber_screenshot` et autres preuves restent des renforts optionnels si Uber les redemande explicitement.

Une preuve manquante bloque la creation du brouillon de contestation. Les preuves peuvent etre ajoutees depuis le dossier TENNET, depuis une tache de preuve ou via un lien mobile tokenise.

## Workflow

1. Importer les transactions Uber via les workflows Uber Reporting.
2. Ouvrir `/customer-refunds`.
3. Lancer `Detecter deductions`.
4. Verifier les disputes detectees et celles en revue manuelle.
5. Creer un dossier TENNET pour une dispute eligible.
6. Fournir les preuves requises.
7. Recalculer les preuves de la dispute.
8. Creer un brouillon interne.
9. Si Gmail est configure, creer un brouillon Gmail.
10. Envoyer manuellement uniquement via le workflow Gmail deja approuve.
11. Traiter manuellement la decision Uber dans le detail de la deduction.
12. Consulter `/recovery` pour suivre le montant detecte, contestable, envoye, recupere, refuse ou en revue manuelle.

Si la decision Uber est un refus, TENNET cree un workflow d'appel dans `/appeals`. Le refus ne cloture pas automatiquement la deduction. Un owner ou manager peut creer un brouillon d'appel, puis un brouillon Gmail si necessaire, sans envoi automatique.

## Traitement manuel des outcomes

Un `owner` ou `manager` peut creer une `CustomerRefundDisputeReview`.

Types de decisions :

- `accepted`
- `payment_to_verify`
- `payment_confirmed`
- `refused`
- `evidence_requested`
- `information_requested`
- `followup_needed`
- `ignored`
- `manual_review`

Effets :

- le statut de la dispute est mis a jour ;
- le dossier TENNET lie est mis a jour si present ;
- `recovered_amount` et `expected_payment_date` sont renseignes si disponibles ;
- une demande de preuve recalcule les exigences et taches ;
- chaque decision est historisee et auditee.

Les statuts `payment_confirmed` et `ignored` sont proteges contre une nouvelle transition en V1.1.

## Permissions

- `owner` : detection, dossiers, brouillons, brouillons Gmail, ignore, tous restaurants.
- `manager` : memes actions sur restaurants assignes.
- `staff` : consultation selon droits et upload de preuves via taches autorisees, sans creation de contestation ni brouillon.

## Audit

TENNET cree un `AuditLog` pour :

- detection run ;
- dispute creee ;
- recalcul evidence ;
- dossier TENNET cree ;
- brouillon interne cree ;
- brouillon Gmail cree ;
- dispute ignoree.
- review de decision creee ;
- statut de deduction ou dossier lie modifie par review.
- workflow d'appel cree ou mis a jour apres refus.

## Limites

- TENNET ne garantit jamais la victoire ni un remboursement.
- TENNET ne doit pas creer de fausse contestation.
- TENNET ne doit pas inventer de montant, motif ou preuve.
- Les exports Uber peuvent varier ; les cas ambigus restent en revue manuelle.
- Aucun email, aucune relance et aucune reponse ne sont envoyes automatiquement.
- Les preuves et decisions restent sous controle humain.

Objectif commercial : aucune deduction significative ne doit rester non revue, tout en gardant une trace claire et responsable.

## V1.1 RC acceptance

Use `docs/examples/v1_1/uber_adjustments_report_sample.csv` to validate:

- customer refund detection;
- order not received;
- missing item;
- negative adjustment;
- chargeback;
- manual review when reason is unclear;
- evidence requirements;
- refusal review opening an appeal workflow.
