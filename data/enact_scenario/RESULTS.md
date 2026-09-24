# Scénario `enact_scenario` — données, cas d'usage, résultats

Reproductible avec :
```bash
PYTHONPATH=src venv/bin/python3 scripts/run_enact_scenario_checks.py
```

## Contexte

Config de départ = données réelles de `dataset/enact/` (2 nœuds télémétrés, 5 services d'une
appli de prévision météo). À partir de là, ajout de nœuds génériques (tous tiers), de mises à
jour plus lourdes de services existants, de télémétrie dynamique (réelle + synthétique) et
d'un catalogue d'intentions NL — sans toucher à `data/infra/`, `data/app_state/`, ni aux
fichiers `data/eval/enact_*` d'origine.

---

## Partie 1 — Données

### 1. Topologie — nœuds (`data/enact_scenario/nodes.csv`)

| node_id | node_name | tier | node_type | cpu_cores | cpu_freq_ghz | ram_gb | storage_gb | mobility | origine |
|---|---|---|---|---:|---:|---:|---:|---|---|
| `rpi4` | RaspberryPi4-Enact | edge | embedded_edge | 4 | 1.5 | 4 | 32 | static | **réel** (télémétrie `dataset/enact/`) |
| `vm-node` | CloudVM-Enact | cloud | cloud_vm | 8 | 2.8 | 16 | 200 | static | **réel** (télémétrie `dataset/enact/`) |
| `iot-gw1` | WeatherStationGateway | iot | iot_gateway | 2 | 1.0 | 1 | 8 | static | générique |
| `edge-srv1` | EdgeMiniServer | edge | mini_server | 6 | 2.4 | 8 | 128 | static | générique |
| `fog-node1` | FogAggregator | fog | fog_node | 8 | 3.0 | 16 | 256 | static | générique |
| `cloud-vm2` | CloudVM-Large | cloud | cloud_vm | 16 | 3.2 | 32 | 500 | static | générique |

Les 4 nœuds génériques couvrent les 4 tiers du continuum (iot/edge/fog/cloud), calibrés par
analogie de style avec `data/infra/nodes.csv` (lu en référence, jamais modifié).

### 2. Topologie — liens (`data/enact_scenario/links.csv`)

| link_id | source | target | type | bandwidth_mbps | latency_ms | packet_loss | reliability |
|---|---|---|---|---:|---:|---:|---:|
| L1 | iot-gw1 | rpi4 | WiFi | 100 | 10 | 0.02 | 0.93 |
| L2 | iot-gw1 | edge-srv1 | WiFi | 100 | 12 | 0.02 | 0.93 |
| L3 | rpi4 | edge-srv1 | WiFi/Ethernet | 500 | 6 | 0.01 | 0.96 |
| L4 | rpi4 | vm-node | WAN | 8000 | 22 | 0.005 | 0.98 |
| L5 | edge-srv1 | fog-node1 | Ethernet | 1000 | 4 | 0.003 | 0.98 |
| L6 | fog-node1 | vm-node | WAN | 9000 | 24 | 0.002 | 0.99 |
| L7 | fog-node1 | cloud-vm2 | WAN | 9000 | 24 | 0.002 | 0.99 |
| L8 | vm-node | cloud-vm2 | Ethernet | 10000 | 2 | 0.001 | 0.995 |

`L4` (`rpi4<->vm-node`) est le chemin edge→cloud réellement observé dans la télémétrie.

### 3. Services applicatifs (`data/enact_scenario/services_pipeline.json`)

| service_id | nom | current_node | next_services | nature |
|---|---|---|---|---|
| `C1` | Weather Collector (Thessaloniki) | rpi4 | — | original |
| `C2` | Weather Collector (Berlin) | rpi4 | `F1`, `F2` | original |
| `F1` | Weather Forecaster (Berlin, Edge) | rpi4 | — | original |
| `F2` | Weather Forecaster (Berlin, Cloud) | vm-node | `P1` | original |
| `P1` | Forecaster Tenant Pool | vm-node | — | original |
| `C2-v2` | Weather Collector (Berlin) v2 — ingestion multi-sources | rpi4 | — | **mise à jour, plus lourde** |
| `F2-v2` | Weather Forecaster (Berlin, Cloud) v2 — modèle d'ensemble | vm-node | — | **mise à jour, plus lourde** |

