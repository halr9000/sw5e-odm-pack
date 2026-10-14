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


def main():
    races, race_rows = build_races()
    used_docs = {r["document_slug"] for r in races}
    cond_rows = build_conditions()
    feat_rows = build_feats()
    bg_rows = build_backgrounds()
    used_docs.update(row[2] for row in cond_rows)
    used_docs.update(row[2] for row in feat_rows)
    used_docs.update(row[2] for row in bg_rows)
    doc_specs = {spec[0]: spec for spec in
                 sorted(set(DOCS.values()) | {DOC_DEFAULT}, key=lambda t: t[0])}
    docs = documents_rows_from(used_docs, doc_specs)
    write_pack(OUT, {
        "documents": docs,
        "races": race_rows,
        "conditions": cond_rows,
        "feats": feat_rows,
        "backgrounds": bg_rows,
    })
    print(f"races: {len(race_rows)} | conditions: {len(cond_rows)} | feats: {len(feat_rows)}"
          f" | backgrounds: {len(bg_rows)}")
    print("documents:", sorted(used_docs))


if __name__ == "__main__":
    sys.exit(main())
