# Rapport de génération des intentions — ARVR-150

Livrable prévu par `LLM-based-Offloading/eval/CONSIGNES_GENERATION_INTENTS_FR.md` §5. Chiffres calculés sur
[`intents.json`](intents.json) ; détail des contrôles dans [`validation_report.json`](validation_report.json).

## 1. Périmètre et résultat

- 150 scénarios dans `scenarios.json` (`ARVR-000001` à `ARVR-000150`, ids uniques) ; 150 intentions, **une par scénario**,
  dans le même ordre, ids non renumérotés, aucune variante (`variant_id` = 1 partout).
- 315 exigences au total (39 scénarios à 1 exigence, 77 à 2, 14 à 3, 20 à 4) : toutes couvertes, aucune ajoutée.
- Langue : anglais. KPI : `cpu`, `ram`, `e2e_latency` uniquement. Intentions quantitatives, valeurs exactes.

## 2. Méthode

1. **Lecture** d'un scénario par `python3 intent_store.py view`, qui n'affiche que l'`id` et les exigences
   (cible, KPI, comparateur, valeur de base, nouvelle valeur, unité). Les champs `category`, `level`, `decision`,
   `feasible_placements`, `minimum_migrations`, `moved_components`, `p1`, `p1_latency_ms`, `flow_budgets_ms` ne sont jamais affichés ;
   `scenarios.json` n'a pas été ouvert pour rédiger. Contexte applicatif utilisé : noms et descriptions de `services.json` et `flows.json`.
2. **Plan** par scénario (niveau d'explicitation de chaque exigence, désignation de la cible, unité écrite, style, registre,
   structure, ordre de mention, longueur), choisi à la main en consultant `python3 intent_store.py report`.
3. **Rédaction manuelle** de l'intention. Aucun gabarit, aucune table de phrases, aucune composition automatique de texte.
4. **Contrôle automatique** puis enregistrement atomique, scénario par scénario, dans `intents.json` (reprise possible via `status`).
5. Correction du texte en cas de refus (3 refus, tous corrigés par reformulation).

Procédure et règles : [`SKILL.md`](SKILL.md). Prompt de travail : [`PROMPT_GENERATION_INTENTS.md`](PROMPT_GENERATION_INTENTS.md).
Outil de stockage et de contrôle : [`intent_store.py`](intent_store.py) (ne génère aucun texte).

## 3. Modèle et paramètres de génération

- Générateur : Claude (Anthropic), modèle `claude-sonnet-5-5`, en session Claude Code. Rédaction directe dans la conversation :
  **pas de paramètres d'échantillonnage (température, top-p), pas de graine**. La reproductibilité repose sur les fichiers
  (`intents.json` et métadonnées de chaque entrée), pas sur une régénération.
- Les 150 intentions ont été rédigées en 13 séries de 8 à 14 scénarios ; ce regroupement ne laisse aucune trace dans le fichier.
- Recouvrement générateur/extracteur : l'extracteur du pipeline utilise `openai/gpt-5.4-mini` via OpenRouter (modifiable).
  Le recouvrement est nul tant que ce modèle est utilisé ; à réévaluer si l'extracteur devient un modèle Claude.

## 4. Fondements méthodologiques

