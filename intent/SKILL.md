---
name: generation-intents-arvr150
description: Rédiger à la main (sans aucun algorithme de composition) une intention en langage naturel anglais pour chacun des 150 scénarios ARVR, en traitant les scénarios un par un, avec persistance dans intents.json après chaque scénario et reprise possible à tout moment.
---

# SKILL — Génération manuscrite d'intentions (ARVR-150)

Ce document est la procédure à suivre. Le prompt de travail détaillé est dans
[`PROMPT_GENERATION_INTENTS.md`](PROMPT_GENERATION_INTENTS.md) ; il fait partie de ce skill et se relit
avant chaque série. Les règles sémantiques de référence restent celles de
[`LLM-based-Offloading/eval/CONSIGNES_GENERATION_INTENTS_FR.md`](../eval/CONSIGNES_GENERATION_INTENTS_FR.md) :
ce skill les précise, il ne les remplace pas.

## 0. Règle d'or

**Chaque intention est écrite par moi, à la main, après lecture du scénario.** Il est interdit de produire un
générateur, un gabarit, une table de phrases à trous, un tirage aléatoire de formulations ou toute boucle qui
compose du texte. Le seul code autorisé est [`intent_store.py`](intent_store.py), qui **ne fait que** : afficher
les exigences sans la vérité terrain, vérifier mécaniquement ce que j'ai écrit, enregistrer. Il ne choisit
aucun mot, aucun style, aucune structure : ces choix sont faits par moi, scénario par scénario.

## 1. Livrables

