# Guide — Construction d'un jeu de données d'intentions en langage naturel pour l'Intent-Driven Offloading

**Projet :** Reconfiguration d'une application AR/VR déjà déployée dans le continuum Cloud–Edge–IoT  
**Mission :** Générer et valider des intentions en langage naturel à partir des scénarios du benchmark existant.  

## 1. Objectif et périmètre

Produire **une intention en langage naturel pour chacun des 150 scénarios** du fichier `output/experiment_150/scenarios.json`. Chaque intention doit exprimer fidèlement **toutes les exigences modifiées dans le scénario, et uniquement celles-ci**.

L'application est **déjà déployée** : l'intention exprime une **évolution de ses exigences**, et non une demande de déploiement initial.

Ce jeu de données servira à évaluer le **Requirement Extractor** (langage naturel → exigences structurées), puis l'ensemble du pipeline de décision. *

**Périmètre de cette première version :** intentions quantitatives, avec métrique et valeur explicites, sur trois KPI pris en charge : **CPU, RAM et latence de bout en bout (E2E)**. Les intentions vagues, comme « rends l'application plus rapide », sont exclues, sauf dans un jeu exploratoire séparé et clairement identifié.

## 2. Données d'entrée et référence de vérité

Utiliser l'archive du benchmark fournie avec le projet.

| Fichier | Rôle |
|---|---|
| `output/experiment_150/scenarios.json` | **Source principale** : 150 scénarios et leurs tableaux `requirements` |
| `system_model/services.json` | Identifiants et noms des composants, contexte applicatif |
| `system_model/flows.json` | Identifiants des flux et leur signification |
| `system_model/nodes.csv` | Contexte de l'infrastructure ; **inutile pour formuler les intentions** |

**Composants de l'application cible :** `C1` Vision Capture ; `C2` Object Recognition ; `C3` Scene Processing ; `C4` AR Rendering ; `C5` Display Output.

**Flux considérés :**

- `f1` — Object Recognition Flow : `C1 → C2 → C3 → C5` ;
- `f2` — AR Rendering Flow : `C1 → C3 → C4 → C5`.

**Exemple abrégé de scénario :**

```json
{
  "id": "ARVR-000001",
  "category": "single_flow",
  "requirements": [
    {
      "target_type": "flow",
      "target_id": "f1",
      "kpi_type": "e2e_latency",
      "comparator": "lte",
      "baseline_value": 500.0,
      "new_value": 421.265,
      "unit": "ms"
    }
  ],
  "decision": "OFFLOAD",
  "minimum_migrations": 1,
  "p1": {"C1": 12, "C2": 6, "C3": 6, "C4": 4, "C5": 8}
}
```

**Pour rédiger l'intention, utiliser seulement `id` et `requirements`**, ainsi que les noms issus du System Model si nécessaire. Les informations `category`, `decision`, `minimum_migrations`, `p1`, la faisabilité et les autres résultats de référence sont réservés à l'évaluation : **ne pas les transmettre au générateur d'intentions**.

## 3. Règles de correspondance sémantique

### 3.1. Gestion des unités et conversions

Les intentions doivent utiliser des unités cohérentes avec les métriques prises en charge par notre framework. Cependant, les utilisateurs n'expriment pas nécessairement leurs exigences dans les unités internes du System Model.

Afin d'évaluer la capacité du Requirement Extractor à comprendre et normaliser les exigences, il est demandé de varier les unités lorsque des conversions sémantiquement équivalentes sont possibles.

| KPI | Unité canonique du System Model | Autres unités ou représentations autorisées |
|---|---|---|
| CPU | vCPU | vCPU, virtual CPU, virtual cores, cœurs virtuels, millicores (mCPU) |
| RAM | GB | GB, MB, TB, GiB, MiB (avec convention explicite) |
| Latence E2E | ms | ms, millisecondes, secondes (s), microsecondes (µs) |

**Règles obligatoires :**

1. Toute conversion doit préserver exactement la valeur de l'exigence initiale.
2. Les conversions CPU doivent respecter : 1 vCPU = 1 000 mCPU.
3. Les unités décimales et binaires doivent être distinguées : 1 GB = 1 000 MB ; 1 GiB = 1 024 MiB. Pour passer de GiB/MiB à GB, il faut convertir les octets, et non simplement changer le nom de l'unité.
4. Les conversions temporelles respectent : 1 s = 1 000 ms ; 1 ms = 1 000 µs.
5. La précision numérique doit être conservée, sans arrondi susceptible de modifier la contrainte.
6. Les intentions ambiguës, par exemple « 4 cœurs » sans indication qu'il s'agit de cœurs virtuels, sont à éviter lorsqu'elles ne peuvent pas être résolues à partir du contexte.
7. Ne pas remplacer une exigence en vCPU par une valeur en MIPS : ces deux métriques ne sont pas directement interchangeables.

