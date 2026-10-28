# PROMPT DE TRAVAIL — rédaction manuscrite d'intentions

Prompt que je suis moi-même pour chaque scénario. Il est référencé par [`SKILL.md`](SKILL.md) (procédure,
persistance, contrôles). Rien ici n'est un gabarit à remplir : ce sont des consignes de jugement.

## Rôle

Tu es une personne qui exploite ou fait évoluer une application de réalité augmentée déjà déployée
(« Interactive Augmented Reality Application »). Tu écris, en anglais, **une seule intention** qui exprime
l'évolution des exigences de l'application. Tu n'es pas un formulaire : tu écris comme quelqu'un écrit vraiment
(ticket, message à un collègue, note d'exploitation, demande à une équipe, remarque pendant une revue), avec des
tournures, un niveau de précision et une longueur qui changent d'un cas à l'autre.

## Ce que tu reçois

Pour un scénario : son `id` et ses exigences. Pour chaque exigence : cible (composant ou flux), KPI
(`cpu`, `ram`, `e2e_latency`), comparateur (`gte` pour CPU/RAM, `lte` pour la latence), valeur de base, nouvelle
valeur, unité canonique (`vCPU`, `GB`, `ms`). Et le contexte applicatif ci-dessous. Rien d'autre.

### Composants

| Id | Nom | Rôle (description officielle) |
|---|---|---|
| `C1` | Vision Capture | Captures visual inputs from the user device |
| `C2` | Object Recognition | Detects and identifies objects in captured frames |
| `C3` | Scene Processing | Processes visual and scene-context information |
| `C4` | AR Rendering | Produces augmented-reality rendering elements |
| `C5` | Display Output | Displays processed results to the receiving device |

### Flux (ordre d'exécution)

| Id | Nom | Chemin | Description officielle |
|---|---|---|---|
| `f1` | Object Recognition Flow | C1 → C2 → C3 → C5 | Object recognition and scene-processing results delivered to the display |
| `f2` | AR Rendering Flow | C1 → C3 → C4 → C5 | Scene processing and AR rendering delivered to the display |

`C1`, `C3` et `C5` appartiennent aux deux flux. Une désignation de flux doit donc s'appuyer sur ce qui les
distingue : la **reconnaissance d'objets** (`f1`, passe par `C2`) ou le **rendu AR** (`f2`, passe par `C4`).

## Ce que tu produis

1. L'intention : une chaîne de texte en anglais (voir longueur et style ci-dessous).
2. Son plan et ses métadonnées (`plan`, `mentions`, éventuellement `baseline_mentions`) au format de
   [SKILL.md §1](SKILL.md), décrivant fidèlement ce que tu as écrit. Les métadonnées sont écrites **après** le
   texte, à partir du texte réel, jamais l'inverse.

## Règles de fond

1. **Toutes les exigences du scénario, et seulement celles-ci.** Aucune exigence ajoutée, aucune omise,
   aucun autre KPI (pas de bande passante, de fiabilité, de stockage, d'énergie…).
2. **Valeur exacte.** Chaque valeur cible est reprise telle quelle, à toutes ses décimales, ou convertie
   exactement : 1 vCPU = 1000 mCPU/millicores ; 1 GB = 1000 MB, 1 TB = 1000 GB ; 1 s = 1000 ms, 1 ms = 1000 µs.
   Jamais « about », « roughly », « around », « ~ », jamais d'arrondi, pas de séparateur de milliers (écrire
   `4500`, pas `4,500`). Pas d'unités binaires (GiB/MiB) : la conversion exacte n'est pas décimale finie.
   Pas de MIPS pour un CPU.
3. **Comparateur déductible.** CPU et RAM : un minimum. Latence de bout en bout : un maximum. Le dire en
   clair ou par la tournure, mais ne jamais l'inverser ni le laisser indécidable.
4. **Cible unique.** Un lecteur qui connaît seulement les noms et descriptions ci-dessus doit retrouver
   sans hésiter *quel composant* ou *quel flux*. Composant ≠ flux : « latency of C2 » est faux, la latence vise
   un flux ; CPU/RAM visent un composant.
5. **Application déjà déployée.** L'intention exprime une évolution de besoin, pas un déploiement initial.
6. **Direction.** « increase / raise / bump / boost » seulement pour une hausse (CPU/RAM sont toujours des hausses).
   Pour la latence, regarde base → nouvelle valeur : « tighten / reduce / lower / shorten » seulement si la
   valeur diminue, « relax / loosen / extend / allow longer » seulement si elle augmente. Dans le doute, ne pas
   mettre de verbe de direction.
7. **Interdits absolus.** Action de placement ou de mouvement (move, migrate, offload, relocate, place, host),
   identifiant de nœud (`N4`…), couche (edge, cloud, fog, IoT), « node », disponibilité, fiabilité, faisabilité
   (« feasible », « impossible »), allusion à ce que le système devrait décider.
8. **Pas de fuite de décision.** L'urgence, le ton et la rigueur ne dépendent pas de la difficulté du scénario.
9. **Pas de nombre en trop.** Les seuls nombres du texte sont les valeurs cibles (et, au besoin, des valeurs de
   base déclarées dans `baseline_mentions`) — hors identifiants `C1`… `f2`. Pas de dates, de durées d'échéance
   chiffrées, de pourcentages, de comptages (« two teams »), de numéros de version.

## Niveaux d'explicitation (un par exigence ; plusieurs niveaux peuvent coexister dans un scénario)

- **1 — explicite** : id (avec ou sans nom), KPI et unité canoniques, comparateur en clair.
- **2 — fonctionnel** : nom du composant ou du flux, KPI nommé, unité variée.
- **3 — implicite** : cible par responsabilité ou par flux métier, sans nom ni id ; KPI reformulé ; comparateur
  porté par la tournure ; contexte possible (une évolution, une contrainte, un incident).
- **4 — oblique** : cible reconnue par raisonnement sur les descriptions (ce qu'elle fait dans la chaîne, ce
  qui l'entoure) ; KPI nommé indirectement ; registre familier ou télégraphique ; contexte omis. Le texte peut
  sembler incomplet à quelqu'un qui n'a pas le System Model, mais la cible reste unique et la valeur exacte.

Le flou ne touche jamais la valeur, ni l'unicité de la cible.

## Mode de désignation à déclarer (`designation`)

`id`, `id+name`, `name`, `role` (responsabilité), `flow` (référence à la chaîne métier), `context`
(déduction par contexte/conséquence). Niveau 1 ⇒ contient `id`. Niveaux 3 et 4 ⇒ ne contient pas `id`. Si la
désignation ne contient pas `id`, l'identifiant ne doit pas apparaître dans le texte.

## Style, registre, structure (valeurs conseillées pour `plan`)

- `style` : `imperative`, `polite_request`, `need_statement`, `constraint_statement`, `goal_oriented`,
  `narrative`, `ticket_note`, `question`.
- `register` : `ops_terse`, `developer`, `manager`, `formal`, `casual`, `product_owner`.
- `structure` : `single_sentence`, `two_sentences`, `conditional`, `enumeration`, `clause_chain`.

Choisis-les pour le scénario, en regardant le rapport de diversité (`report`) avant de t'engager : prends ce
qui est sous-représenté. Ne les déduis pas de la taille du scénario ni du KPI. Ordre des mentions : change-le
d'un scénario à l'autre (une exigence de flux avant les composants, la valeur avant la cible, l'objectif
d'abord, etc.).

## Longueur

Libre mais variée : de quelques mots (~8) à ~70 mots ; plus long de façon exceptionnelle (~90). Un scénario à une
exigence n'est pas toujours court, un scénario à quatre exigences n'est pas toujours long. Aucun texte de plusieurs
paragraphes.

## Relecture avant enregistrement (liste de contrôle)

- [ ] Chaque exigence du scénario est présente une fois, avec la bonne cible.
- [ ] Chaque valeur est exacte (copie ou conversion décimale exacte), sans mot d'approximation.
- [ ] Chaque unité correspond au KPI (CPU → vCPU/virtual CPUs/cores virtuels/mCPU/millicores ; RAM → GB/MB/TB ;
      latence → ms/seconds/µs).
- [ ] Comparateurs déductibles et dans le bon sens.
- [ ] Aucune cible ambiguë entre `f1`/`f2` ou entre composants.
- [ ] Aucun mot interdit, aucun nombre en trop, aucun KPI ajouté.
- [ ] Verbes de direction cohérents avec base → nouvelle valeur.
- [ ] Ouverture et structure différentes des intentions voisines ; style/registre/longueur choisis volontairement.
- [ ] Les `mentions` décrivent exactement ce que le texte dit (`written_form` = sous-chaîne copiée du texte).

## Format du fichier de lot (écrit à la main)

Tableau JSON d'entrées dans l'ordre des scénarios :

```json
[
  {
    "scenario_id": "ARVR-0000XX",
    "intent": "…",
    "plan": {"style": "need_statement", "register": "developer", "structure": "two_sentences"},
    "mentions": [
      {"target_id": "C2", "kpi_type": "cpu", "comparator": "gte",
       "written_value": "4500", "written_unit": "millicores", "written_form": "4500 millicores",
       "designation": "role", "level": 3}
    ],
    "baseline_mentions": []
  }
]
```

- `written_value` : nombre écrit dans le texte, sous forme de chaîne (`"4500"`). Si le nombre est écrit en mots
  (« five and a quarter »), mettre dans `written_value` la valeur numérique décimale (`"5.25"`) et ajouter
  `"number_in_words": true` ; `written_form` reste la sous-chaîne exacte du texte.
- `written_unit` : l'unité telle qu'écrite (`ms`, `seconds`, `virtual CPUs`, `millicores`, `GB`, `MB`…).
- `written_form` : sous-chaîne exacte du texte contenant le nombre *et* l'unité.
- `baseline_mentions` : mêmes champs, sans `comparator`/`designation`/`level`, uniquement pour une valeur de
  base citée dans le texte ; elle sera vérifiée contre `baseline_value`.
- Commande : `python3 intent_store.py append <lot.json>` ; les erreurs et avertissements s'affichent ; en cas de
  refus, corriger le texte (et non les métadonnées) puis recommencer.
