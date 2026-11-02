#!/usr/bin/env python3
"""Stockage et contrôle des intentions ARVR-150. Ne génère AUCUN texte.

Commandes :
  status                 entrées déjà enregistrées et prochain scénario à traiter
  revise LOT.json RAISON corrige une entrée déjà enregistrée (revalidée, ancien texte conservé)
  carry                  (jeu 500) reporte les intentions du jeu 150 vers leurs nouveaux ids, après revalidation
  view [next|ID] [N]     affiche N scénarios (exigences seulement, vérité terrain masquée)
  append LOT.json        contrôle puis enregistre, scénario par scénario, dans intents.json
  report                 répartition des niveaux/styles/longueurs/ouvertures déjà enregistrés

Les textes sont écrits à la main (voir SKILL.md) ; ce script les vérifie et les enregistre.
"""

import json
import os
import re
import sys
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
# Jeu de scénarios : INTENT_SET=150 (défaut) ou 500. Chaque jeu a son propre fichier de sortie.
SET = os.environ.get("INTENT_SET", "150")
SCENARIOS = ROOT.parent / "eval" / f"experiment_{SET}" / "scenarios.json"
OUT = ROOT / ("intents.json" if SET == "150" else f"intents_{SET}.json")

REVIEW_STATUS = "llm_generated_auto_checked"

UNITS = {
    "cpu": {
        "vcpu": "1", "vcpus": "1", "virtual cpu": "1", "virtual cpus": "1",
        "virtual core": "1", "virtual cores": "1",
        "mcpu": "0.001", "millicore": "0.001", "millicores": "0.001",
    },
    "ram": {
        "gb": "1", "gigabyte": "1", "gigabytes": "1",
        "mb": "0.001", "megabyte": "0.001", "megabytes": "0.001",
        "tb": "1000", "terabyte": "1000", "terabytes": "1000",
    },
    "e2e_latency": {
        "ms": "1", "millisecond": "1", "milliseconds": "1",
        "s": "1000", "sec": "1000", "second": "1000", "seconds": "1000",
        "µs": "0.001", "us": "0.001", "microsecond": "0.001", "microseconds": "0.001",
    },
}

DESIGNATIONS = {"id", "id+name", "name", "role", "flow", "context"}
STYLES = {"imperative", "polite_request", "need_statement", "constraint_statement",
          "goal_oriented", "narrative", "ticket_note", "question"}
REGISTERS = {"ops_terse", "developer", "manager", "formal", "casual", "product_owner"}
STRUCTURES = {"single_sentence", "two_sentences", "conditional", "enumeration", "clause_chain"}

FORBIDDEN = [
    (r"\bN\d{1,2}\b", "identifiant de noeud"),
    (r"\b(offload\w*|migrat\w*|relocat\w*|placement\w*|reposition\w*)", "mot de placement"),
    (r"\b(mov(e|es|ed|ing)|place[sd]?|placing|host(s|ed|ing)?)\b", "mot de placement/hébergement"),
    (r"\bnodes?\b", "mot 'node'"),
    (r"\b(edge|cloud|fog|iot)\b", "couche du continuum"),
    (r"\b(availab\w*|reliab\w*|uptime)\b", "disponibilité/fiabilité"),
    (r"\b(feasib\w*|infeasib\w*|impossible)\b", "mot de faisabilité"),
    (r"\b(about|roughly|approximately|around|approx\.?)\b", "mot d'approximation"),
    (r"~", "tilde d'approximation"),
    (r"\d,\d{3}", "séparateur de milliers"),
    (r"\bmips\b", "MIPS"),
]

UP_WORDS = r"\b(increas\w*|rais(e|es|ed|ing)|bump\w*|boost\w*)\b"
DOWN_WORDS = r"\b(tighten\w*|reduc\w*|lower\w*|shorten\w*|stricter|squeez\w*|trim\w*)\b"
RELAX_WORDS = r"\b(relax\w*|loosen\w*|extend\w*|more lenient)\b"

ID_ANY = r"(?<![A-Za-z0-9])(?:[Cc][1-5]|[Ff][12])(?![A-Za-z0-9])"
NUMBER = r"\d+(?:\.\d+)?"


# ---------------------------------------------------------------- données
def load_scenarios():
    with open(SCENARIOS, encoding="utf-8") as f:
        return json.load(f)


def load_out():
    if not OUT.exists():
        return []
    with open(OUT, encoding="utf-8") as f:
        return json.load(f)


def save_out(entries):
    order = {s["id"]: i for i, s in enumerate(load_scenarios())}
    entries = sorted(entries, key=lambda e: order[e["scenario_id"]])
    fd, tmp = tempfile.mkstemp(prefix="intents.", suffix=".tmp", dir=str(ROOT))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, OUT)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fmt(x):
    return format(Decimal(repr(x)).normalize(), "f")