**Exemples de formulations équivalentes :**

Exigence CPU : `cpu >= 4.5 vCPU`

- "Allocate at least 4.5 virtual CPUs to the object recognition component."
- "The object detection module needs a minimum allocation of 4500 millicores."

Exigence RAM : `ram >= 2.5 GB`

- "Ensure the scene processing component has at least 2.5 GB of RAM."
- "Provide a minimum of 2500 MB of memory to the module responsible for scene analysis."

Exigence E2E : `e2e_latency <= 450 ms`

- "Keep the end-to-end latency of the recognition flow below or equal to 450 milliseconds."
- "The complete recognition processing flow must respond within 0.45 seconds."

Les exigences de référence restent exprimées dans leurs unités canoniques. Le Requirement Extractor devra produire une sortie normalisée dans ces unités, indépendamment de l'unité utilisée dans l'intention.

Chaque objet du tableau `requirements` doit être restitué sans altération.

| Champ source | Règle |
|---|---|
| `target_type` | Distinguer strictement `service` et `flow` |
| `target_id` | Identifier explicitement la cible (`C2`, `C3`, `C4`, `f1`, `f2`, selon le scénario) |
| `kpi_type` | Conserver `cpu`, `ram` ou `e2e_latency` ; ne pas inventer d'autres KPI |
| `comparator` | `gte` = **au moins / supérieur ou égal** ; `lte` = **au plus / inférieur ou égal / ne doit pas dépasser** ; `eq` = **exactement égal à** |
| `new_value` | Préserver **exactement** la valeur cible |
| `unit` | Respecter `vCPU`, `GB` ou `ms` ; ne pas changer l'unité sans conversion exacte, vérifiée et documentée |

**Interprétation :**

- `cpu` + `gte` : allouer **au moins** le nombre indiqué de vCPU au composant désigné.
- `ram` + `gte` : allouer **au moins** la quantité de RAM indiquée, en GB.
- `e2e_latency` + `lte` : la latence **de bout en bout** du flux désigné ne doit **pas dépasser** le seuil, en ms.
- Un scénario peut comporter **une à quatre exigences**, concernant plusieurs composants et/ou les deux flux. Produire **une seule requête cohérente par scénario**, qui inclut toutes les exigences.
- **Ne pas confondre** `baseline_value` (valeur antérieure) et `new_value` (nouvelle cible). Les verbes « augmenter » ou « réduire » ne sont permis que si les valeurs avant/après les justifient. Il n'est pas obligatoire de mentionner la valeur initiale.
- **Ne pas arrondir** les valeurs, même lorsque leur précision paraît peu naturelle (par exemple, `4.089336 vCPU`), sauf si une tolérance a été approuvée et documentée au préalable.
- Ne jamais ajouter d'action de placement (« déplacer C2 vers Edge »), d'identifiant de nœud, de disponibilité, de fiabilité ou d'autre contrainte QoS absente du scénario.

## 4. Formulation et diversité linguistique

L'objectif n'est pas simplement de transformer une exigence structurée en une phrase grammaticalement correcte. Le dataset doit permettre d'évaluer la capacité du LLM à interpréter différentes formulations d'une même exigence.

Il est donc demandé de privilégier une diversité linguistique significative, tout en conservant la précision sémantique de chaque scénario.

### 4.1. Diversité des formulations

Pour une même métrique, faire varier :

- **Le style de demande :** impératif, demande polie, expression d'un besoin, déclaration d'une contrainte ou formulation orientée objectif.
- **La structure grammaticale :** phrases courtes, phrases complexes, propositions conditionnelles ou coordonnées, demandes combinant plusieurs exigences.
- **Le vocabulaire métier :** utiliser différentes expressions désignant le même KPI, sans introduire d'ambiguïté.
- **L'ordre des informations :** commencer par le service, par la métrique, par la valeur cible ou par l'objectif recherché.
- **Les unités :** utiliser les représentations équivalentes autorisées dans la section 3.1.
- **La manière de désigner les services et les flux :** utiliser les noms fonctionnels, des descriptions de responsabilité ou des références contextuelles.

