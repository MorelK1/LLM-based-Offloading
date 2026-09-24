# Méthodologie d'évaluation — pipeline NL → moteur symbolique

Ce document décrit **comment on évalue**, pas comment le dataset a été généré (pour ça, voir
[`data/enact_scenario/METHODOLOGY.md`](../data/enact_scenario/METHODOLOGY.md)) ni le détail des
résultats obtenus (voir [`data/enact_scenario/RESULTS.md`](../data/enact_scenario/RESULTS.md) et
le notebook [`notebooks/evaluation.ipynb`](notebooks/evaluation.ipynb)).

## 0. Principe directeur : deux couches, jamais fusionnées

Le pipeline a deux points de défaillance indépendants :
- **Extraction** (`intent_grounding_node`, LLM) : le texte NL est-il correctement transformé en
  `Requirement` structuré ?
- **Décision** (`necessity_checker_node` + `decision_engine_node`, code symbolique) : une fois
  un `Requirement` obtenu, le moteur prend-il la bonne décision ?

On a délibérément constaté (voir Partie 3 de `RESULTS.md`) que ces deux couches peuvent échouer
pour des raisons totalement indépendantes — un bug de comparaison d'unités dans le moteur n'a
rien à voir avec une confusion de service par le LLM. **Aucune métrique de ce projet ne mélange
les deux dans un seul score.** Chaque évaluation choisit son périmètre et sa méthode en fonction
de la couche qu'elle vise.

## 1. Architecture en 3 étapes

