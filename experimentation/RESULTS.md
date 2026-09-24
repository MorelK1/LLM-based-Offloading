# Résultats — évaluation NL → moteur symbolique

Tables prêtes à intégrer dans un rapport. Méthode complète (formules, périmètre, limites) dans
[`METHODOLOGY.md`](METHODOLOGY.md) — ce document ne fait que présenter les chiffres. Toutes les
valeurs sont recalculées directement depuis `data/nl_evaluation_scored.csv` et
`data/decision_evaluation_scored.csv` (aucune valeur recopiée à la main).

## Corps du rapport

### 1. Vue d'ensemble — extraction (34 cas × 3 runs = 102, LLM réel)

| Métrique | Valeur |
|---|---:|
| N | 102 |
| Exact match | 85.3% |
| Precision | 94.1% |
| Recall | 88.9% |
| F1 | 91.4% |

### 2. Extraction par palier de clarté (`clarity_spectrum`, n=12/palier)

| Palier | Exact match | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| 1 — explicite | 100.0% | 100.0% | 100.0% | 100.0% |
| 2 — informel | 91.7% | 100.0% | 91.7% | 95.7% |
| 3 — implicite | 100.0% | 100.0% | 100.0% | 100.0% |
| 4 — bruité | 50.0% | 75.0% | 75.0% | 75.0% |
| 5 — vague (rejet attendu) | 100.0% | — | — | — |

*(figure companion : `figures/accuracy_by_clarity_tier.png`)*

Palier 5 : precision/recall non définis (aucun item positif attendu) — voir Table 6 pour le
taux de rejet correct, qui est la métrique pertinente sur ce palier.

### 3. Taxonomie d'erreurs — extraction (agrégée, 102 lignes)

| Catégorie | Occurrences | % du total |
|---|---:|---:|
| ok | 87 | 85.3% |
| confusion_service | 7 | 6.9% |
| sur_extraction | 5 | 4.9% |
| sous_extraction | 3 | 2.9% |
| hallucination_sur_vague | 0 | 0.0% |

*(figure companion : `figures/error_types_by_tier.png`, répartition par palier)*

### 4. Couche décision — LLM contourné, vérité terrain injectée (24 cas, 1 run chacun)

| Métrique | Valeur |
|---|---:|
| `necessity_status` correct | 17/24 (70.8%) |

| Catégorie d'erreur | Occurrences |
|---|---:|
| correct | 17 |
| capacite_brute_vs_cible | 6 |
| kpi_non_gere | 1 |

### 5. Détail des 7 écarts de la couche décision — conséquence réelle sur la configuration

| id | KPI | service | attendu | observé | catégorie | conséquence |
|---|---|---|---|---|---|---|
| enact-001 | ram | C1 | satisfait | violé | capacite_brute_vs_cible | **relocalisé** → `cloud-vm2` |
| enact-003 | ram | C2 | satisfait | violé | capacite_brute_vs_cible | **relocalisé** → `cloud-vm2` (+ `F1`→`fog-node1` en cascade) |
| enact-005 | ram | F1 | satisfait | violé | capacite_brute_vs_cible | aucune configuration valide trouvée |
| enact-007 | ram | F2 | satisfait | violé | capacite_brute_vs_cible | aucune configuration valide trouvée |
| enact-009 | ram | P1 | satisfait | violé | capacite_brute_vs_cible | aucune configuration valide trouvée |
| enact-102 | cpu | F1 | satisfait | violé | capacite_brute_vs_cible | aucune configuration valide trouvée |
| enact-108 | energy | P1 | violé | satisfait | kpi_non_gere | rien détecté, aucune action |

### 6. Taux de rejet correct — palier 5 (4 cas × 3 runs = 12)

| id | runs corrects | taux |
|---|---:|---:|
| enact-217 | 3/3 | 100% |
| enact-218 | 3/3 | 100% |
| enact-219 | 3/3 | 100% |
| enact-220 | 3/3 | 100% |
| **Total** | **12/12** | **100%** |

---

## Annexe

### A1. Extraction par type de KPI (abstentions exclues)

| KPI | n | Exact match | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| cpu | 30 | 100.0% | 100.0% | 100.0% | 100.0% |
| ram | 3 | 100.0% | 100.0% | 100.0% | 100.0% |
| network_in | 6 | 100.0% | 100.0% | 100.0% | 100.0% |
| energy | 24 | 83.3% | 88.5% | 95.8% | 92.0% |
| storage | 12 | 83.3% | 100.0% | 83.3% | 90.9% |
| network_out | 6 | 83.3% | 100.0% | 83.3% | 90.9% |
| latency | 9 | 11.1% | 60.0% | 33.3% | 42.9% |

N très faible pour `ram`/`network_in`/`network_out`/`latency` — à ne pas citer comme résultat
généralisable, `latency` en particulier est expliqué par une vérité terrain ambiguë
(`enact-109`/`110`, voir `data/enact_scenario/METHODOLOGY.md`), pas une faiblesse du LLM en soi.

### A2. Extraction par source de données

| Source | n | Exact match | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| clarity_spectrum | 60 | 88.3% | 93.6% | 91.7% | 92.6% |
| extended | 42 | 81.0% | 94.7% | 85.7% | 90.0% |

### A3. Stabilité inter-run (extraction)

| Runs corrects sur 3 | Nombre de cas |
|---:|---:|
| 3/3 | 30 |
| 2/3 | 2 |
| 1/3 | 1 |
| 0/3 | 1 |

Cas instables : `enact-213` (0/3), `enact-216` (1/3), `enact-206` et `enact-215` (2/3 chacun).

### A4. Croisement extraction × décision (descriptif, pas un score)

| | no_change | no_valid_placement | relocated | total |
|---|---:|---:|---:|---:|
| extraction inexacte | 12 | 0 | 3 | 15 |
| extraction exacte | 69 | 9 | 9 | 87 |
| **total** | **81** | **9** | **12** | **102** |