DAG (contrairement à `data/eval/enact_services.json` d'origine, plat) : `C2 → F1` (co-localisés,
0ms), `C2 → F2 → P1` (traverse `L4`, 22ms cumulés) — nécessaire pour tester des intentions de
latence bout-en-bout. `C2-v2`/`F2-v2` démarrent naïvement sur le nœud de la version qu'ils
mettent à jour, sans lien vers la suite du pipeline.

### 4. Télémétrie dynamique

- **`node_state_timeseries.csv`** (1734 lignes, pas de 15min sur ~3 jours) : `rpi4`/`vm-node`
  = télémétrie **réelle** rééchantillonnée depuis `dataset/enact/node_telemetry_pods_on.csv` ;
  les 4 nœuds génériques = séries **synthétiques** calibrées par tier. Fenêtre de surcharge
  injectée sur `edge-srv1` (cpu_pct ~0.96 au pic vs ~0.26 en moyenne).
- **`link_state_timeseries.csv`** (2312 lignes) : `L4` = utilisation dérivée des `rx_bps`/`tx_bps`
  réels des deux nœuds ; les autres liens = synthétiques. Fenêtre de dégradation injectée sur
  `L5` (latence ~64ms au pic vs ~7ms de base).
- **Non branché dans le pipeline aujourd'hui** — voir §11.

### 5. Catalogue des intentions NL

**Originales, `data/eval/intent_grounding_enact.jsonl`** (10 cas, intouchés, RAM uniquement,
ancrés sur `pod_telemetry_pods_on.csv`) :

| id | service | intent_text |
|---|---|---|
| enact-001 | C1 | The Thessaloniki weather collector needs at least 20MB of RAM to operate. |
| enact-002 | C1 | The Thessaloniki weather collector must not exceed 50MB of memory usage. |
| enact-003 | C2 | The Berlin weather collector requires at least 30MB of RAM. |
| enact-004 | C2 | The Berlin weather collector should stay under 60MB of memory. |
| enact-005 | F1 | The edge-based Berlin forecaster needs at least 200MB of RAM to run its model. |
| enact-006 | F1 | The edge-based Berlin forecaster must not exceed 250MB of memory. |
| enact-007 | F2 | The cloud-based Berlin forecaster requires at least 400MB of RAM to run correctly. |
| enact-008 | F2 | The cloud-based Berlin forecaster should not use more than 420MB of memory. |
| enact-009 | P1 | The forecaster tenant pool needs at least 700MB of RAM available. |
| enact-010 | P1 | The forecaster tenant pool must not exceed 1000MB of memory usage. |

**Étendues, `data/eval/intent_grounding_enact_extended.jsonl`** (14 nouveaux cas) :

| id | service | kpi | intent_text |
|---|---|---|---|
| enact-101 | F1 | cpu | The edge-based Berlin forecaster needs at least 0.02 vCPU to keep running its model. |
| enact-102 | F1 | cpu | The edge-based Berlin forecaster should stay under 0.08 vCPU under normal load. |
| enact-103 | F1 | cpu | The edge-based Berlin forecaster must never go above 0.05 vCPU, full stop. |
| enact-104 | P1 | cpu | The forecaster tenant pool requires at least 0.02 vCPU at baseline. |
| enact-105 | F1 | energy | The edge-based Berlin forecaster won't run on less than 1W of power budget. |
| enact-106 | F1 | energy | The edge-based Berlin forecaster should draw no more than 6W of energy. |
| enact-107 | F2 | energy | The cloud-based Berlin forecaster must not exceed 4W of power consumption. |
| enact-108 | P1 | energy | The forecaster tenant pool can never draw more than 5W of power, no exceptions. |
| enact-109 | P1 | latency | The end-to-end latency of the cloud-based Berlin forecasting path must not exceed 30ms. |
| enact-110 | P1 | latency | Latency on the cloud-based Berlin forecasting path can't go over 15ms. |
| enact-111 | F1 | latency | The edge-based Berlin forecasting path (collector to forecaster) must stay under 5ms of latency. |
| enact-112 | C2-v2 | cpu | We're rolling out the updated Berlin collector that ingests from several providers at once — it needs at least 10 vCPU to keep up. |
| enact-113 | F2-v2 | ram | The new ensemble-model version of the cloud Berlin forecaster needs at least 20GB of RAM to load all its ensemble members. |
| enact-114 | C1 | cpu | The Thessaloniki weather collector's request volume has tripled since new client apps started polling it directly — it now needs at least 12 vCPU to keep up. |