Reprise à l'identique pour les deux couches, pour la même raison : séparer ce qui coûte cher et
n'est pas reproductible à l'identique (les appels LLM) de ce qui est gratuit et déterministe
(le scoring, l'analyse).

| Étape | Rôle | Appelle le LLM ? | Se relance quand |
|---|---|---|---|
| 1. Run | Exécute le pipeline réel, persiste toute observation brute | Selon la couche | On veut du nouveau comportement observé (nouveau prompt, nouveau modèle...) |
| 2. Score | Compare le brut à la vérité terrain, calcule les métriques | Jamais | On ajuste la logique de scoring, la tolérance, la taxonomie |
| 3. Analyse | Tables, graphes, à partir du scoré uniquement | Jamais | Aussi souvent qu'on veut, sans coût ni risque |

### 1.1 Couche extraction

| Étape | Fichier | Entrée | Sortie |
|---|---|---|---|
| 1 | `scripts/run_nl_evaluation.py` | `data/eval/intent_grounding_enact_extended.jsonl` + `..._clarity_spectrum.jsonl` | `data/nl_evaluation_raw.jsonl` |
| 2 | `scripts/score_nl_evaluation.py` | `data/nl_evaluation_raw.jsonl` | `data/nl_evaluation_scored.csv` |
| 3 | `notebooks/evaluation.ipynb` §1-9, §12 | `data/nl_evaluation_scored.csv` | tables, `figures/*.png` |

**3 runs par cas** (LLM non-déterministe — `llm_openrouter.py` route chaque requête vers un
provider différent, pas de garantie stricte à `temperature=0`) : instabilité mesurable, voir §3.2.

### 1.2 Couche décision

| Étape | Fichier | Entrée | Sortie |
|---|---|---|---|
| 1 | `scripts/run_decision_evaluation.py` | `data/eval/intent_grounding_enact.jsonl` + `..._extended.jsonl` | `data/decision_evaluation_raw.jsonl` |
| 2 | `scripts/score_decision_evaluation.py` | `data/decision_evaluation_raw.jsonl` | `data/decision_evaluation_scored.csv` |
| 3 | `notebooks/evaluation.ipynb` §10-11 | `data/decision_evaluation_scored.csv` | tables |

**1 seul run par cas** : le LLM est contourné, `expected_requirements` est injecté directement
comme vérité terrain — déterministe, relancer donnerait un résultat identique à chaque fois.

## 2. Périmètre : quel fichier alimente quelle évaluation

| Fichier source | Couche extraction | Couche décision | Pourquoi |
|---|---|---|---|
| `intent_grounding_enact.jsonl` (10 cas) | non | oui | RAM uniquement, jamais rejoué au LLM avant cette session |
| `intent_grounding_enact_extended.jsonl` (14 cas) | oui | oui | seul fichier couvert par les deux couches |
| `intent_grounding_enact_clarity_spectrum.jsonl` (20 cas) | oui | **non** | conçu pour tester la clarté du texte, jamais avec un statut violé/satisfait attendu — rien d'honnête à scorer côté décision |
| `intent_grounding_enact_variants.jsonl` (30 cas, préexistant) | non | non | jamais intégré à ces évaluations |

## 3. Définitions exactes des métriques

### 3.1 Extraction (`score_nl_evaluation.py`)

Un requirement extrait et un requirement attendu sont appariés par recouvrement de champs
(`match_lists`), puis comparés (`field_score`) sur 5 champs : `service`, `kpi_type`,
`comparator`, `unit` (égalité stricte), `target_value` (tolérance relative 5%, `values_close`).

- **`n_true_positive` / `n_false_positive` / `n_false_negative`** : comptage au niveau
  requirement individuel (pas au niveau cas), permet de gérer proprement les cas à 0 ou
  plusieurs requirements attendus.
- **`exact_match`** (booléen, par cas×run) : vrai ssi `n_false_positive == 0` ET
  `n_false_negative == 0` — rien manqué, rien en trop, tout correct.
- **`precision`** = ΣTP / (ΣTP + ΣFP), **`recall`** = ΣTP / (ΣTP + ΣFN), **`f1`** = moyenne
  harmonique des deux — toujours calculés sur des compteurs **sommés sur le groupe**, jamais
  moyennés cas par cas.
- **Taux de rejet correct** : cas particulier où `n_expected == 0` (palier 5 uniquement,
  4 cas) — `exact_match` s'y réduit à `n_extracted == 0`.

### 3.2 Décision (`score_decision_evaluation.py`)

- **`expected_necessity_status`** : dérivé du tag `"violated"` déjà présent dans les fichiers
  sources (`reconfiguration_required` si présent, `no_action_needed` sinon) — aucun champ ajouté
  aux fichiers JSONL.
- **`status_correct`** : `necessity_status` observé (calculé par le vrai `necessity_checker_node`
  sur la vérité terrain injectée) == `expected_necessity_status`.
- **`decision_kind`** : `no_change` (aucun service déplacé) / `relocated` (au moins un service
  déplacé) / `no_valid_placement` (le solveur ne trouve aucune configuration valide —
  `ValueError` de `solve_placement`, capturée).

### 3.3 Stabilité inter-run (extraction uniquement)

Nombre de runs à `exact_match == True` sur les 3, par cas — 3/3 = fiable, <3/3 = instabilité
réelle à investiguer (pas un run malchanceux isolé).

## 4. Taxonomies d'erreurs

### 4.1 Extraction — une catégorie unique par (cas, run), priorité dans cet ordre

`sous_extraction` > `sur_extraction` > `confusion_service` > `confusion_kpi` >
`comparateur_inverse` > `unite_incorrecte` > `valeur_incorrecte` > `ok` ; `hallucination_sur_vague`
remplace tout le reste quand `n_expected == 0` et que le LLM a quand même extrait quelque chose.

### 4.2 Décision — dérivée directement du code de `necessity_checker.py`, pas devinée

- **`kpi_non_gere`** : `kpi_type` ∉ {`cpu`, `ram`, `latency`} — `_KPI_TO_NODE_FIELD.get(...)`
  renvoie `None`, la requirement est ignorée (`continue`), ne peut donc jamais apparaître comme
  violée quelle que soit la réalité.
- **`capacite_brute_vs_cible`** : `kpi_type` ∈ {`cpu`, `ram`} — la cible est comparée directement
  à `node.cpu_cores`/`node.ram_gb` (capacité totale brute, unité native), jamais à un usage réel
  ni convertie d'unité.
- **`correct`** : `expected_necessity_status == necessity_status`.

## 5. Limites méthodologiques (à ne jamais omettre en présentant un résultat)

- **La vérité terrain est auto-produite** : j'ai écrit à la fois le texte de chaque intention et
  son `expected_requirements`, dans le même mouvement (voir `data/enact_scenario/METHODOLOGY.md`
  §6-7). Un score mesure donc "le LLM a-t-il compris comme moi", pas une vérité indépendante —
  confirmé concrètement par `enact-109`/`110`/`216`, où la lecture alternative du LLM (unanime
  sur 3 runs) est au moins aussi défendable que la mienne. Aucun accord inter-annotateurs n'a
  été mesuré.
- **Petits effectifs** : 34 cas en extraction (12/palier, 3-30/KPI), 24 en décision. Statistiques
  descriptives seulement, jamais de test de significativité — c'est un pilote, pas un benchmark.
- **`ONE_SHOT`/`FEW_SHOT_SYSTEM_PROMPT` jamais testés** : `intent_grounding_node` utilise
  `ZERO_SHOT_SYSTEM_PROMPT` codé en dur (`intent_grounding.py:11`) — tous les runs LLM de cette
  évaluation, sans exception, sont zero-shot.
- **`bandwidth` (KpiType) a 0 cas de test** — ajouté au schéma, jamais utilisé dans une intention.
- **Le pipeline complet n'est jamais scoré en une seule passe** : extraction (LLM réel) et
  décision (LLM contourné) sont évaluées séparément, sur des exécutions distinctes — jamais
  "LLM réel → decision_engine" chaîné et scoré ensemble pour un même cas.
- **Solveur CP-SAT jamais sollicité** — seul `decision_engine.py` (brute-force) est testé.

## 6. Reproductibilité

```bash
# Couche extraction (appels LLM réels, ~2-3 min)
PYTHONPATH=src venv/bin/python3 experimentation/scripts/run_nl_evaluation.py
venv/bin/python3 experimentation/scripts/score_nl_evaluation.py

# Couche décision (déterministe, pas de LLM, quelques secondes)
PYTHONPATH=src venv/bin/python3 experimentation/scripts/run_decision_evaluation.py
venv/bin/python3 experimentation/scripts/score_decision_evaluation.py

# Analyse (aucun appel LLM, relançable librement)
jupyter nbconvert --to notebook --execute --inplace experimentation/notebooks/evaluation.ipynb
```