| Fichier (racine) | Rôle |
|---|---|
| `SKILL.md` | cette procédure |
| `PROMPT_GENERATION_INTENTS.md` | prompt de travail que je suis moi-même (rôle, niveaux, interdits, format d'entrée/sortie) |
| `intent_store.py` | `status`, `view`, `append`, `report` — affichage masqué, contrôle, enregistrement atomique |
| `intents.json` | **sortie** : tableau JSON, 1 entrée par scénario, même ordre que `scenarios.json`, construit au fur et à mesure |

Format d'une entrée de `intents.json` (les 4 premiers champs sont ceux demandés par les consignes) :

```json
{
  "scenario_id": "ARVR-000001",
  "intent": "…",
  "review_status": "llm_generated_auto_checked",
  "variant_id": 1,
  "plan": {"style": "…", "register": "…", "structure": "…"},
  "mentions": [{"target_id": "f1", "kpi_type": "e2e_latency", "comparator": "lte",
                "written_value": "0.4", "written_unit": "seconds", "written_form": "0.4 seconds",
                "designation": "flow", "level": 3}],
  "baseline_mentions": [],
  "n_words": 31
}
```

`mentions` documente, pour chaque exigence, **comment** je l'ai écrite (valeur et unité telles qu'écrites,
type de désignation de la cible, niveau d'explicitation). Ces métadonnées servent au contrôle automatique et à
l'analyse ultérieure (accuracy par niveau), jamais à l'extracteur. Ne jamais les transmettre à
l'extracteur ni à l'évaluation du pipeline.

## 2. Ce que j'ai le droit de voir

Pour rédiger : **uniquement** `id` + tableau `requirements` (cible, KPI, comparateur, valeur de base, nouvelle
valeur, unité), plus les noms et descriptions de `services.json` / `flows.json`. Je lis les scénarios
exclusivement avec `python3 intent_store.py view`, qui masque `category`, `level`, `decision`,
`feasible_placements`, `minimum_migrations`, `moved_components`, `p1`, `p1_latency_ms`, `flow_budgets_ms`.
Je n'ouvre pas `scenarios.json` ni `scenarios.csv` pour rédiger. Aucune intention ne doit refléter la décision attendue
(`STAY` / `OFFLOAD` / `INFEASIBLE`) : le ton, l'urgence et la sévérité ne sont jamais corrélés à elle.

## 3. Fondements méthodologiques (à citer)

Les six articles du dépôt n'abordent pas l'intention vague ou implicite ; ils fournissent le cadre de
contrôle de la génération. Ce que le protocole en retient :

| Étape du protocole | Source |
|---|---|
| Entrée atomique, noms sémantiques, unités explicites, ordre d'entrée mélangé (biais du premier cité) | Sundararajan, Sripada & Reiter, NAACL 2024 ; Kasner & Dušek, ACL 2024 ; Chen et al., EMNLP 2022 (sérialisation par gabarit) |
| Plan avant rédaction : quelles exigences, comment, dans quel ordre, regroupées ou non | Zhao & Sun, *Knowledge-Based Systems* 304 (2024) ; Thomson et al., INLG 2023 (vues et schéma de document) |
| Diversité obtenue par le plan, pas par le hasard de l'échantillonnage ; pas d'exemples qui fuient dans la sortie | Kasner & Dušek 2024 (décodage déterministe, « half-shot ») ; Zhao & Sun 2024 (ordre piloté par les exemples) |
| Vérifier après avoir généré, puis corriger (deux passes) | Chen et al. 2022 (délibération) ; Liu, Zheng & Kong, ACL 2025 (génération puis contrôle d'implication) |
| Taxonomie d'erreurs : nombre, nom/cible, comparateur, ajout, contexte | Thomson et al. 2023 ; Sundararajan et al. 2024 ; Kasner & Dušek 2024 |
| Générateur ≠ modèle évalué, à documenter | Kasner & Dušek 2024 ; consignes §8 |

Adaptation propre à ce projet : le « non vérifiable », compté comme faute dans ces articles, est ici
produit volontairement mais **uniquement sur la forme** (voir §5). La valeur d'une exigence n'est jamais floue.

## 4. Protocole par scénario (toujours dans cet ordre)

1. **Lire** : `python3 intent_store.py view next 5` (ou l'id voulu). Lire chaque exigence, ses unités, le sens
   de la variation (hausse CPU/RAM ; latence resserrée *ou* relâchée — le sens se lit en comparant valeur de
   base et nouvelle valeur, il peut être l'un ou l'autre).
2. **Planifier** (à écrire dans `plan` et `mentions`) : pour chaque exigence choisir le niveau d'explicitation
   (§5), le mode de désignation de la cible, l'unité écrite ; puis le style, le registre, la structure de
   l'ensemble, l'ordre de mention (jamais l'ordre du JSON par défaut), le regroupement (une phrase, deux, une
   énumération…), la longueur. Consulter `python3 intent_store.py report` avant chaque série pour équilibrer.
3. **Rédiger** l'intention, en anglais, comme l'écrirait une personne réelle (ticket, message à un
   collègue, note d'exploitation, demande polie…). Pas de recopie de phrases des entrées précédentes.
4. **Relire** contre la liste de contrôle du prompt : valeurs exactes, unités convenues, comparateurs,
   cibles non ambiguës, aucun ajout, aucun mot de placement, direction cohérente avec base→nouvelle valeur.
5. **Enregistrer** : écrire le fichier de lot (JSON écrit à la main), puis
   `python3 intent_store.py append <lot.json>`. Le script écrit **chaque scénario séparément** et de façon
   atomique ; il s'arrête à la première entrée refusée sans perdre les précédentes.
6. En cas de refus ou d'avertissement : corriger mon texte (jamais assouplir le contrôle), ré-enregistrer.

Les scénarios sont traités dans l'ordre strict de `scenarios.json` ; on regroupe par petites séries (5 à 10)
pour limiter les appels, mais l'ordre, le contenu et le fichier final ne portent aucune trace de ce regroupement.

## 5. Niveaux d'explicitation (par exigence)

Le flou porte sur la **désignation**, le **vocabulaire**, la **structure** et le **contexte**. **Il ne porte
jamais sur la valeur** : valeurs exactes, sans arrondi, ni « environ », ni « à peu près ».

| Niveau | Cible | KPI / comparateur | Exemple (valeurs fictives) |
|---|---|---|---|
| 1 explicite | identifiant technique (`C2`, `f1`), éventuellement avec le nom | KPI et unité canoniques, comparateur dit en clair | « Keep the end-to-end latency of flow f2 at or below 412.5 ms. » |
| 2 fonctionnel | nom du composant ou du flux | KPI nommé, unités variées, comparateur en clair | « The AR Rendering component needs at least 5250 millicores. » |
| 3 implicite | description de responsabilité ou référence au flux métier, sans nom ni id | KPI reformulé, comparateur porté par la tournure (« can't take longer than », « needs room for ») ; récit de contexte possible | « With richer overlays coming, whatever draws the augmented-reality elements should get a minimum of 5.25 virtual CPUs. » |
| 4 oblique | cible reconnaissable seulement par raisonnement sur les descriptions du System Model (conséquence, rôle dans la chaîne) ; aucun id, aucun nom | KPI nommé indirectement (« memory headroom », « compute budget », « time to answer ») ; registre familier ou télégraphique ; informations de contexte omises | « The stage that turns detections into overlays is starving — five and a quarter virtual CPUs minimum. » |

Contraintes qui bornent le flou :

- **Toute cible reste identifiable de façon unique** à partir de `services.json`/`flows.json`. Les flux `f1`
  et `f2` partagent `C1`, `C3` et `C5` : ne jamais désigner un flux ni un de ces trois composants de façon qui
  convienne aux deux (« the video path », « the main pipeline » sont proscrits). `f1` = chaîne de
  reconnaissance d'objets ; `f2` = chaîne de rendu AR.
- On peut faire référence à des éléments *non présents* dans le System Model (une mise à jour, un incident,
  une échéance) tant que la cible reste déterminable par les descriptions et que la valeur reste exacte.
- Le comparateur doit rester déductible : « au moins » pour CPU/RAM, « au plus » pour la latence, même quand
  il n'est pas écrit mot à mot.
- Jamais d'action de placement, d'identifiant de nœud, de disponibilité, de fiabilité, de couche
  (edge/cloud/fog/IoT), ni de mot qui dit que l'application doit bouger.

Répartition visée sur l'ensemble des mentions : niveaux 1 ≈ 20 %, 2 ≈ 30 %, 3 ≈ 30 %, 4 ≈ 20 %, mélangés au
sein d'un même scénario multi-exigences, répartis sur les trois KPI et sur les tailles de scénario.

Hors périmètre de cette passe : intentions sans aucun seuil chiffré (abstention attendue). Si besoin, ce sera
un fichier séparé et clairement identifié (`intents_exploratory.json`), à ne pas mélanger à `intents.json`.

## 6. Diversité

- Varier **style** (impératif, demande polie, besoin, contrainte, objectif, récit, note de ticket), **registre**,
  **structure** (une phrase, deux, conditionnelle, énumération, enchaînement), **ordre** (cible, métrique,
  valeur ou objectif d'abord), **longueur** (de ~8 à ~70 mots, une intention de plus de ~90 mots est une
  exception), **ouverture** (ne jamais commencer deux intentions voisines de la même façon), **unités**.
- La variation doit être structurelle, pas lexicale : remplacer « increase » par « raise » ne compte pas.
- Aucune association stable entre un KPI et un tour de phrase, ni entre une taille de scénario et un style.
- Ne pas imiter le début des intentions précédentes pour « suivre le rythme » : relire le rapport de
  diversité (`report`) et prendre volontairement le contraire de ce qui domine.
- Mentionner la valeur de base seulement quand elle sert l'histoire, via `baseline_mentions`, et jamais pour
  préciser un sens que la phrase ne tient pas.

## 7. Persistance et reprise

- `intents.json` est la seule source de vérité. Il existe dès la première entrée enregistrée et ne contient
  jamais d'entrée provisoire.
- `python3 intent_store.py status` donne le nombre d'entrées faites et le prochain `scenario_id` à traiter :
  **toute reprise commence par là**, y compris après une coupure ou une limite d'usage.
- Les entrées enregistrées ne sont pas réécrites en masse. Une correction d'une entrée existante se fait
  seulement sur demande explicite, scénario par scénario, avec nouvelle vérification.
- Le fichier de lot est un fichier de travail jetable (dans le dossier temporaire de la session), jamais un
  livrable.

## 8. Ce que le contrôle automatique vérifie, et ce qu'il ne vérifie pas

Vérifié mécaniquement : ordre des scénarios, couverture des exigences (ni oubli ni ajout), comparateur,
égalité *exacte* entre valeur écrite × facteur d'unité et valeur canonique (arithmétique décimale), présence de
la forme écrite dans le texte, aucun nombre non déclaré (hors identifiants), id présent si et seulement si
la désignation le dit, mots interdits (placement, nœuds, couches, décision), cohérence des verbes de direction avec
base→nouvelle valeur, doublons, longueur.

**Non vérifié** : le sens des désignations de niveau 3 et 4, le naturel, l'ambiguïté d'une cible. Ces points
reposent sur ma relecture (étape 4) et sur une revue humaine ultérieure (hors périmètre ici). `review_status`
reste donc `llm_generated_auto_checked`, jamais `validated`.

## 9. Traçabilité à reporter dans le rapport final

- Le générateur est Claude (Anthropic). L'extracteur évalué dans le pipeline utilise `openai/gpt-5.4-mini`
  via OpenRouter (modèle configurable) : recouvrement à documenter si l'extracteur change.
- Les scénarios sont synthétiques : ne pas présenter ces intentions comme des demandes réelles d'opérateurs.
- Évaluation humaine, accord inter-annotateurs, intentions sans seuil : traités à part.