# ---------------------------------------------------------------- vue masquée
def show(s):
    print(f"## {s['id']}")
    for r in s["requirements"]:
        if r["target_type"] == "service":
            who = f"service {r['target_id']} ({r['component_name']})"
        else:
            who = f"flow {r['target_id']} ({r['flow_name']})"
        print(f"  - {who}: {r['kpi_type']} {r['comparator']} {fmt(r['new_value'])} {r['unit']}"
              f"   [valeur de base {fmt(r['baseline_value'])}]")


def pending(scenarios, out):
    """Scénarios sans intention, dans l'ordre du fichier de scénarios."""
    done = {e["scenario_id"] for e in out}
    return [s for s in scenarios if s["id"] not in done]


def cmd_view(args):
    scenarios = load_scenarios()
    todo = pending(scenarios, load_out())
    count = 5
    if args and args[0] != "next":
        ids = [s["id"] for s in scenarios]
        if args[0] not in ids:
            sys.exit(f"id inconnu : {args[0]}")
        todo = scenarios[ids.index(args[0]):]
    if len(args) > 1:
        count = int(args[1])
    for s in todo[:count]:
        show(s)


def cmd_status(_):
    scenarios = load_scenarios()
    out = load_out()
    todo = pending(scenarios, out)
    print(f"enregistrés : {len(out)}/{len(scenarios)}")
    if todo:
        print(f"prochain    : {todo[0]['id']}   (restants : {len(todo)})")
    else:
        print("terminé.")


# ---------------------------------------------------------------- contrôle
def id_present(text, ident):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(ident) + r"(?![A-Za-z0-9])", text, re.I) is not None


def check_value(kpi, unit, written_value, expected, label, errors):
    factor = UNITS.get(kpi, {}).get(unit.lower())
    if factor is None:
        errors.append(f"{label}: unité '{unit}' non admise pour {kpi}")
        return
    try:
        got = Decimal(written_value) * Decimal(factor)
    except InvalidOperation:
        errors.append(f"{label}: written_value '{written_value}' n'est pas un nombre")
        return
    if got.normalize() != Decimal(repr(expected)).normalize():
        errors.append(f"{label}: {written_value} {unit} = {fmt(float(got))} canonique, attendu {fmt(expected)}")


def check_form(m, text, label, errors):
    form = m.get("written_form", "")
    if not form or form.lower() not in text.lower():
        errors.append(f"{label}: written_form '{form}' absent du texte")
        return
    if m.get("written_unit", "").lower() not in form.lower():
        errors.append(f"{label}: l'unité '{m.get('written_unit')}' n'est pas dans written_form")
    if not m.get("number_in_words") and str(m.get("written_value")) not in re.findall(NUMBER, form):
        errors.append(f"{label}: nombre '{m.get('written_value')}' absent de written_form (number_in_words ?)")


