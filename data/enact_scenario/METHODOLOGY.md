# Méthodologie de génération — `enact_scenario`

Ce document explique **comment** chaque fichier de `data/enact_scenario/` et chaque intention NL
de `data/eval/intent_grounding_enact_extended.jsonl` / `intent_grounding_enact_clarity_spectrum.jsonl`
a été produit — la logique, les sources, les formules. Pour le contenu final et les résultats
d'exécution, voir [`RESULTS.md`](RESULTS.md).

## 0. Contrainte de départ

Rien dans `data/infra/`, `data/app_state/`, ni dans les fichiers `data/eval/` préexistants
(`enact_services.json`, `intent_grounding_enact.jsonl`, `..._variants.jsonl`) n'a été modifié.
Tout ce qui suit est additif, dans `data/enact_scenario/` et deux nouveaux fichiers `data/eval/`.

## 1. Topologie — nœuds (`nodes.csv`)

- `rpi4` et `vm-node` : **repris tels quels** comme `node_id` littéraux (pas de renommage en
  `N2`/`N7`) pour matcher directement `node_name` dans `dataset/enact/*.csv` et `current_node`
  dans `data/eval/enact_services.json` (intouché) sans aucune conversion. Leurs caractéristiques
  (`cpu_cores`, `ram_gb`, ...) sont choisies par analogie avec le vrai matériel qu'ils
  représentent (`rpi4` ≈ un vrai Raspberry Pi 4 : 4 cœurs/1.5GHz/4GB — comparé à `N2` dans
  `data/infra/nodes.csv`, lu en référence sans être copié ; `vm-node` ≈ une VM cloud générique
  modeste, pas la grosse instance GPU `N7` de l'infra d'origine).
- 4 nœuds génériques (`iot-gw1`, `edge-srv1`, `fog-node1`, `cloud-vm2`) : **pas de source
  télémétrique réelle**, spécifications choisies à la main, une par tier manquant (iot, fog) +
  diversité supplémentaire (edge, cloud), en s'inspirant du style/des ordres de grandeur de
  `data/infra/nodes.csv` (jamais copié ligne à ligne).

## 2. Topologie — liens (`links.csv`)

Conçue à la main pour connecter les 6 nœuds de façon cohérente par tier (WiFi entre iot/edge,
Ethernet entre nœuds proches, WAN vers le cloud), sur le même schéma de colonnes que
`data/infra/links.csv`. Un seul lien est ancré sur une observation réelle : `L4`
(`rpi4<->vm-node`), le chemin edge→cloud effectivement mesuré dans la télémétrie — sa latence
(22ms) sert de référence pour tous les calculs de latence cumulée du scénario.

## 3. Services applicatifs (`services_pipeline.json`)

- Les 5 services d'origine (`C1,C2,F1,F2,P1`) sont copiés depuis `data/eval/enact_services.json`
  (mêmes `name`/`description`/`current_node`), avec un seul ajout : `next_services`, pour former
  un DAG exploitable par `pipeline.py:cumulative_latency_ms` (`enact_services.json` d'origine a
  `next_services: []` partout — aucune chaîne testable). Construction du DAG contrainte par
  `build_predecessor_map` (`utils/pipeline.py`), qui lève une erreur si un service a plus d'un
  prédécesseur (pas de point de fusion) : `C2 → [F1, F2]` (branchement, autorisé), `F2 → [P1]` ;
  `C1` et `F1` restent des feuilles.
- `C2-v2` / `F2-v2` (mises à jour plus lourdes de `C2`/`F2`) : ajoutés plus tard, à la demande
  explicite de l'utilisateur, pour tester un scénario d'offload. Placés naïvement sur le nœud de
  la version qu'ils mettent à jour (`current_node` = celui de `C2`/`F2`), sans lien vers la
  suite du pipeline (`next_services: []`) — le point n'est pas leur position dans le DAG mais le
  fait qu'ils ne peuvent structurellement pas tenir sur ce nœud une fois leur exigence exprimée.

## 4. Télémétrie dynamique (`node_state_timeseries.csv`, `link_state_timeseries.csv`)