Familles couvertes : plancher/plafond de ressource (`101-108`), latence bout-en-bout (`109-111`),
déploiement d'une mise à jour plus lourde (`112-113`), charge accrue sur un service existant
(`114`) — les 3 derniers sont les déclencheurs d'offload testés en Partie 2.

---

## Partie 2 — Vérification pipeline

Exécution réelle (`necessity_checker_node`, `decision_engine_node`), LLM contourné (les
`expected_requirements` ci-dessus sont injectés directement comme `Requirement` — seule
l'extraction NL→structuré n'est pas testée ici).

### 6. Chargement

| | |
|---|---|
| Nœuds | 6, tous chargés |
| Liens | 8, tous chargés |
| Services | 7, tous chargés |

`load_nodes`/`load_links`/`load_services` parsent tout sans erreur sous les modèles Pydantic actuels.

### 7. Extension de schéma (`KpiType`/`Unit`)

`ExtractedRequirement(kpi_type="energy", unit="W")` et `(kpi_type="bandwidth", unit="Mbps")`
s'instancient sans erreur — l'extension est effective, purement additive.

### 8. Correction des 24 cas NL

`necessity_checker` comparé à l'attendu ("intended", déterminé par la vraie mesure/topologie)
vs. ce que le moteur calcule réellement :

| id | kpi | cmp | target | unit | attendu | moteur | |
|---|---|---|---:|---|---|---|---|
| enact-001 | ram | gte | 20 | MB | satisfied | **violated** | ⚠️ |
| enact-002 | ram | lte | 50 | MB | satisfied | satisfied | |
| enact-003 | ram | gte | 30 | MB | satisfied | **violated** | ⚠️ |
| enact-004 | ram | lte | 60 | MB | satisfied | satisfied | |
| enact-005 | ram | gte | 200 | MB | satisfied | **violated** | ⚠️ |
| enact-006 | ram | lte | 250 | MB | satisfied | satisfied | |
| enact-007 | ram | gte | 400 | MB | satisfied | **violated** | ⚠️ |
| enact-008 | ram | lte | 420 | MB | satisfied | satisfied | |
| enact-009 | ram | gte | 700 | MB | satisfied | **violated** | ⚠️ |
| enact-010 | ram | lte | 1000 | MB | satisfied | satisfied | |
| enact-101 | cpu | gte | 0.02 | vCPU | satisfied | satisfied | |
| enact-102 | cpu | lte | 0.08 | vCPU | satisfied | **violated** | ⚠️ |
| enact-103 | cpu | lte | 0.05 | vCPU | violated | violated | |
| enact-104 | cpu | gte | 0.02 | vCPU | satisfied | satisfied | |
| enact-105 | energy | gte | 1.0 | W | satisfied | satisfied | |
| enact-106 | energy | lte | 6.0 | W | satisfied | satisfied | |
| enact-107 | energy | lte | 4.0 | W | satisfied | satisfied | |
| enact-108 | energy | lte | 5.0 | W | violated | **satisfied** | ⚠️ |
| enact-109 | latency | lte | 30.0 | ms | satisfied | satisfied | |
| enact-110 | latency | lte | 15.0 | ms | violated | violated | |
| enact-111 | latency | lte | 5.0 | ms | satisfied | satisfied | |
| enact-112 | cpu | gte | 10.0 | vCPU | violated | violated | |
| enact-113 | ram | gte | 20.0 | GB | violated | violated | |
| enact-114 | cpu | gte | 12.0 | vCPU | violated | violated | |

**7/24 cas en désaccord** (⚠️) : `enact-001, 003, 005, 007, 009, 102, 108`.