def validate(entry, scen, existing):
    errors, warnings = [], []
    text = entry.get("intent", "")
    if not isinstance(text, str) or not text.strip():
        return ["intent vide"], warnings
    if "\n" in text:
        errors.append("intent sur plusieurs lignes")

    reqs = {(r["target_id"], r["kpi_type"]): r for r in scen["requirements"]}
    mentions = entry.get("mentions", [])
    seen = Counter((m.get("target_id"), m.get("kpi_type")) for m in mentions)
    for key in reqs:
        if seen[key] == 0:
            errors.append(f"exigence {key} absente de mentions")
    for key, c in seen.items():
        if key not in reqs:
            errors.append(f"mention {key} absente du scénario (exigence ajoutée)")
        elif c > 1:
            errors.append(f"mention {key} déclarée {c} fois")

    forms = []
    for m in mentions:
        key = (m.get("target_id"), m.get("kpi_type"))
        r = reqs.get(key)
        if r is None:
            continue
        label = f"{key[0]}/{key[1]}"
        if m.get("comparator") != r["comparator"]:
            errors.append(f"{label}: comparateur {m.get('comparator')} != {r['comparator']}")
        check_value(key[1], m.get("written_unit", ""), m.get("written_value", ""), r["new_value"], label, errors)
        check_form(m, text, label, errors)
        forms.append(m.get("written_form", ""))
        d, lvl = m.get("designation"), m.get("level")
        if d not in DESIGNATIONS:
            errors.append(f"{label}: designation '{d}' inconnue")
            continue
        if lvl not in (1, 2, 3, 4):
            errors.append(f"{label}: level doit être 1..4")
        if lvl == 1 and "id" not in d:
            errors.append(f"{label}: niveau 1 exige une désignation avec id")
        if lvl in (3, 4) and "id" in d:
            errors.append(f"{label}: niveau {lvl} incompatible avec l'id")
        has_id = id_present(text, key[0])
        if "id" in d and not has_id:
            errors.append(f"{label}: désignation '{d}' mais {key[0]} absent du texte")
        if "id" not in d and has_id:
            errors.append(f"{label}: {key[0]} présent dans le texte alors que designation='{d}'")
        if r["target_type"] == "service" and key[1] == "e2e_latency":
            errors.append(f"{label}: latence sur un composant")

    for b in entry.get("baseline_mentions", []):
        key = (b.get("target_id"), b.get("kpi_type"))
        r = reqs.get(key)
        label = f"base {key[0]}/{key[1]}"
        if r is None:
            errors.append(f"{label}: absente du scénario")
            continue
        check_value(key[1], b.get("written_unit", ""), b.get("written_value", ""), r["baseline_value"], label, errors)
        check_form(b, text, label, errors)
        forms.append(b.get("written_form", ""))

    allowed = set()
    for f in forms:
        allowed.update(re.findall(NUMBER, f))
    stripped = re.sub(ID_ANY, " ", text)
    for tok in re.findall(NUMBER, stripped):
        if tok not in allowed:
            errors.append(f"nombre non déclaré dans le texte : {tok}")

    for pat, what in FORBIDDEN:
        mt = re.search(pat, text, re.I)
        if mt:
            errors.append(f"terme interdit ({what}) : '{mt.group(0)}'")

    lat_down = any(r["kpi_type"] == "e2e_latency" and r["new_value"] < r["baseline_value"] for r in scen["requirements"])
    lat_up = any(r["kpi_type"] == "e2e_latency" and r["new_value"] > r["baseline_value"] for r in scen["requirements"])
    if re.search(DOWN_WORDS, text, re.I) and not lat_down:
        errors.append("verbe de réduction sans latence resserrée dans ce scénario")
    if re.search(RELAX_WORDS, text, re.I) and not lat_up:
        errors.append("verbe de relâchement sans latence relâchée dans ce scénario")
    if re.search(UP_WORDS, text, re.I) and not any(k in ("cpu", "ram") for _, k in reqs):
        errors.append("verbe d'augmentation sans exigence CPU/RAM dans ce scénario")

    plan = entry.get("plan", {})
    for field, vocab in (("style", STYLES), ("register", REGISTERS), ("structure", STRUCTURES)):
        if plan.get(field) not in vocab:
            warnings.append(f"plan.{field}='{plan.get(field)}' hors vocabulaire conseillé")

    n_words = len(text.split())
    if n_words < 5 or n_words > 110:
        warnings.append(f"longueur inhabituelle : {n_words} mots")
    if any(e["intent"].strip().lower() == text.strip().lower() for e in existing):
        errors.append("intent identique à une entrée existante")
    opening = " ".join(text.lower().split()[:3])
    if sum(1 for e in existing if " ".join(e["intent"].lower().split()[:3]) == opening) >= 3:
        warnings.append(f"ouverture '{opening}' déjà utilisée 3 fois ou plus")
    recent = [" ".join(e["intent"].lower().split()[:2]) for e in existing[-4:]]
    if " ".join(text.lower().split()[:2]) in recent:
        warnings.append("même début que l'une des 4 intentions précédentes")
    return errors, warnings


def cmd_append(args):
    if not args:
        sys.exit("usage: append LOT.json")
    with open(args[0], encoding="utf-8") as f:
        batch = json.load(f)
    scenarios = load_scenarios()
    out = load_out()
    saved = 0
    done_ids = {e["scenario_id"] for e in out}
    for entry in batch:
        if entry.get("scenario_id") in done_ids:
            continue  # déjà enregistré lors d'une exécution précédente : on ne réécrit jamais
        todo = pending(scenarios, out)
        if not todo:
            print("tous les scénarios sont déjà enregistrés.")
            break
        scen = todo[0]
        if entry.get("scenario_id") != scen["id"]:
            print(f"STOP : attendu {scen['id']}, reçu {entry.get('scenario_id')}")
            break
        errors, warnings = validate(entry, scen, out)
        for w in warnings:
            print(f"  avertissement {scen['id']}: {w}")
        if errors:
            for e in errors:
                print(f"  ERREUR {scen['id']}: {e}")
            print(f"STOP : {scen['id']} refusé (enregistrés avant : {saved}).")
            break
        stored = {
            "scenario_id": scen["id"],
            "intent": entry["intent"].strip(),
            "review_status": REVIEW_STATUS,
            "variant_id": 1,
            "plan": entry["plan"],
            "mentions": entry["mentions"],
            "baseline_mentions": entry.get("baseline_mentions", []),
            "n_words": len(entry["intent"].split()),
        }
        out.append(stored)
        save_out(out)
        done_ids.add(scen["id"])
        saved += 1
        print(f"ok {scen['id']} ({stored['n_words']} mots)")
    print(f"total enregistré : {len(out)}/{len(scenarios)}")