La diversité ne doit pas être purement lexicale : remplacer systématiquement « increase » par « raise » ne constitue pas une variation linguistique suffisante.

### 4.2. Désignation indirecte des services et des flux

1. **Son identifiant technique :** « C2 ».
2. **Son nom fonctionnel :** « Object Recognition ».
3. **Sa responsabilité :** « the component responsible for identifying objects in the video stream ».
4. **Une description contextuelle :** « the module that analyzes the captured scene ».
5. **Une référence au flux métier :** « the processing chain responsible for object recognition » ou « the augmented reality rendering pipeline ».

**Exemple :**

Exigence structurée :

      {
        "target_type": "service",
        "target_id": "C2",
        "component_id": 2,
        "component_name": "Object recognition",
        "kpi_type": "cpu",
        "comparator": "gte",
        "baseline_value": 3,
        "new_value": 4,
        "unit": "vCPU"
      }

Formulations possibles :

- "The object recognition component must have at least four virtual CPU cores."
- "Make sure the module responsible for recognizing objects in the video stream has a CPU allocation of no less than 4000 millicores."
- The component responsible for object recognition currently requires 3 vCPUs. Due to increased processing demands, I would like to increase its CPU allocation to at least 4 vCPUs.

Ces trois formulations doivent permettre au Requirement Extractor de retrouver la même cible : `C2`.

### 4.3. Contraintes de désambiguïsation

Une désignation indirecte n'est acceptable que si elle permet d'identifier sans ambiguïté le service ou le flux concerné à partir des informations du System Model.

Le générateur d'intentions doit pouvoir consulter les noms et les rôles fonctionnels des composants et des flux. Il ne doit jamais inventer de nouvelles responsabilités fonctionnelles.

En particulier :

- « le composant qui reconnaît les objets » peut désigner C2 ;
- « le module qui traite la scène » peut désigner C3, si cette responsabilité est définie dans la description de l'application ;
- « le moteur de rendu de réalité augmentée » peut désigner C4 ;
- « le flux de reconnaissance d'objets » peut désigner f1 ;
- « le flux de rendu AR » peut désigner f2.

En revanche, des expressions comme « le service principal », « le module le plus important » ou « le traitement vidéo » sont insuffisamment précises si plusieurs composants peuvent correspondre.

**Les intentions ne doivent pas obligatoirement contenir l'identifiant technique de la cible.** Le Requirement Extractor sera évalué sur sa capacité à retrouver cet identifiant à partir de la formulation et du contexte applicatif autorisé.

### 4.4. Répartition de la diversité dans le dataset

La génération devra produire un mélange de formulations :

- explicites, avec identifiants techniques ;
- fonctionnelles, avec noms des services ou des flux ;
- descriptives, avec références indirectes mais non ambiguës ;
- composites, combinant plusieurs exigences dans une seule demande.

Il est recommandé de suivre la proportion de chaque catégorie dans le rapport de génération et d'éviter qu'une formulation unique domine le dataset.

Les différentes catégories doivent être réparties sur les KPI et les types de scénarios, afin que certaines formulations ne deviennent pas des indices artificiels de la décision attendue.

La génération devra également éviter de reproduire systématiquement les mêmes structures de phrases, les mêmes introductions et les mêmes associations entre KPI et vocabulaire.

**Exemples illustratifs en français**  :

| Exigences structurées | Intention acceptable |
|---|---|
| `f1`, `e2e_latency`, `lte`, `421.265 ms` | « Veille à ce que la latence de bout en bout du flux f1 ne dépasse pas 421.265 ms. » |
| `C2`, `cpu`, `gte`, `4.089336 vCPU` | « Alloue au moins 4.089336 vCPU au composant Object Recognition (C2). » |
| `C4`, `ram`, `gte`, `7.109220038 GB` et `C2`, `ram`, `gte`, `4.729380463 GB` | « Prévois au moins 7.109220038 GB de RAM pour AR Rendering (C4) et 4.729380463 GB pour Object Recognition (C2). » |
| `C2`, `cpu`, `gte`, `4.089336 vCPU` et `f1`, `e2e_latency`, `lte`, `461.611 ms` | « Attribue au moins 4.089336 vCPU à C2, tout en maintenant la latence E2E de f1 inférieure ou égale à 461.611 ms. » |

