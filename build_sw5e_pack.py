#!/usr/bin/env python3
"""Build the SW5e content pack: all open5e-schema tables into sw5e.sqlite.

Entry point for the table builders; the races pass reuses sw5e_lib.load_race.
Tables not yet implemented are created empty by the shared schema.
"""

import glob
import json
import os
import re
import sys

import yaml

from sw5e_lib import (DOCS, DOC_DEFAULT, SRC_ROOT, documents_rows_from,
                      html_to_md, load_race, sw5e_doc, write_pack)

OUT = os.path.expanduser("~/projects/sw5e-odm-pack/sw5e.sqlite")


def _load(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def doc_meta(src=None):
    """(slug, title, license, author, url) for a Foundry system.source dict."""
    return sw5e_doc(src)


def build_races():
    files = sorted(glob.glob(os.path.join(SRC_ROOT, "species", "*.yml")))
    races = [load_race(f) for f in files]
    return races, [
        (r["slug"], r["name"], r["document_slug"], r["is_subrace"],
         r["parent_slug"], r["data_json"]) for r in races]


def build_conditions():
    """conditions(slug, name, document_slug, data_json)
    data_json: {name, slug, desc, document__*}
    SW5e PHB conditions; the source YAMLs are journal-pages shaped
    (description lives in pages[].text.content, no top-level `system`)."""
    rows = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "conditions", "*.yml"))):
        d = _load(f)
        slug = os.path.basename(f)[:-4]
        name = d.get("name") or slug.replace("-", " ").title()
        pages = d.get("pages") or []
        desc = ""
        for p in pages:
            txt = (p.get("text") or {}).get("content") or ""
            if txt.strip():
                desc = html_to_md(txt)
                break
        data = {
            "name": name, "slug": slug, "desc": desc,
            "document__slug": "sw5e-phb",
            "document__title": DOCS["PHB"][1],
            "document__license_url": "https://sw5e.com/attributing",
            "document__url": DOCS["PHB"][4],
        }
        rows.append((slug, name, "sw5e-phb", data))
    return rows


def build_feats():
    """feats(slug, name, document_slug, aliases_csv, data_json)
    data_json: {slug, name, desc, prerequisite, effects_desc, document__*}
    Walks feats/**/*.yml; skips _folder.yml (type: Item) and any non-feat.
    Prerequisite: system.prerequisites.level (always null in this source) or ''
    — formatted 'Level N+' when an int is ever present (open5e display shape).
    effects_desc: top-level Foundry effects[].changes flattened to 'key: value'
    lines; '' when a feat has none."""
    rows = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "feats", "**", "*.yml"),
                              recursive=True)):
        d = _load(f)
        if (d.get("type") or "") != "feat":
            continue
        sys_ = d.get("system") or {}
        rel = os.path.relpath(f, os.path.join(SRC_ROOT, "feats"))
        base = os.path.basename(f)[:-4]
        # system.identifier is NOT unique in this source (all background
        # features share "feature"; class/multiclass/splashclass improvements
        # share one identifier per class), so slug comes from the filename,
        # prefixed with the subdirectory name for the colliding improvement
        # dirs (same filenames, genuinely different content).
        parent = os.path.dirname(rel)
        if parent.endswith("-improvements"):
            slug = f"{parent}-{base}"
        else:
            slug = base
        name = d.get("name") or slug.replace("-", " ").title()
        desc = html_to_md((sys_.get("description", {}) or {}).get("value", ""))
        prereq_level = (sys_.get("prerequisites") or {}).get("level")
        prerequisite = f"Level {prereq_level}+" if isinstance(prereq_level, int) else ""
        change_bits = []
        for eff in (d.get("effects") or []):
            for ch in (eff.get("changes") or []):
                key = ch.get("key") or ""
                val = ch.get("value")
                mode = ch.get("mode")
                bit = key if val in (None, "") else f"{key}: {val}"
                if mode:
                    bit = f"[mode {mode}] {bit}"
                if bit:
                    change_bits.append(bit)
        doc = doc_meta(sys_.get("source"))
        data = {
            "slug": slug, "name": name, "desc": desc,
            "prerequisite": prerequisite,
            "effects_desc": "\n".join(change_bits),
            "document__slug": doc[0],
            "document__title": doc[1],
            "document__license_url": "https://sw5e.com/attributing",
            "document__url": doc[4],
        }
        rows.append((slug, name, doc[0], "", data))
    return rows


_BG_LABELS = (
    ("skill_proficiencies", r"\*\*Skill Proficiencies:?\*\*"),
    ("tool_proficiencies", r"\*\*Tool Proficiencies:?\*\*"),
    ("languages", r"\*\*Languages:?\*\*"),
    ("equipment", r"\*\*Equipment:?\*\*"),
)
_BG_SPLIT = re.compile("(" + "|".join(
    [pat for _, pat in _BG_LABELS]
    + [r"## Feature:.*", r"## Suggested Characteristics",
       r"## Background Feat"]) + ")")