def cmd_carry(_):
    """Jeu 500 : reprend les intentions déjà écrites et contrôlées du jeu 150, sous leur nouvel id.

    Correspondance par égalité exacte des exigences ; le texte n'est pas modifié ; chaque entrée est
    revalidée contre le scénario du jeu 500.
    """
    if SET == "150":
        sys.exit("carry s'utilise avec INTENT_SET=500")
    old_scen = json.load(open(ROOT.parent / "eval" / "experiment_150" / "scenarios.json", encoding="utf-8"))
    old_int = {e["scenario_id"]: e for e in json.load(open(ROOT / "intents.json", encoding="utf-8"))}
    new_scen = load_scenarios()
    key = lambda s: json.dumps(s["requirements"], sort_keys=True)
    by_req = {}
    for s in new_scen:
        by_req.setdefault(key(s), []).append(s)
    out = load_out()
    done_ids = {e["scenario_id"] for e in out}
    carried = 0
    for o in old_scen:
        matches = by_req.get(key(o), [])
        if len(matches) != 1:
            sys.exit(f"{o['id']}: {len(matches)} correspondances dans le jeu 500, abandon")
        scen = matches[0]
        if scen["id"] in done_ids:
            continue
        e = old_int[o["id"]]
        errors, _w = validate(e, scen, out)
        if errors:
            sys.exit(f"{o['id']} -> {scen['id']} : revalidation refusée : {errors}")
        stored = dict(e)
        stored["scenario_id"] = scen["id"]
        stored["carried_over_from"] = {"set": "experiment_150", "scenario_id": o["id"]}
        out.append(stored)
        done_ids.add(scen["id"])
        carried += 1
    save_out(out)
    print(f"reportées : {carried} ; total {len(out)}/{len(new_scen)}")


def cmd_revise(args):
    """Corrige à la main une entrée déjà enregistrée : revalidation complète, ancien texte conservé."""
    if len(args) < 2:
        sys.exit("usage: revise LOT.json 'raison'")
    with open(args[0], encoding="utf-8") as f:
        batch = json.load(f)
    scenarios = {s["id"]: s for s in load_scenarios()}
    out = load_out()
    index = {e["scenario_id"]: i for i, e in enumerate(out)}
    for entry in batch:
        sid = entry.get("scenario_id")
        if sid not in index:
            sys.exit(f"{sid}: pas encore enregistré, utiliser append")
        old = out[index[sid]]
        others = [e for e in out if e["scenario_id"] != sid]
        errors, warnings = validate(entry, scenarios[sid], others)
        for w in warnings:
            print(f"  avertissement {sid}: {w}")
        if errors:
            for e in errors:
                print(f"  ERREUR {sid}: {e}")
            sys.exit(f"STOP : révision de {sid} refusée, entrée inchangée.")
        new = dict(old)
        new.update({
            "intent": entry["intent"].strip(),
            "plan": entry["plan"],
            "mentions": entry["mentions"],
            "baseline_mentions": entry.get("baseline_mentions", []),
            "n_words": len(entry["intent"].split()),
            "revision": {"previous_intent": old["intent"], "reason": args[1]},
        })
        out[index[sid]] = new
        save_out(out)
        print(f"révisé {sid} ({new['n_words']} mots)")


def cmd_report(_):
    out = load_out()
    if not out:
        print("rien d'enregistré.")
        return
    mentions = [m for e in out for m in e["mentions"]]
    print(f"entrées : {len(out)}   mentions : {len(mentions)}")
    for title, counter in (
        ("niveaux", Counter(m["level"] for m in mentions)),
        ("désignations", Counter(m["designation"] for m in mentions)),
        ("styles", Counter(e["plan"].get("style") for e in out)),
        ("registres", Counter(e["plan"].get("register") for e in out)),
        ("structures", Counter(e["plan"].get("structure") for e in out)),
        ("unités écrites", Counter(m["written_unit"].lower() for m in mentions)),
    ):
        print(f"{title:15s}", dict(sorted(counter.items(), key=lambda kv: str(kv[0]))))
    cross = Counter((m["kpi_type"], m["level"]) for m in mentions)
    print("kpi x niveau   ", dict(sorted(cross.items())))
    words = [e["n_words"] for e in out]
    print(f"mots : min {min(words)}  médiane {median(words)}  max {max(words)}")
    openings = Counter(" ".join(e["intent"].lower().split()[:2]) for e in out)
    print("ouvertures (2 mots) les plus fréquentes :", openings.most_common(6))


def main():
    cmds = {"status": cmd_status, "view": cmd_view, "append": cmd_append, "report": cmd_report, "carry": cmd_carry, "revise": cmd_revise}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
