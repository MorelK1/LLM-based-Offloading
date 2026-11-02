# Rapport de génération des intentions — ARVR-500

Complète [`intent_generation_report.md`](intent_generation_report.md) (jeu de 150, méthode inchangée). Chiffres calculés sur
[`intents_500.json`](intents_500.json) ; détail dans [`validation_report_500.json`](validation_report_500.json).

## 1. Périmètre

- `eval/experiment_500/scenarios.json` : 500 scénarios, 1057 exigences (136 à 1 exigence, 246 à 2, 43 à 3, 75 à 4).
- Les 150 scénarios du jeu précédent sont **tous contenus** dans les 500, avec des exigences identiques mais des **ids renumérotés**
  (ex. `ARVR-000001` du jeu 150 est `ARVR-000261` dans le jeu 500). Les ids 1 à 150 existent dans les deux jeux mais désignent des scénarios différents.
- `intents_500.json` : 500 entrées, une par scénario, dans l'ordre de `scenarios.json`.
  - **150 reportées** (`carried_over_from`) : texte inchangé, correspondance par égalité exacte du tableau d'exigences, chaque entrée revalidée contre son nouveau scénario.
  - **350 nouvelles** : rédigées à la main dans cette passe, selon le même protocole (`SKILL.md`, `PROMPT_GENERATION_INTENTS.md`).
- `intents.json` (jeu de 150) n'a pas été modifié.

## 2. Méthode et paramètres

Identiques au jeu de 150 : lecture masquée (`intent_store.py view`, vérité terrain cachée), plan, rédaction manuelle, contrôle mécanique, enregistrement atomique par scénario.
Générateur : Claude (`claude-sonnet-5-5`), rédaction directe, aucun paramètre d'échantillonnage ni graine. 350 intentions rédigées en une vingtaine de séries de 12 à 18 scénarios.
**Aucun code ne génère de texte** : `intent_store.py` affiche, contrôle, enregistre (ajouts de cette passe : jeu paramétrable `INTENT_SET`, `carry`, `revise`).
Extracteur évalué : `openai/gpt-5.4-mini` (OpenRouter) ; pas de recouvrement avec le générateur.

## 3. Contrôles et incidents

- Revalidation finale des 500 entrées contre `scenarios.json` : **0 échec** (couverture, comparateurs, valeurs exactes après conversion d'unité, nombres non déclarés, ids, mots interdits, directions, doublons).
- 1 refus du contrôle pendant la rédaction : ARVR-000263, « How **about** … » (mot d'approximation) ; texte réécrit, contrôle inchangé.
- Audit après rédaction : 8 entrées nouvelles corrigées (`revise`, ancien texte conservé dans le champ `revision`) : 6 intentions de moins de 7 mots, et ARVR-000396 qui
  reprenait presque mot pour mot la formulation d'une entrée reportée (ARVR-000082), ainsi que ARVR-000069 proche d'ARVR-000162.
- Après correction : plus petite intention 7 mots ; similarité maximale entre deux intentions (valeurs numériques retirées) 0,70.

## 4. Répartition

| Niveau | 350 nouvelles | 500 au total | Cible |
|---|---:|---:|---:|
| 1 explicite | 22,1 % | 20,3 % | 20 % |
| 2 fonctionnel | 24,1 % | 27,0 % | 30 % |
| 3 implicite | 37,3 % | 35,8 % | 30 % |
| 4 oblique | 16,4 % | 16,9 % | 20 % |

La cible n'est **pas atteinte** : le niveau 3 est surreprésenté de 6 à 7 points, les niveaux 2 et 4 sont sous-représentés. Cet écart vient de la rédaction (désignations par rôle ou par flux),
pas d'un défaut du contrôle.

350 nouvelles : styles need_statement 87, narrative 64, constraint_statement 51, ticket_note 45, imperative 31, goal_oriented 30, polite_request 22, question 20 ;
registres casual 69, developer 75, ops_terse 61, manager 59, product_owner 46, formal 40 ; structures single_sentence 120, clause_chain 115, enumeration 84, two_sentences 23, conditional 8 ;
longueur 7 à 45 mots (médiane 18) ; 289 débuts de deux mots distincts, 143 premiers mots distincts ; KPI : 312 latences, 218 CPU, 212 RAM ; unités variées (ms, seconds, vCPU, mCPU, millicores, virtual CPUs, GB, MB).

## 5. Limites

- **Aucune relecture humaine** : statut `llm_generated_auto_checked` pour les 500.
- Frontière entre niveaux 3 et 4 non stricte ; l'unicité de la cible entre `f1` et `f2` pour les références indirectes n'est pas vérifiée par la machine.
- Monotonie partielle : « minimum » dans 144 intentions sur 500 ; débuts « the stage », « object recognition », « scene processing » répétés 6 à 7 fois parmi les 350 nouvelles.
- La longueur croît avec le nombre d'exigences (médiane 11 mots pour une exigence, 30 pour quatre).
- Scénarios synthétiques et stratifiés : ces intentions ne représentent pas des demandes réelles d'opérateurs.
- Comme pour le jeu de 150 : donner à l'extracteur **uniquement** le champ `intent` ; la vérité terrain n'est lue qu'après la prédiction.