def build_backgrounds():
    """backgrounds(slug, name, document_slug, skills_csv, data_json)
    data_json: {slug, name, desc, skill_proficiencies, tool_proficiencies,
    languages, equipment, feature, feature_desc, suggested_characteristics,
    document__*}

    Most SW5e backgrounds carry their feature and proficiencies inside the
    description HTML, so each labelled section (**Label:** / ## Feature:) is
    split out of the markdown; sections that don't exist stay ''. No
    background in this source carries system.proficiencies, so skills_csv is
    '' for all (defensive read kept anyway)."""
    rows = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "backgrounds", "*.yml"))):
        d = _load(f)
        if (d.get("type") or "") not in ("background", "", None):
            continue
        sys_ = d.get("system") or {}
        slug = sys_.get("identifier") or os.path.basename(f)[:-4]
        name = d.get("name") or slug.replace("-", " ").title()
        md = html_to_md(((sys_.get("description") or {}).get("value")) or "")
        parts = _BG_SPLIT.split(md)
        # token -> body text up to the next token
        segs = {parts[i]: (parts[i + 1] if i + 1 < len(parts) else "")
                for i in range(1, len(parts) - 1, 2)}
        by_prefix = {}
        for tok in segs:
            key = ("feature" if tok.startswith("## Feature")
                   else "sugg" if tok.startswith("## Suggested")
                   else "bgfeat" if tok.startswith("## Background Feat")
                   else tok.split(":")[0].strip("* ").lower().split()[0])
            by_prefix.setdefault(key, tok)
        # desc: prose before the first labelled section
        positions = [p for p in (md.find(t) for t in segs) if p >= 0]
        desc = md[:min(positions)].strip() if positions else md.strip()
        feature_name = ""
        feat_tok = by_prefix.get("feature")
        if feat_tok:
            feature_name = re.sub(r"\s+", " ", re.sub(r"^## Feature:\s*", "", feat_tok)).strip()
        profs = sys_.get("proficiencies") or {}
        skill_list = profs.get("skills") or []
        doc = doc_meta(sys_.get("source"))

        def seg(key):
            tok = by_prefix.get(key)
            return segs[tok].strip() if tok else ""

        data = {
            "slug": slug, "name": name, "desc": desc,
            "skill_proficiencies": seg("skill"),
            "tool_proficiencies": seg("tool"),
            "languages": seg("languages"),
            "equipment": seg("equipment"),
            "feature": feature_name,
            "feature_desc": seg("feature"),
            "suggested_characteristics": seg("sugg"),
            "document__slug": doc[0],
            "document__title": doc[1],
            "document__license_url": "https://sw5e.com/attributing",
            "document__url": doc[4],
        }
        rows.append((slug, name, doc[0], ",".join(skill_list), data))
    return rows


_FORCE_CLASSES = "Consular, Guardian, Sentinel"
_TECH_CLASSES = "Engineer, Scout, Scholar"
_ACT_WORD = {"action": "action", "bonus": "bonus action", "reaction": "reaction"}
_LEVEL_WORD = {0: "Cantrip", 1: "1st", 2: "2nd", 3: "3rd"}
_current_slug = ""  # set by build_spells before each _range_text call


def _spell_level_word(level: int) -> str:
    return f"{_LEVEL_WORD.get(level, str(level) + 'th')}-level"


def _casting_time(activation: dict) -> str:
    """Foundry activation {type, cost} -> open5e casting_time string."""
    a = activation or {}
    typ = a.get("type") or "none"
    cost = a.get("cost") if isinstance(a.get("cost"), (int, float)) else 1
    if typ in _ACT_WORD:
        return f"1 {_ACT_WORD[typ]}"
    if typ in ("minute", "hour", "day"):
        return f"{cost} {typ}{'' if cost == 1 else 's'}"
    return "special"  # covers 'none' (two weapon-integrated powers) and anything new


def _duration_text(duration: dict, concentration: bool) -> str:
    d = duration or {}
    units = d.get("units") or ""
    val = d.get("value") or ""
    if units == "inst":
        return "Instantaneous"
    if units in ("minute", "hour", "day", "round", "turn"):
        try:
            n = int(val)
        except (TypeError, ValueError):
            n = 0
        word = f"{val} {units}{'' if n == 1 else 's'}"
        return f"Up to {word}" if concentration else word
    return ""


