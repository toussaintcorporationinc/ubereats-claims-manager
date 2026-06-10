# AutoPilot TENNET

AutoPilot est le mode d'envoi automatique controle de TENNET. Il peut envoyer des contestations initiales, relances et appels uniquement lorsque toutes les regles de securite sont remplies.

AutoPilot ne garantit aucun remboursement. Il garantit uniquement une execution tracee, limitee et verifiable des dossiers eligibles.

## Activation

Toutes les variables sont desactivees par defaut :

- `AUTOPILOT_ENABLED=false`
- `AUTOPILOT_INITIAL_CLAIMS_ENABLED=false`
- `AUTOPILOT_FOLLOWUPS_ENABLED=false`
- `AUTOPILOT_APPEALS_ENABLED=false`
- `AUTOPILOT_REQUIRE_COMPLETE_EVIDENCE=true`
- `AUTOPILOT_REQUIRE_GMAIL_CONNECTED=true`
- `AUTOPILOT_NEVER_CLOSE_ON_REFUSAL=true`

En plus des flags globaux, chaque restaurant doit avoir `autopilot_enabled=true`. Cela evite qu'une activation globale envoie sur des restaurants non valides.

## Regles d'envoi

Une contestation initiale peut etre envoyee seulement si :

- Gmail est active et connecte ;
- `AUTOPILOT_ENABLED=true` et `AUTOPILOT_INITIAL_CLAIMS_ENABLED=true` ;
- le restaurant est active et AutoPilot est active pour ce restaurant ;
- le dossier est `ready_to_send` ;
- les preuves obligatoires sont completes ;
- le montant respecte `AUTOPILOT_MIN_AMOUNT` et `AUTOPILOT_MAX_AMOUNT_WITHOUT_OWNER_REVIEW` ;
- aucun email sortant n'a deja ete envoye pour ce dossier ;
- aucune reponse inbound non traitee ne bloque le dossier.

Une relance automatique peut etre envoyee seulement si :

- `AUTOPILOT_FOLLOWUPS_ENABLED=true` ;
- une tache `followup_1`, `followup_2` ou `escalation` est due ;
- le dossier n'est pas dans un statut final ;
- aucune reponse inbound non traitee n'existe ;
- le cooldown `AUTOPILOT_COOLDOWN_HOURS` est respecte ;
- `MAX_FOLLOWUPS_PER_ORDER` n'est pas depasse.

Un appel automatique peut etre envoye seulement si :

- `AUTOPILOT_APPEALS_ENABLED=true` ;
- un `AppealWorkflow` actif existe apres refus ;
- le dossier n'est pas `accepted` ou `payment_confirmed` ;
- le cooldown est respecte ;
- `AUTOPILOT_MAX_APPEAL_ATTEMPTS` n'est pas depasse ;
- la meme template n'est pas renvoyee sans nouvel argument si `APPEAL_ALLOW_SAME_TEMPLATE_RESEND=false`.

## Limites anti-spam

- `AUTOPILOT_DAILY_SEND_LIMIT` limite le volume global quotidien.
- `AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT` limite le volume par restaurant.
- `AUTOPILOT_COOLDOWN_HOURS` espace les relances et appels.
- `AUTOPILOT_MAX_APPEAL_ATTEMPTS` bloque les boucles d'appel.
- Un refus Uber ne cloture jamais automatiquement un dossier.

## Dry-run et audit

`POST /v1/autopilot/dry-run` cree une previsualisation tracee sans envoyer d'email. Les actions sont enregistrees dans `AutopilotAction`.

`POST /v1/autopilot/run` execute les candidats eligibles seulement si les flags sont actifs.

`POST /v1/autopilot/stop` cree un arret d'urgence persistant. Les runs suivants sont refuses tant que l'etat d'urgence reste actif.

Chaque run et chaque envoi cree des `AuditLog`. Aucun secret Gmail, token, mot de passe ou contenu `.env` n'est expose.