Ces exemples sont en français pour expliquer les règles ; **le fichier principal d'évaluation reste en anglais**, sauf décision contraire explicite de l'équipe.

## 5. Format de sortie et livrables

**Livrable principal :** `intents.json`, un tableau JSON comprenant **exactement 150  entrées**, dans le même ordre que `scenarios.json`.

Exemple de structure (intention rédigée en anglais) :

```json
{
  "scenario_id": "ARVR-000001",
  "intent": "Keep the end-to-end latency of flow f1 at or below 421.265 ms.",
  "review_status": "validated",
  "variant_id": 1
}
```

Conserver **les identifiants originaux des scénarios**, sans renumérotation. Si plusieurs reformulations sont souhaitées pour un même scénario, créer un fichier distinct `intent_variants.json`, avec un `variant_id`. **Ne pas augmenter silencieusement** le jeu principal de 150 observations.

**Livrables complémentaires obligatoires :**

1. `intent_generation_report.md` : méthode suivie, modèle LLM et version si utilisés, prompts, paramètres de génération, modèles de phrases, règles de filtrage, revue humaine et limites.
2. `validation_report.json` : nombres et raisons des échecs de conformité (exigences absentes, comparateurs incorrects, valeurs/unités erronées, identifiants dupliqués, etc.) et corrections effectuées.
3. `generate_intents.py` (ou script/notebook équivalent), prompts et paramètres de reproductibilité, notamment la graine aléatoire si elle est disponible.

Les exigences structurées de référence restent dans `scenarios.json` : elles n'ont pas besoin d'être recopiées dans `intents.json`. **Ne jamais inclure les décisions de référence dans les données fournies au Requirement Extractor.**

## 6. Procédure recommandée

1. Charger les 150 scénarios ; vérifier les identifiants et la structure des tableaux `requirements`.
2. Construire pour chaque exigence une représentation sémantique déterministe : `(target_type, target_id, kpi_type, comparator, new_value, unit)`.
3. Produire **des intentions (différentes formulations si possibles)  en anglais par scénario**. Pour un scénario à plusieurs exigences, réunir d'abord toutes les contraintes, puis reformuler la demande complète.
4. Vérifier automatiquement, autant que possible, les identifiants, les valeurs numériques, les unités, les KPI et le sens des comparateurs.
5. **Relire le sens de chaque intention**, en particulier les scénarios composites, les valeurs très précises et les formulations potentiellement ambiguës. Une simple comparaison de chaînes de caractères n'est pas une validation sémantique suffisante.
6. Corriger ou régénérer les cas non conformes. **Ne pas supprimer les cas difficiles** pour améliorer artificiellement les résultats.
7. Enregistrer `intents.json`, les rapports et les versions du benchmark et du script.

**Si un LLM participe à la génération :** lui donner uniquement le tableau `requirements` nettoyé et les correspondances entre identifiants et noms de services/flux, **jamais le scénario complet**. Le prompt doit interdire l'invention d'exigences et imposer le respect des valeurs numériques et des comparateurs. Prévoir une validation indépendante (contrôles automatiques + relecture). L'auto-évaluation du LLM ne suffit pas.

## 8. Exploitation expérimentale et prévention des fuites d'information

Le jeu de données servira à deux évaluations distinctes.

**A — Requirement Extractor uniquement**

Entrée : `intent`. Sortie attendue : liste des tuples `(kpi_type, comparator, target_value, unit, target_type, target_id)`. Mesurer la correspondance sémantique exacte par scénario, puis les performances par champ.

**B — Pipeline complet**

Entrée : `intent` + **même System Model initial et même placement P0 pour chaque scénario indépendant**. Sortie : évaluation de la nécessité de reconfiguration, décision de placement, explication. Comparer aux résultats de référence et vérifier indépendamment les contraintes.

**À ne jamais donner au Requirement Extractor :** les exigences attendues, la catégorie/sévérité du scénario, la décision attendue, les placements de référence ou un accès indirect au fichier des réponses. Le script d'évaluation pourra utiliser `scenario_id` pour récupérer la vérité terrain **après** la prédiction.

Si un LLM sert à produire les intentions, documenter l'éventuel recouvrement entre le modèle de génération et le modèle évalué ; effectuer une validation sémantique indépendante et, si possible, prévoir un sous-ensemble d'intentions rédigées par des humains. Les scénarios étant synthétiques, **ne pas présenter les intentions comme représentatives de demandes réelles d'opérateurs sans preuve supplémentaire**.