Six articles de génération texte-à-partir-de-données ont servi de cadre de contrôle (aucun ne traite l'intention vague) :
Kasner & Dušek (ACL 2024) ; Zhao & Sun (*Knowledge-Based Systems* 304, 2024) ; Thomson et al. (INLG 2023) ;
Sundararajan, Sripada & Reiter (NAACL 2024) ; Liu, Zheng & Kong (ACL 2025) ; Chen et al. (EMNLP 2022).
Correspondance article → étape dans `SKILL.md` §3.

## 5. Niveaux d'explicitation et vocabulaire de désignation

Niveaux par exigence : 1 explicite (id), 2 fonctionnel (nom), 3 implicite (rôle ou flux métier), 4 oblique (position, conséquence,
circonlocution). Le flou porte sur la désignation, le vocabulaire, la structure et le contexte, **jamais sur la valeur**.
Unités variées parmi celles admises par les consignes : vCPU, virtual CPUs, mCPU, millicores ; GB, MB ; ms, seconds, µs, microseconds.
Unités binaires (GiB, MiB) non utilisées : leur conversion exacte n'est pas décimale finie.

## 6. Répartition obtenue (315 mentions, 150 intentions)

| Niveau | Mentions | Part | Cible |
|---|---:|---:|---:|
| 1 explicite | 51 | 16 % | 20 % |
| 2 fonctionnel | 106 | 34 % | 30 % |
| 3 implicite | 101 | 32 % | 30 % |
| 4 oblique | 57 | 18 % | 20 % |

| Désignation | n | | Style | n | | Registre | n | | Structure | n |
|---|---:|---|---|---:|---|---|---:|---|---|---:|
| name | 106 | | need_statement | 37 | | developer | 33 | | single_sentence | 64 |
| role | 62 | | narrative | 30 | | ops_terse | 31 | | clause_chain | 38 |
| context | 57 | | constraint_statement | 28 | | casual | 26 | | enumeration | 25 |
| id | 47 | | imperative | 17 | | manager | 22 | | two_sentences | 19 |
| flow | 39 | | goal_oriented / ticket_note | 11 / 11 | | formal | 21 | | conditional | 4 |
| id+name | 4 | | polite_request / question | 9 / 7 | | product_owner | 17 | | | |

KPI : 132 latences, 96 RAM, 87 CPU. Longueur : 7 à 57 mots, médiane 23, moyenne 24,3.

## 7. Règles de filtrage appliquées automatiquement

Refus si : exigence absente ou ajoutée ; comparateur différent ; valeur écrite × facteur d'unité ≠ valeur canonique (arithmétique décimale exacte) ;
forme écrite absente du texte ; nombre non déclaré (hors identifiants) ; id présent alors que la désignation n'en contient pas, ou absent alors
qu'elle en contient ; identifiant de nœud, mot de placement ou de mouvement, couche du continuum, disponibilité, fiabilité, faisabilité,
mot d'approximation, séparateur de milliers, MIPS ; verbe de réduction/relâchement/augmentation incohérent avec base → nouvelle valeur ;
intention identique à une autre. Avertissement seulement : début identique à l'une des 4 intentions précédentes, longueur inhabituelle.

## 8. Revue humaine

**Aucune.** Statut de toutes les entrées : `llm_generated_auto_checked`. La relecture sémantique (sens des niveaux 3 et 4,
unicité de la cible entre `f1` et `f2`, naturel) est à faire par un humain ; une partie du jeu écrite par des humains est recommandée par les consignes §8.

## 9. Limites

- Frontière entre niveaux 3 et 4 non stricte : la périphrase « le flux qui se termine par l'overlay » est étiquetée tantôt 3, tantôt 4.
- Quasi-doublon : ARVR-000137 et ARVR-000140 (mêmes périphrases obliques pour C2 et C4, similarité de mots 0,70).
- Monotonie lexicale partielle : « at least X GB of RAM » revient 16 à 18 fois.
- La longueur croît avec le nombre d'exigences (médiane 15 mots pour une exigence, 45,5 pour quatre) : indice de taille du scénario, non de la décision.
- Les 3 refus de contrôle ont concerné des faux positifs lexicaux (« places », « moves », « around ») ; le texte a été réécrit, le contrôle n'a pas été assoupli.
- Scénarios synthétiques et stratifiés après classification (35 % STAY, 45 % OFFLOAD, 20 % INFEASIBLE) : ne pas présenter ces intentions comme
  représentatives de demandes réelles d'opérateurs, ni les fréquences comme réalistes.
- Hors périmètre de cette passe : intentions sans seuil chiffré (abstention attendue), variantes (`intent_variants.json`), évaluation humaine.

## 10. Usage ultérieur sans fuite

Donner à l'extracteur **uniquement** le champ `intent` (et le contexte applicatif autorisé). Les champs `plan`, `mentions`,
`baseline_mentions`, `n_words` sont des métadonnées d'analyse ; la vérité terrain reste dans `scenarios.json` et n'est lue qu'après la prédiction,
via `scenario_id`.