Générée par [`scripts/generate_enact_telemetry.py`](../../scripts/generate_enact_telemetry.py),
RNG `numpy.random.default_rng(seed=42)` (reproductible à l'identique).

**Nœuds :**
- `rpi4`/`vm-node` : `dataset/enact/node_telemetry_pods_on.csv` rééchantillonné à `15min`
  (`groupby("node_name").resample("15min").mean()`) — donnée réelle, juste moyennée sur des
  fenêtres de 15 minutes pour réduire le volume (18k → 289 lignes/nœud).
- 4 nœuds génériques : tirage `numpy.random.normal(mean, std, n)` par métrique, paramètres
  choisis à la main par analogie de tier (edge/iot ≈ variance proche de `rpi4`, fog/cloud ≈
  variance proche de `vm-node`) — **ce ne sont pas des valeurs mesurées**, seulement des ordres
  de grandeur plausibles. Écrêtage à `[0,1]` pour les `_pct`, à `[0,∞)` pour `energy_w`/`rx_bps`/`tx_bps`.
- Fenêtre de surcharge injectée sur `edge-srv1` : entre 45% et 55% de la timeline,
  `cpu_pct~N(0.92,0.03)`, `mem_pct~N(0.88,0.03)`, `energy_w~N(78,4)` — remplace le tirage normal
  pour ces lignes.

**Liens :**
- `L4` : `bandwidth_utilization_mbps` dérivé des `rx_bps+tx_bps` réels des deux extrémités
  (`(rx_rpi4+tx_rpi4+rx_vm+tx_vm) * 8 / 1e6`) ; `latency_ms`/`packet_loss_rate` = bruit gaussien
  autour de la valeur statique de `links.csv`.
- Autres liens : entièrement synthétiques, `bandwidth_utilization_mbps~N(30% de la capacité, 8%
  d'écart-type)`, `latency_ms`/`packet_loss_rate` = bruit gaussien (15%/30% d'écart-type relatif)
  autour de la baseline statique.
- Fenêtre de dégradation injectée sur `L5` : entre 60% et 68% de la timeline,
  `latency_ms~N(45,8)`, `packet_loss_rate~N(0.08,0.02)`.

**Important (déjà noté dans RESULTS.md §10) :** ces deux fichiers ne sont lus par aucun code du
pipeline aujourd'hui — générés pour un futur chantier moteur, pas branchés.

## 5. Extension du schéma pour accueillir les nouveaux KPI

Deux vagues, purement additives (`Literal[...]` étendus dans `schemas.py`, jamais de champ
retiré) :
1. `energy`/`bandwidth` (unités `W`/`Mbps`) — pour pouvoir exprimer des intentions sur la
   consommation électrique.
2. `storage`/`network_in`/`network_out` (unités `%`/`Mbps`) — pour coller aux colonnes réelles
   de `dataset/enact/node_telemetry_*.csv` (`fs (%)`, `rx (B/sec)`, `tx (B/sec)`) plutôt qu'à des
   unités qui n'existaient que côté moteur.

`prompts/requirement_extraction.py` a été mis à jour en même temps que la vague 2 (glossaire +
règle d'abstention explicite) — sans ça le LLM n'a aucune connaissance de ces KPI et ne peut pas
les extraire correctement (voir RESULTS.md §11).

## 6. Intentions NL — `intent_grounding_enact_extended.jsonl` (14 cas)

**Hand-authored, pas de génération LLM.** Méthode pour chaque cas :
1. Calcul de `mean`/`p95`/`max` par pod sur `dataset/enact/pod_telemetry_pods_on.csv`
   (`groupby("pod_name")[...].mean()/.quantile(0.95)/.max()`) pour `cpu_pct`, `energy_w`, et
   `mem_b` (converti en MB) — c'est la même méthode que celle déjà utilisée par le fixture
   d'origine (`intent_grounding_enact.jsonl`) pour ses 10 cas RAM, étendue ici à cpu/énergie.
2. Choix manuel d'un seuil plancher (`gte`) légèrement **sous** la moyenne mesurée (cas
   confortablement satisfait), ou d'un seuil plafond (`lte`) légèrement **au-dessus** du p95
   (satisfait) ou **en dessous** du max observé (délibérément violé, ex. `enact-108` : plafond
   5W alors que le pic mesuré est 17.9W).
3. Cas de latence bout-en-bout (`enact-109/110/111`) : valeur = sortie exacte de
   `pipeline.py:cumulative_latency_ms` appelée sur le DAG de la section 3 (22ms pour le chemin
   `C2→F2→P1`, 0ms pour `C2→F1` car co-localisés) — pas une mesure télémétrique, une valeur
   topologique calculée.
4. Cas d'offload (`enact-112/113/114`) : cpu/ram demandé délibérément **à l'échelle du nœud
   entier** (10 vCPU, 20GB) plutôt qu'à l'échelle d'un seul service, pour forcer une vraie
   relocalisation plutôt que de retomber dans le bug de comparaison déjà documenté (RESULTS.md
   §8) qui fausse les petites valeurs fractionnaires.

Chaque cas a ensuite été vérifié en le rejouant contre le vrai `necessity_checker`/
`decision_engine` (bypass du LLM, `expected_requirements` injecté directement) —
[`scripts/run_enact_scenario_checks.py`](../../scripts/run_enact_scenario_checks.py).

## 7. Intentions NL — `intent_grounding_enact_clarity_spectrum.jsonl` (20 cas)

**Hand-authored également.** Contrairement à la section 6, l'objectif n'est pas de tester le
moteur symbolique mais **la capacité du LLM à extraire correctement une intention structurée
quand le texte devient de moins en moins explicite**. Méthode :

1. Vocabulaire de KPI restreint à ceux réellement présents dans
   `dataset/enact/node_telemetry_pods_on.csv` (`cpu`, `energy`, `storage`, `network_in`,
   `network_out`) — décision explicite de l'utilisateur, RAM volontairement exclue de ce lot.
2. Seuils ancrés sur les moyennes **par nœud** (et non par pod, contrairement à la section 6) de
   `node_telemetry_pods_on.csv` : `rpi4` (cpu≈0.48 vCPU, fs≈69.2%, energy≈83.6W, rx≈0.30 Mbps,
   tx≈0.34 Mbps) et `vm-node` (cpu≈1.66 vCPU, fs≈76.0%, energy≈84.4W, rx≈5.58 Mbps,
   tx≈7.25 Mbps) — cpu converti en vCPU via `cpu_pct_moyen × cpu_cores_du_nœud`, réseau converti
   en Mbps via `B/sec × 8 / 1e6`.
3. Cinq paliers de clarté écrits à la main, 4 cas chacun (`clarity_tier` 1 à 5), en dégradant
   volontairement et systématiquement : formulation canonique → familière → nombre exprimé en
   toutes lettres/indirect → noyé dans du contexte parasite (distracteurs, justification avant
   le chiffre) → aucun seuil numérique du tout (abstention attendue). Le palier 5 inclut un
   piège délibéré (`enact-220` : "a lot chunkier... need to beef up" évoque un besoin sans jamais
   donner de chiffre, pour vérifier que le LLM n'en invente pas un).
4. Vérité terrain figée **avant** toute exécution du LLM (le fichier JSONL a été écrit en entier
   avant le premier appel réel) — pour que le score mesuré soit une vraie comparaison, pas un
   ajustement a posteriori.

Exécuté 3× par cas via le vrai `intent_grounding_node` (appel LLM réel, OpenRouter) puis
`necessity_checker`/`decision_engine` —
[`scripts/run_enact_clarity_spectrum.py`](../../scripts/run_enact_clarity_spectrum.py). Résultats
détaillés : RESULTS.md, Partie 3.

## 8. Vérification (comment chaque artefact a été validé avant d'être considéré fiable)

- Chargement : `load_nodes`/`load_links`/`load_services` (`data_loader.py`) sur chaque fichier
  statique, sans erreur, sous les modèles Pydantic actuels.
- Schéma : instanciation directe d'`ExtractedRequirement`/`Requirement` pour chaque nouveau
  `kpi_type`/`unit`, sans appel LLM.
- Cohérence référentielle : chaque `expected_requirements[].service` des deux fichiers JSONL
  vérifié comme existant dans `services_pipeline.json` (script, pas de relecture manuelle).
- Comportement réel : les deux scripts `run_enact_*` exécutent le vrai code du pipeline
  (`necessity_checker_node`, `decision_engine_node`, et pour la section 7 `intent_grounding_node`
  avec un vrai appel LLM) plutôt que de simuler le résultat attendu.

## 9. Limites méthodologiques (à ne pas perdre de vue)

- Les nœuds génériques et leur télémétrie synthétique sont des **approximations à dire
  d'expert**, pas calibrées par une vraie mesure ni par un modèle statistique rigoureux (juste
  `numpy.random.normal` avec des paramètres choisis à la main).
- Les fenêtres de dégradation/surcharge (section 4) sont des injections manuelles à des
  positions et amplitudes fixes, pas des événements générés par un processus stochastique réaliste.
- `intent_grounding_enact_clarity_spectrum.jsonl` : la vérité terrain elle-même contient au
  moins un cas à la formulation réellement ambiguë (`enact-216`, voir RESULTS.md §15) — un
  rappel que la difficulté de conception d'un cas peut se confondre avec la difficulté
  d'extraction pour le LLM.