def _range_text(rng: dict) -> tuple:
    """(open5e range string, target_range_sort) — sort key as open5e computes
    it: self=0, touch=1, N feet=N, miles*5280, sight=9999, special=99990,
    unlimited=99999."""
    r = rng or {}
    units = r.get("units") or ""
    val = r.get("value")
    if units == "ft":
        n = int(val) if isinstance(val, (int, float)) else 0
        return f"{n} feet", n
    if units == "mi":
        n = int(val) if isinstance(val, (int, float)) else 1
        return f"{n} mile{'' if n == 1 else 's'}", n * 5280
    if units == "self":
        return "Self", 0
    if units == "touch":
        return "Touch", 1
    if not units:
        # 8 tech powers set no range: 'sending' is truly unlimited, the
        # weapon-attack riders act on the weapon's own range -> Self.
        if os.path.basename(_current_slug) == "sending":
            return "Unlimited", 99999
        return "Self", 0
    return "Special", 99990


def build_spells():
    """spells(slug, name, document_slug, level, school, classes_csv, ritual,
    concentration, aliases_csv, data_json)

    Force powers (force-powers/*/) and tech powers (tech-powers/*/) — the
    SW5e spell-equivalents; maneuvers are deliberately excluded (user
    decision, they are feat/action-shaped). Folder name gives the level
    ('1st-level'..'9th-level', 'at-will' = 0). school is the user-decided
    verbatim family string 'Force'/'Tech' (the source's uni/drk/lgt/tec
    sub-school is kept in data_json.sw5e_school). classes_csv is the family
    default list — no power YAML carries class data."""
    families = {
        "force-powers": ("Force", _FORCE_CLASSES, ["consular", "guardian", "sentinel"]),
        "tech-powers": ("Tech", _TECH_CLASSES, ["engineer", "scout", "scholar"]),
    }
    global _current_slug
    rows = []
    for family, (school, dnd_class, spell_lists) in families.items():
        base = os.path.join(SRC_ROOT, "powers-maneuvers", family)
        for folder in sorted(os.listdir(base)):
            dirpath = os.path.join(base, folder)
            if folder.startswith("_") or not os.path.isdir(dirpath):
                continue
            if folder == "at-will":
                level = 0
            else:
                level = int(re.match(r"(\d+)", folder).group(1))
            for f in sorted(glob.glob(os.path.join(dirpath, "*.yml"))):
                d = _load(f)
                if (d.get("type") or "") != "spell":
                    continue  # each level dir also carries an _folder.yml Item
                sys_ = d.get("system") or {}
                slug = os.path.basename(f)[:-4]
                _current_slug = slug
                name = d.get("name") or slug.replace("-", " ").title()
                desc = html_to_md((sys_.get("description", {}) or {}).get("value", ""))
                concentration = 1 if "concentration" in (sys_.get("properties") or []) else 0
                rng_str, sort = _range_text(sys_.get("range"))
                doc = doc_meta(sys_.get("source"))
                data = {
                    "slug": slug, "name": name, "desc": desc,
                    "higher_level": "", "page": "",
                    "range": rng_str, "target_range_sort": sort,
                    "components": "",
                    "requires_verbal_components": False,
                    "requires_somatic_components": False,
                    "requires_material_components": False,
                    "material": "",
                    "can_be_cast_as_ritual": False, "ritual": "no",
                    "duration": _duration_text(sys_.get("duration"), bool(concentration)),
                    "concentration": "yes" if concentration else "no",
                    "requires_concentration": bool(concentration),
                    "casting_time": _casting_time(sys_.get("activation")),
                    "level": _spell_level_word(level), "level_int": level,
                    "spell_level": level, "school": school,
                    "sw5e_school": sys_.get("school") or "",
                    "dnd_class": dnd_class, "spell_lists": spell_lists,
                    "archetype": "", "circles": "",
                    "document__slug": doc[0],
                    "document__title": doc[1],
                    "document__license_url": "https://sw5e.com/attributing",
                    "document__url": doc[4],
                }
                rows.append((slug, name, doc[0], level, school, dnd_class,
                             0, concentration, "", data))
    return rows


def main():
    races, race_rows = build_races()
    used_docs = {r["document_slug"] for r in races}
    cond_rows = build_conditions()
    feat_rows = build_feats()
    bg_rows = build_backgrounds()
    spell_rows = build_spells()
    used_docs.update(row[2] for row in cond_rows)
    used_docs.update(row[2] for row in feat_rows)
    used_docs.update(row[2] for row in bg_rows)
    used_docs.update(row[2] for row in spell_rows)
    doc_specs = {spec[0]: spec for spec in
                 sorted(set(DOCS.values()) | {DOC_DEFAULT}, key=lambda t: t[0])}
    docs = documents_rows_from(used_docs, doc_specs)
    write_pack(OUT, {
        "documents": docs,
        "races": race_rows,
        "conditions": cond_rows,
        "feats": feat_rows,
        "backgrounds": bg_rows,
        "spells": spell_rows,
    })
    print(f"races: {len(race_rows)} | conditions: {len(cond_rows)} | feats: {len(feat_rows)}"
          f" | backgrounds: {len(bg_rows)} | spells: {len(spell_rows)}")
    print("documents:", sorted(used_docs))


if __name__ == "__main__":
    sys.exit(main())