**Cause racine (confirmée, pas juste supposée) :** `necessity_checker`/`csp_checks` comparent
`target_value` directement à `node.cpu_cores`/`node.ram_gb` — la capacité **statique totale**
du nœud, dans ses **unités natives** (cœurs entiers, GB entiers) :
- Les planchers (`gte`) en MB comparent p.ex. `4 >= 20` (4 = `ram_gb` de `rpi4`, jamais converti
  en MB) → faux négatif systématique sur toute cible plancher exprimée en MB.
- `enact-102` (`lte 0.08 vCPU`) compare `4 <= 0.08` → faux positif de violation.
- `enact-108` (`energy`) est **ignoré silencieusement** (`kpi_type` absent de
  `_KPI_TO_NODE_FIELD`) → le pic réel mesuré à 17.9W (contre 5W de plafond) n'est jamais vu.

Ce bug préexistait sur les 10 cas RAM d'origine (pas introduit aujourd'hui) ; distinct du gap
"agrégation de capacité multi-services" déjà identifié et volontairement laissé de côté.

**Les 3 cas de latence (`enact-109/110/111`) et les 3 cas d'offload (`enact-112/113/114`,
en vCPU/GB à l'échelle du nœud entier plutôt qu'en fraction) sont, eux, corrects.**

### 9. Scénarios d'offload (bout en bout, via `decision_engine`)

| id | intention | requirement | statut | décision |
|---|---|---|---|---|
| `enact-112` | *"updated Berlin collector... needs at least 10 vCPU"* | `C2-v2 cpu gte 10.0 vCPU` | `reconfiguration_required` | `C2-v2 → cloud-vm2` |
| `enact-113` | *"ensemble-model version... needs at least 20GB of RAM"* | `F2-v2 ram gte 20.0 GB` | `reconfiguration_required` | `F2-v2 → cloud-vm2` |
| `enact-114` | *"Thessaloniki collector's request volume has tripled... needs at least 12 vCPU"* | `C1 cpu gte 12.0 vCPU` | `reconfiguration_required` | `C1 → cloud-vm2` |

Dans les trois cas : aucun nœud n'est cité dans le texte, `cloud-vm2` est trouvé par recherche
exhaustive (`csp_solver.py`, tous les nœuds de `nodes.csv` explorés) en <1s, et **seul le
service concerné est déplacé** — le reste de la configuration reste identique.

- `enact-112`/`113` : nouveau `service_id` (mise à jour plus lourde d'un service existant),
  placé naïvement sur son nœud d'origine, ne peut pas y tenir.
- `enact-114` : **aucun nouveau `service_id`** — c'est `C1`, le service original, dont
  l'exigence propre est relevée à l'échelle du nœud entier.

### 10. Limites connues, non résolues aujourd'hui (décision explicite)

- Pas d'agrégation de capacité entre services co-localisés (chaque service checké isolément
  contre la capacité totale du nœud).
- Pas de conversion d'unité dans `necessity_checker`/`csp_checks` (bug ci-dessus).
- `energy`/`bandwidth` acceptés par le schéma mais jamais appliqués dans les checks.
- `node_state_timeseries.csv`/`link_state_timeseries.csv` (télémétrie dynamique, réelle +
  synthétique) ne sont lus par aucun code du pipeline pour l'instant — artefacts prêts pour
  un futur chantier moteur, pas encore branchés.

---

## Partie 3 — Spectre de clarté des intentions NL (LLM réel, extraction node-level)

Cette fois-ci, on adapte le pipeline au dataset plutôt que l'inverse : les intentions restent
sur les KPI réellement présents dans `dataset/enact/node_telemetry_pods_on.csv` — **CPU,
Energy, fs (stockage), rx/tx (réseau entrant/sortant)** — plutôt que sur des unités qui
n'existaient que dans le schéma du moteur (RAM). Le moteur symbolique ne sait pas encore agir
sur fs/rx/tx (comme pour `energy` en Partie 2) — c'est acté, un futur chantier étendra
`necessity_checker`/`csp_checks` pour les prendre en compte. `rx`/`tx` étant du débit, pas de
la latence, aucune métrique composite RTT n'a été créée pour l'instant — à revisiter si le
moteur venait à raisonner sur le RTT plutôt que la latence statique de `links.csv`.

### 11. Extension du schéma et du prompt d'extraction

