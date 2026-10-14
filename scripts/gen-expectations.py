#!/usr/bin/env python3
"""Generate expected-sw5e.json for test-sw5e-completeness.mjs.

Walks the SW5e Foundry source YAMLs at packs/_source/ and emits the expected
name lists — one entry per source entity, mirroring the file-selection rules
of build_sw5e_pack.py (skip _folder.yml, type filters, class-file layout).
These lists are GENERATED, never hand-edited: if the test fails, fix the
normalizer or this walk, not the JSON.

Usage: python3 scripts/gen-expectations.py   (writes expected-sw5e.json in cwd)
"""

import glob
import json
import os
import sys

import yaml

SRC_ROOT = os.path.expanduser("~/projects/sw5e-module/packs/_source")

# Same pack set as build_sw5e_pack.MONSTER_PACKS (drakes-shipyard and
# hgttgspecies carry no type: npc statblocks; excluded there too).
MONSTER_PACKS = {
    "monsters": "sw5e",
    "snv-monsters": "sw5e-snv",
    "fistoscodex": "sw5e-fistoscodex",
    "mandaloriancodexnpcs": "sw5e-mandaloriancodexnpcs",
    "veshs-galactic-holodex": "sw5e-veshs-galactic-holodex",
}
N_MONSTER_SPOT_CHECKS = 30


def _load(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def _name(d, slug):
    return d.get("name") or slug.replace("-", " ").title()


def expected_species():
    out = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "species", "*.yml"))):
        d = _load(f)
        out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def expected_conditions():
    out = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "conditions", "*.yml"))):
        d = _load(f)
        out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def expected_feats():
    out = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "feats", "**", "*.yml"),
                              recursive=True)):
        d = _load(f)
        if (d.get("type") or "") != "feat":
            continue
        out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def expected_backgrounds():
    out = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "backgrounds", "*.yml"))):
        d = _load(f)
        if (d.get("type") or "") not in ("background", "", None):
            continue
        out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def expected_spells():
    out = []
    base = os.path.join(SRC_ROOT, "powers-maneuvers")
    for family in ("force-powers", "tech-powers"):
        fdir = os.path.join(base, family)
        for folder in sorted(os.listdir(fdir)):
            dirpath = os.path.join(fdir, folder)
            if folder.startswith("_") or not os.path.isdir(dirpath):
                continue
            for f in sorted(glob.glob(os.path.join(dirpath, "*.yml"))):
                d = _load(f)
                if (d.get("type") or "") != "spell":
                    continue
                out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def expected_classes():
    out = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "character-classes",
                                           "*", "*.yml"))):
        slug = os.path.basename(f)[:-4]
        if os.path.basename(os.path.dirname(f)) != slug:
            continue
        out.append(_name(_load(f), slug))
    return out


def expected_archetypes():
    out = []
    for cls in sorted(os.listdir(os.path.join(SRC_ROOT, "character-classes"))):
        adir = os.path.join(SRC_ROOT, "character-classes", cls, "archetypes")
        if not os.path.isdir(adir):
            continue
        for f in sorted(glob.glob(os.path.join(adir, "*.yml"))):
            d = _load(f)
            if (d.get("type") or "") != "subclass":
                continue
            out.append(_name(d, os.path.basename(f)[:-4]))
    return out


def _cr_value(raw):
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw or "").strip()
    if s == "1/8":
        return 0.125
    if s == "1/4":
        return 0.25
    if s == "1/2":
        return 0.5
    try:
        return float(s)
    except ValueError:
        return 0.0


def expected_monsters(n_spot=N_MONSTER_SPOT_CHECKS):
    """Per-pack spot-checks: sample names spread across CR brackets.

    Not the full 1,082 (the count itself is asserted separately by the test);
    deterministic: entities sorted per bracket, evenly indexed picks.
    """
    entities = []  # (cr, name)
    n_total = 0
    for pack in MONSTER_PACKS:
        for f in sorted(glob.glob(os.path.join(SRC_ROOT, pack, "**", "*.yml"),
                                  recursive=True)):
            if os.path.basename(f).startswith("_"):
                continue
            d = _load(f)
            if d.get("type") != "npc":
                continue
            n_total += 1
            cr = _cr_value(((d.get("system") or {}).get("details") or {})
                           .get("cr"))
            entities.append((cr, _name(d, os.path.basename(f)[:-4])))
    # CR brackets: 0..0.5, then integer bands.
    def bracket(cr):
        return 0 if cr <= 0.5 else min(int(cr), 30)
    brackets = {}
    for cr, name in entities:
        brackets.setdefault(bracket(cr), []).append((cr, name))
    picks = []
    order = sorted(brackets)
    i = 0
    while len(picks) < n_spot and i < n_spot * len(order) * 2:
        b = order[i % len(order)]
        group = sorted(brackets[b])
        idx = (len(picks) // len(order)) % len(group)
        cand = group[idx][1]
        if cand not in picks:
            picks.append(cand)
        i += 1
    # top up from the full sorted list if tiny brackets left us short
    if len(picks) < n_spot:
        for _cr, name in sorted(entities):
            if len(picks) >= n_spot:
                break
            if name not in picks:
                picks.append(name)
    return picks, n_total


def main():
    species = expected_species()
    conditions = expected_conditions()
    feats = expected_feats()
    backgrounds = expected_backgrounds()
    spells = expected_spells()
    classes = expected_classes()
    archetypes = expected_archetypes()
    monsters, n_monsters = expected_monsters()
    out = {
        "species": species,
        "conditions": conditions,
        "feats": feats,
        "backgrounds": backgrounds,
        "spells": spells,
        "classes": classes,
        "archetypes": archetypes,
        "monsters_spot_checks": monsters,
        "monsters_total": n_monsters,
    }
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "expected-sw5e.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    print(f"species {len(species)} | conditions {len(conditions)} | "
          f"feats {len(feats)} | backgrounds {len(backgrounds)} | "
          f"spells {len(spells)} | classes {len(classes)} | "
          f"archetypes {len(archetypes)} | monsters {n_monsters} total, "
          f"{len(monsters)} spot checks -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
