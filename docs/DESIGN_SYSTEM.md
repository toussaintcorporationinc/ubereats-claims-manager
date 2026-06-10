# Design System TENNET

Objectif : une interface professionnelle, rapide et lisible, sans effet flashy.

Principes :
- une action claire avant un tableau complexe ;
- une recommandation avant un choix technique ;
- un statut lisible avant un code interne ;
- une carte mobile avant un tableau illisible ;
- une confirmation humaine quand TENNET doute.

Statuts visuels :
- vert : pret, recupere, confirme ;
- orange : preuve manquante, a verifier ;
- rouge : refus, urgent ;
- bleu : envoye, en cours ;
- gris : ignore, cloture.

Composants V1.2 :
- `MobileHeader` ;
- `MobileNavDrawer` ;
- `MobileActionBar` ;
- `ResponsiveDataList` ;
- `SmartImportPreviewCard` ;
- `RecoveryActionCard` ;
- `EvidenceTaskCard` ;
- `PremiumEmptyState` ;
- `PremiumLoadingState` ;
- `PremiumErrorState`.

Les libelles publics doivent masquer les codes internes quand c'est possible :
- `combined_report` devient "Rapport Uber detecte" ;
- `missing_evidence` devient "Preuves manquantes" ;
- `manual_review` devient "A verifier" ;
- `not_compensated` devient "Non compense" ;
- `customer_refund` devient "Remboursement client" ;
- `AppealWorkflow` devient "Appel en cours".