- `schemas.py` : `KpiType` += `storage`, `network_in`, `network_out` ; `Unit` += `%`.
- `prompts/requirement_extraction.py` : le glossaire décrit maintenant les 8 KPI (avec leurs
  unités) et la règle d'abstention est renforcée explicitement pour les intentions vagues sans
  seuil numérique ("it's been acting up", "might need more room to breathe" → liste vide, pas
  de valeur inventée). Nécessaire : sans ça, le LLM n'a aucune connaissance de ces KPI et
  l'expérience ci-dessous serait invalide dès le départ.
- Les 6 nœuds de `enact_scenario` portent déjà ces variables dans `node_state_timeseries.csv`
  (cpu_pct, fs_pct, energy_w, rx_bps, tx_bps) — conforme au schéma du dataset réel, aucun
  changement nécessaire de ce côté.

### 12. Les 20 scénarios (clarté décroissante, `data/eval/intent_grounding_enact_clarity_spectrum.jsonl`)

Ancrés sur les moyennes réelles de `node_telemetry_pods_on.csv` (`rpi4` : cpu≈0.48 vCPU,
fs≈69%, energy≈83.6W, rx≈0.30 Mbps, tx≈0.34 Mbps ; `vm-node` : cpu≈1.66 vCPU, fs≈76%,
energy≈84.4W, rx≈5.58 Mbps, tx≈7.25 Mbps).

| id | tier | kpi | service | intent_text |
|---|---|---|---|---|
| enact-201 | 1 explicite | cpu | C1 | The Thessaloniki collector must be allocated at least 0.4 vCPU at all times. |
| enact-202 | 1 explicite | energy | F2 | The cloud-based Berlin forecaster must not consume more than 90W of power. |
| enact-203 | 1 explicite | storage | P1 | The forecaster tenant pool's disk usage must not exceed 80% of capacity. |
| enact-204 | 1 explicite | network_in | C2 | The Berlin collector needs an inbound bandwidth of at least 0.3 Mbps to fetch weather data reliably. |
| enact-205 | 2 informel | cpu | F1 | Yeah so the edge forecaster shouldn't really go past half a vCPU, otherwise it starts choking. |
| enact-206 | 2 informel | energy | F2-v2 | Ensemble model's power draw needs to stay under 100 watts, can't have it guzzling more than that. |
| enact-207 | 2 informel | network_out | C2-v2 | The upgraded collector shouldn't be pushing out more than 1 Mbps upstream, bandwidth's tight on that link. |
| enact-208 | 2 informel | storage | P1 | The tenant pool needs at least 60% of its storage quota reserved and ready. |
| enact-209 | 3 implicite | energy | C1 | Thessaloniki collector's power budget can't creep past what it's using right now, maybe cap it around 85 watts to be safe. |
| enact-210 | 3 implicite | cpu | F2 | The cloud forecaster's going to need noticeably more compute than before -- figure at least a vCPU and a half. |
| enact-211 | 3 implicite | storage | C2 | Berlin collector's local storage is getting tight, better keep it under three-quarters full. |
| enact-212 | 3 implicite | network_in | F1 | The edge forecaster's inbound feed can't drop below roughly a quarter of a megabit, or the model starves. |
| enact-213 | 4 bruité | energy | P1 | Look, ops flagged three things this week -- the tenant pool's latency, its power draw (should stay under 95W), and some flaky disk alerts, but only the power one's actually urgent. |
| enact-214 | 4 bruité | cpu | C2-v2 | We're onboarding two more data providers for the updated collector, so it'll need at least 2 vCPU dedicated just to keep up with them. |
| enact-215 | 4 bruité | network_out | F2-v2 | Cloud forecaster's ensemble output shouldn't blow past the link's usual ceiling, call it 8 megabits out, tops. |
| enact-216 | 4 bruité | storage | F1 | Edge forecaster's cache needs enough room -- 65% should do it, don't want it thrashing. |
| enact-217 | 5 vague | — | C1 | Thessaloniki collector's been acting up lately, can someone take a look? |
| enact-218 | 5 vague | — | F2 | The cloud forecaster feels kind of heavy right now, might need more room to breathe. |
| enact-219 | 5 vague | — | P1 | Not sure the tenant pool is going to hold up much longer with everything we're throwing at it. |
| enact-220 | 5 vague | — | C2-v2 | The new collector version is a lot chunkier than the old one, we'll probably need to beef up its node at some point. |

Palier 5 : aucun seuil numérique donné nulle part — l'extraction correcte attendue est une
**liste vide** (abstention), pas une valeur inventée.

### 13. Méthode

Exécution réelle de `intent_grounding_node` (LLM via OpenRouter, `ZERO_SHOT_SYSTEM_PROMPT`)
**3 fois** sur chacun des 20 scénarios, puis les requirements extraits sont passés tels quels
à `necessity_checker_node` puis, si nécessaire, `decision_engine_node` — pipeline réel de bout
en bout, aucune vérité terrain injectée directement cette fois.
Reproductible avec :
```bash
PYTHONPATH=src venv/bin/python3 scripts/run_enact_clarity_spectrum.py
```
Résultat brut complet (60 lignes) : `data/eval/enact_clarity_spectrum_run_results.json`.

### 14. Résultats

**Global : 55/60 runs corrects (92%).**

| palier | résultat |
|---|---:|
| 1 — explicite | 12/12 (100%) |
| 2 — informel | 12/12 (100%) |
| 3 — implicite | 12/12 (100%) |
| 4 — bruité | 7/12 (58%) |
| 5 — vague (abstention attendue) | 12/12 (100%) |

**Par cas (score sur 3 runs), seulement ceux <3/3 :**

| id | score | run en écart |
|---|---|---|
| enact-213 | 2/3 | run 2 : sur-extraction — un `storage lte 95%` inventé en plus du bon `energy lte 95W`, en réutilisant la valeur 95 pour "flaky disk alerts" alors qu'aucun seuil disque n'est donné |
| enact-215 | 2/3 | run 1 : bon KPI/valeur, mais résolu sur `F2` au lieu de `F2-v2` — confusion entre le service original et sa mise à jour |
| enact-216 | 0/3 | 2 runs : `lte 65%` au lieu du `gte 65%` attendu ; 1 run : liste vide |

### 15. Ce que ça montre

- **Paliers 1 à 3 (explicite → implicite) : robuste à 100%**, y compris les seuils exprimés en
  toutes lettres ("a vCPU and a half", "three-quarters full", "a quarter of a megabit") — la
  consigne ajoutée au glossaire (§11) sur les nombres en toutes lettres fonctionne.
- **Palier 5 (vague, sans seuil) : 100% d'abstention correcte, aucune hallucination** — y
  compris `enact-220`, conçu spécifiquement comme piège ("a lot chunkier... need to beef up") :
  le LLM ne comble jamais l'absence de chiffre par une valeur inventée. C'est le résultat le
  plus rassurant du lot.
- **Palier 4 (bruité) concentre toute la dégradation (58%)**, avec deux modes d'échec distincts :
  - `enact-213` : un distracteur mentionné sans seuil ("flaky disk alerts") peut occasionnellement
    être promu en requirement halluciné, en recyclant une valeur numérique présente ailleurs dans
    la phrase.
  - `enact-215` : deux services quasi-homonymes (`F2` / `F2-v2`) sont parfois confondus quand le
    texte ne les distingue que par une périphrase ("ensemble output") plutôt que par leur nom.
  Aucun des deux n'est un échec d'abstention (le LLM ne rate jamais un vrai seuil) — les deux
  échecs sont des erreurs de *sur-extraction* ou de *résolution de service*, pas de détection.
- **`enact-216` est un défaut de conception du cas, pas forcément du LLM** : "cache needs enough
  room -- 65% should do it" est réellement ambigu entre "au moins 65%" (ma vérité terrain) et
  "65% suffit, pas plus" (lecture du LLM, cohérente sur 2 runs sur 3) — les deux lectures sont
  défendables ; ce cas mesure surtout ma propre formulation plus que l'extraction.
- **Conséquence en aval (`enact-205`)** : le plafond `0.5 vCPU` déclenche bien
  `reconfiguration_required`, mais `decision_engine` échoue avec *"no placement satisfies..."*
  — cohérent avec le bug déjà documenté en §8 (comparaison à la capacité totale brute du nœud,
  jamais à un usage réel) : ici, *aucun* nœud n'a moins de 0.5 cœur, donc aucun n'est valide,
  pas seulement `rpi4`.
