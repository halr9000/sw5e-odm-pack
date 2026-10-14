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


def build_classes():
    """classes(slug, name, document_slug, hit_die, data_json)
    data_json: {name, slug, desc, hit_die, document__*} — picker-level rows
    only (user decision): no feature tables, no proficiency/table text."""
    rows = []
    for f in sorted(glob.glob(os.path.join(SRC_ROOT, "character-classes",
                                           "*", "*.yml"))):
        slug = os.path.basename(f)[:-4]
        if os.path.basename(os.path.dirname(f)) != slug:
            continue  # only <slug>/<slug>.yml is the class file itself
        d = _load(f)
        sys_ = d.get("system") or {}
        hd = ((sys_.get("hd") or {}).get("denomination") or "")
        hit_die = int(hd[1:]) if hd.startswith("d") and hd[1:].isdigit() else 0
        doc = doc_meta(sys_.get("source"))
        data = {
            "name": d.get("name") or slug.title(), "slug": slug,
            "desc": html_to_md((sys_.get("description") or {}).get("value", "")),
            "hit_die": hit_die,
            "document__slug": doc[0],
            "document__title": doc[1],
            "document__license_url": "https://sw5e.com/attributing",
            "document__url": doc[4],
        }
        rows.append((slug, data["name"], doc[0], hit_die, data))
    return rows


def build_archetypes():
    """archetypes(slug, name, document_slug, class_slug, data_json)
    data_json: {name, slug, subclass_class_name, desc, document__*}
    <class>/archetypes/*.yml type: subclass files; class_slug = owning class
    folder. All 137 archetype identifiers are unique across classes, so the
    identifier/filename stands as the slug directly."""
    rows = []
    classes = {r[0]: r[1] for r in build_classes()}
    for class_slug in sorted(classes):
        for f in sorted(glob.glob(os.path.join(SRC_ROOT, "character-classes",
                                               class_slug, "archetypes", "*.yml"))):
            d = _load(f)
            if (d.get("type") or "") != "subclass":
                continue  # _folder.yml and any non-subclass shape
            sys_ = d.get("system") or {}
            slug = sys_.get("identifier") or os.path.basename(f)[:-4]
            name = d.get("name") or slug.replace("-", " ").title()
            doc = doc_meta(sys_.get("source"))
            data = {
                "name": name, "slug": slug,
                "subclass_class_name": classes[class_slug],
                "desc": html_to_md((sys_.get("description") or {}).get("value", "")),
                "document__slug": doc[0],
                "document__title": doc[1],
                "document__license_url": "https://sw5e.com/attributing",
                "document__url": doc[4],
            }
            rows.append((slug, name, doc[0], class_slug, data))
    return rows


_ITEM_KEY_LABELS = {
    "two": "two-handed", "luminous": "luminous", "lgt": "light", "fin": "finesse",
    "strRq": "strength", "dexRq": "dexterity", "hidden": "hidden", "rel": "reload",
    "ver": "versatile", "rch": "reach", "auto": "automatic", "hvy": "heavy",
    "fixed": "fixed", "special": "special", "silentWeapon": "silent",
    "silentEquipment": "silent", "powerCell": "power cell", "mighty": "mighty",
    "disarming": "disarming", "ret": "retractable", "interlockingWeapon": "interlocking",
}
_ITEM_CATEGORIES = {
    "simple-blasters": "Simple Blasters", "martial-blasters": "Martial Blasters",
    "exotic-blasters": "Exotic Blasters",
    "simple-lightweapons": "Simple Light Weapons",
    "martial-lightweapons": "Martial Light Weapons",
    "exotic-lightweapons": "Exotic Light Weapons",
    "simple-vibroweapons": "Simple Vibroweapons",
    "martial-vibroweapons": "Martial Vibroweapons",
    "exotic-vibroweapons": "Exotic Vibroweapons",
    "natural-weapons": "Natural Weapons",
    "light": "Light Armor", "medium": "Medium Armor", "heavy": "Heavy Armor",
    "shield": "Shields",
    "artisans-implements": "Artisan's Implements", "gaming-sets": "Gaming Sets",
    "musical-instruments": "Musical Instruments",
    "specialists-kits": "Specialists Kits",
    "adventuring-gear": "Adventuring Gear", "weapons": "Weapons",
    "armor": "Armor", "tools": "Tools", "consumables": "Consumables",
    "cybernetic-augmentations": "Cybernetic Augmentations",
    "droid-customizations": "Droid Customizations",
    "focus-generators": "Focus Generators", "item-modifications": "Item Modifications",
}


def _item_category(folder: str) -> str:
    return _ITEM_CATEGORIES.get(folder) or folder.replace("-", " ").title()


def _item_props(d: dict) -> list:
    """Readable property strings for a weapon/armor item: system.properties
    keys (dnd5e short codes) labeled via _ITEM_KEY_LABELS, values taken from
    flags.sw5e.properties when present (e.g. rel: 16 -> 'reload 16')."""
    sys_ = d.get("system") or {}
    flag_props = ((d.get("flags") or {}).get("sw5e") or {}).get("properties") or {}
    out = []
    for key in (sys_.get("properties") or []):
        val = flag_props.get(key)
        label = _ITEM_KEY_LABELS.get(key, key)
        if isinstance(val, (int, float, str)) and val not in (True, None, ""):
            out.append(f"{label} {val}")
        else:
            out.append(label)
    return out


def _item_cost(sys_: dict) -> str:
    price = sys_.get("price") or {}
    if price.get("value") in (None, ""):
        return ""
    denom = price.get("denomination") or "gc"
    return f"{price['value']} {denom}"


def _item_weight(sys_: dict) -> float:
    w = (sys_.get("weight") or {}).get("value")
    try:
        return float(w)
    except (TypeError, ValueError):
        return 0.0  # ODM convention: 0 = the source did not say


def _item_doc_tag(doc):
    return {
        "document__slug": doc[0], "document__title": doc[1],
        "document__license_url": "https://sw5e.com/attributing",
        "document__url": doc[4],
    }


def build_items():
    """items(slug, name, document_slug, kind, rarity, cost, category, weight,
    data_json)

    Sources: equipment/ (weapons, armor, adventuring-gear, tools) and
    enhanceditems/ (all kinds of augmented gear -> magic_item); the
    third-party codex item packs are excluded (user decision: only monsters
    were mandated full third-party coverage). kind mapping: type weapon ->
    weapon; equipment/armor folder -> armor; everything else under
    equipment/ -> gear; enhanceditems/ -> magic_item. category comes from
    the parent folder name. data_json shape per kind follows the open5e
    pack rows (weapon: damage_dice/damage_type/properties; armor:
    base_ac/plus_dex_mod/plus_max/ac_string/strength_requirement/
    stealth_disadvantage; gear/magic_item: desc + rarity/attunement)."""
    base = os.path.join(SRC_ROOT)
    files = [f for f in glob.glob(os.path.join(base, "equipment", "**", "*.yml"),
                                  recursive=True)
             + glob.glob(os.path.join(base, "enhanceditems", "**", "*.yml"),
                         recursive=True)
             if not os.path.basename(f).startswith("_")]
    # disambiguate colliding filenames (33, e.g. pack contents vs utilities)
    by_base = {}
    for f in files:
        by_base.setdefault(os.path.basename(f)[:-4], []).append(f)
    rows = []
    for f in sorted(files):
        d = _load(f)
        sys_ = d.get("system") or {}
        base_name = os.path.basename(f)[:-4]
        eq_root = os.path.join(base, "equipment")
        pack = "equipment" if f.startswith(eq_root) else "enhanceditems"
        rel_dir = os.path.relpath(os.path.dirname(f), os.path.join(base, pack))
        parent = os.path.basename(os.path.dirname(f))
        in_armor_tree = rel_dir == "armor" or rel_dir.startswith("armor" + os.sep)
        if len(by_base.get(base_name, [])) > 1:
            slug = f"{parent}-{base_name}"
        else:
            slug = base_name
        name = d.get("name") or slug.replace("-", " ").title()
        desc = html_to_md((sys_.get("description") or {}).get("value", ""))
        kind = "magic_item" if pack == "enhanceditems" else (
            "weapon" if d.get("type") == "weapon"
            else "armor" if in_armor_tree
            else "gear")
        cost = _item_cost(sys_)
        weight = _item_weight(sys_)
        rarity = sys_.get("rarity") or ""
        category = _item_category(parent)
        data = {"name": name, "slug": slug, "category": category, "desc": desc,
                "cost": cost, "weight": weight, **_item_doc_tag(doc_meta(sys_.get("source")))}
        if kind == "weapon":
            parts = ((sys_.get("damage") or {}).get("parts") or [])
            dice = str(parts[0][0]).replace(" + @mod", "") if parts else ""
            dtype = str(parts[0][1]) if parts else ""
            data.update({"damage_dice": dice, "damage_type": dtype,
                         "properties": _item_props(d)})
        elif kind == "armor":
            armor = sys_.get("armor") or {}
            dex = armor.get("dex")
            value = armor.get("value")
            data.update({
                "base_ac": value, "plus_dex_mod": dex != 0,
                "plus_flat_mod": 0, "plus_max": dex or 0,
                "ac_string": (f"{value} + Dex modifier (max {dex})" if dex
                              else f"{value} + Dex modifier" if dex is None
                              else str(value)),
                "strength_requirement": None,
                "stealth_disadvantage": "stealthDisadvantage"
                in (sys_.get("properties") or []),
                "properties": _item_props(d),
            })
            for key in (sys_.get("properties") or []):
                if key == "strength":
                    data["strength_requirement"] = \
                        (((d.get("flags") or {}).get("sw5e") or {})
                         .get("properties") or {}).get("strength")
        elif kind == "magic_item":
            data.update({
                "rarity": rarity,
                "requires_attunement": sys_.get("attunement") == "required",
            })
        rows.append((slug, name, data["document__slug"], kind, rarity, cost,
                     category, weight, data))
    return rows


# --- monsters -------------------------------------------------------------
# NPC-statblock packs, FULL third-party coverage (user decision 2026-10-14).
# drakes-shipyard/ is excluded: every YAML there is `type: vehicle`, not an
# NPC statblock. monstertraits/ is a shared trait library (feat/weapon-shaped
# items), not statblocks; NPC items carry their descriptions inline, so it is
# not needed for text resolution either.
MONSTER_PACKS = {  # pack dir -> (document_slug, document title)
    "monsters":             ("sw5e",                       "SW5e Bestiary"),
    "snv-monsters":         ("sw5e-snv",                   "Scum and Villainy Monsters"),
    "fistoscodex":          ("sw5e-fistoscodex",           "Fisto's Codex"),
    "mandaloriancodexnpcs": ("sw5e-mandaloriancodexnpcs",  "Mandalorian Codex NPCs"),
    "veshs-galactic-holodex": ("sw5e-veshs-galactic-holodex", "Vesh's Galactic Holodex"),
}
MONSTER_DOC_LICENSE = "CC-BY-NC-SA-4.0"
MONSTER_DOC_AUTHOR = "SW5e community (third-party)"

# Foundry short size codes -> open5e size words.
MONSTER_SIZES = {"fine": "Fine", "dim": "Diminutive", "tiny": "Tiny",
                 "sm": "Small", "med": "Medium", "lg": "Large",
                 "huge": "Huge", "grg": "Gargantuan"}

# Foundry skill keys -> open5e snake_case skill names.
MONSTER_SKILLS = {
    "acr": "acrobatics", "ani": "animal_handling", "ath": "athletics",
    "dec": "deception", "ins": "insight", "itm": "intimidation",
    "inv": "investigation", "lor": "lore", "med": "medicine",
    "nat": "nature", "pil": "piloting", "prc": "perception",
    "prf": "persuasion", "per": "performance", "slt": "sleight_of_hand",
    "ste": "stealth", "sur": "survival", "tec": "technology",
}
MONSTER_ABILITY_KEYS = [("strength", "str"), ("dexterity", "dex"),
                        ("constitution", "con"), ("intelligence", "int"),
                        ("wisdom", "wis"), ("charisma", "cha")]
# Damage/condition immunity keys that differ from their open5e text; anything
# not listed passes through as-is (lowercased).
MONSTER_DAMAGE_LABELS = {"kinetic": "kinetic", "energy": "energy",
                         "ion": "ion", "sonic": "sonic"}
MONSTER_CONDITION_LABELS = {
    "diseased": "diseased", "exhaustion": "exhaustion",
}
# Foundry ac.calc -> open5e armor_desc.
MONSTER_AC_DESC = {"natural": "natural armor"}


def _cr_value(raw):
    """'1/2'|0.25|24 -> float. Unparseable -> 0."""
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw or "").strip()
    if s in ("1/8",):
        return 0.125
    if s in ("1/4",):
        return 0.25
    if s in ("1/2",):
        return 0.5
    try:
        return float(s)
    except ValueError:
        return 0.0


def _cr_text(cr):
    if cr == int(cr) and cr >= 1:
        return str(int(cr))
    return {0.125: "1/8", 0.25: "1/4", 0.5: "1/2"}.get(cr, str(cr))


def _prof_bonus(cr):
    if cr < 1:
        return 2
    return 2 + int(cr - 1) // 4


def _mod(score):
    return (score - 10) // 2 if score else -5


def _label_list(keys, overrides):
    out = []
    for k in keys:
        k = str(k).strip().lower()
        if not k:
            continue
        out.append(overrides.get(k, k))
    return out


def _joined(trait_key, overrides, custom):
    parts = _label_list(trait_key, overrides)
    if custom and custom.strip() not in ("-", "—", "â€”"):
        parts.append(custom.strip())
    return ", ".join(parts)


def _lang_text(values, custom):
    """Language key list + custom free-text -> 'Basic, Huttese, <custom>'."""
    parts = [str(v).strip().title() for v in values if str(v).strip()]
    if custom and custom.strip() not in ("-", "—", "â€”"):
        parts.append(custom.strip())
    return ", ".join(parts)


def _mon_action(item):
    """Foundry NPC item -> open5e action entry {name, desc[, attack_bonus,
    damage_dice]}, or None for items that don't belong in a statblock."""
    it_type = item.get("type")
    if it_type not in ("feat", "weapon"):
        return None  # spells are summarized by the innate-casting trait;
                     # equipment/consumables are not statblock entries
    sy = item.get("system") or {}
    desc = html_to_md(((sy.get("description") or {}).get("value")) or "")
    entry = {"name": item.get("name") or "", "desc": desc}
    if it_type == "weapon":
        bonus = (sy.get("attack") or {}).get("bonus")
        try:
            entry["attack_bonus"] = int(str(bonus).replace("+", ""))
        except (ValueError, TypeError):
            pass
        parts = (sy.get("damage") or {}).get("parts") or []
        dice = " + ".join(str(p[0]) for p in parts if p and p[0])
        if dice:
            entry["damage_dice"] = dice.replace(" + @mod", "")
    return entry


def _mon_bucket(activation_type):
    """Foundry activation.type -> which open5e array the entry belongs in."""
    if activation_type == "legendary":
        return "legendary_actions"
    if activation_type == "bonus":
        return "bonus_actions"
    if activation_type == "reaction":
        return "reactions"
    if activation_type in ("action", "minute", "hour", "day", "special"):
        return "actions"
    return "special_abilities"  # '', 'none', None -> passive trait


def build_monsters():
    """monsters(slug, name, document_slug, cr, type, data_json)

    FULL coverage of every NPC-statblock pack (MONSTER_PACKS). Port of ODM's
    statblock shape (scripts/lib/open5e-normalize.mjs normalizeMonster target
    schema, i.e. the data_json of an actual open5e.sqlite monsters row):
    open5e key set with actions/bonus_actions/reactions/legendary_actions/
    special_abilities as JSON arrays of {name, desc}; environments [] and
    group null (both empty in the source). Handles the two on-disk
    generations defensively (importer_version 3 core files vs dnd5e 5.2.5
    regenerated third-party packs): every read is a .get chain, CR may be
    int/float/str, mandaloriancodexnpcs lacks an `attributes` block entirely
    (AC/HP/speed default to 0/''), and saves/skills are computed from
    ability scores + proficiency flags with the proficiency bonus derived
    from CR (Foundry does not store it for NPCs). document__slug is tagged
    PER PACK so third-party rows are separable."""
    files = []   # (pack_dir, relpath, doc_slug)
    for pack, (doc_slug, _title) in MONSTER_PACKS.items():
        for f in sorted(glob.glob(os.path.join(SRC_ROOT, pack, "**", "*.yml"),
                                  recursive=True)):
            if os.path.basename(f).startswith("_"):
                continue
            files.append((pack, f, doc_slug))
    # slug disambiguation, same pattern as the items pass: basename; if it
    # collides, prefix the pack tag (cross-pack) or parent folder (within
    # one pack); a final global seen-set guarantees uniqueness.
    by_base = {}
    for pack, f, _ in files:
        by_base.setdefault(os.path.basename(f)[:-4], []).append(pack)
    pack_tag = {"snv-monsters": "snv", "fistoscodex": "fisto",
                "mandaloriancodexnpcs": "mcodex",
                "veshs-galactic-holodex": "veshs", "monsters": "sw5e"}
    used_slugs = set()
    rows = []
    n_walked = 0
    n_skipped = 0
    for pack, f, doc_slug in files:
        d = _load(f)
        if d.get("type") != "npc":
            n_skipped += 1
            continue
        n_walked += 1
        sys_ = d.get("system") or {}
        det = sys_.get("details") or {}
        tr = sys_.get("traits") or {}
        attr = sys_.get("attributes") or {}
        base_name = os.path.basename(f)[:-4]
        colliders = by_base.get(base_name, [])
        parent = os.path.basename(os.path.dirname(f))
        if len(colliders) > 1 and len(set(colliders)) > 1:
            slug = f"{pack_tag[pack]}-{base_name}"
        elif len(colliders) > 1:
            slug = f"{parent}-{base_name}"
        else:
            slug = base_name
        while slug in used_slugs:
            slug = f"{slug}-x"
        used_slugs.add(slug)
        name = d.get("name") or base_name.replace("-", " ").title()
        cr = _cr_value(det.get("cr"))
        pb = _prof_bonus(cr)
        ctype = det.get("type") or {}
        type_value = str(ctype.get("value") or
                         os.path.basename(os.path.dirname(f))).lower()
        # description: biography (most packs) or description (mandalorian) —
        # prefer whichever actually carries text
        bio = det.get("biography") or {}
        alt = det.get("description") or {}
        if not (bio.get("value") or "").strip() and alt.get("value"):
            bio = alt
        desc = html_to_md(bio.get("value") or "")
        # abilities + saves
        ab = sys_.get("abilities") or {}
        ability_scores, saves = {}, {}
        for col, key in MONSTER_ABILITY_KEYS:
            score = ((ab.get(key) or {}).get("value"))
            score = score if isinstance(score, (int, float)) else 10
            ability_scores[col] = int(score)
            prof = (ab.get(key) or {}).get("proficient")
            saves[col + "_save"] = (_mod(score) + pb * prof
                                    if prof else None)
        # skills: bonus = ability mod + pb * proficiency (0 none, 1 prof,
        # 2 expertise)
        skills = {}
        for key, info in (sys_.get("skills") or {}).items():
            val = info.get("value")
            if not val:
                continue
            abil = info.get("ability") or "wis"
            score = ability_scores.get(
                {v: k for k, v in MONSTER_ABILITY_KEYS}.get(abil, "wisdom"), 10)
            skills[MONSTER_SKILLS.get(key, key)] = _mod(score) + pb * min(val, 2)
        # AC / HP / speed / senses
        ac = attr.get("ac") or {}
        hp = attr.get("hp") or {}
        speed = {k: int(attr["movement"][k])
                 for k in ("walk", "fly", "swim", "burrow", "climb")
                 if isinstance((attr.get("movement") or {}).get(k), (int, float))
                 and attr["movement"][k] > 0}
        se = attr.get("senses") or {}
        sense_bits = [f"{label} {se[k]} ft."
                      for label, k in (("darkvision", "darkvision"),
                                       ("blindsight", "blindsight"),
                                       ("tremorsense", "tremorsense"),
                                       ("truesight", "truesight"))
                      if isinstance(se.get(k), (int, float)) and se[k] > 0]
        if (se.get("special") or "").strip():
            sense_bits.append(str(se["special"]).strip())
        perception = skills.get("perception")
        if perception is None:
            perception = _mod(ability_scores["wisdom"])
        sense_bits.append(f"passive Perception {10 + perception}")
        # items -> action buckets
        buckets = {"actions": [], "bonus_actions": [], "reactions": [],
                   "legendary_actions": [], "special_abilities": []}
        n_spells = 0
        for item in (d.get("items") or []):
            if item.get("type") == "spell":
                n_spells += 1
                continue
            entry = _mon_action(item)
            if entry is None:
                continue
            buckets[_mon_bucket(((item.get("system") or {})
                                 .get("activation") or {}).get("type"))].append(entry)
        if not any(buckets.values()) and n_spells:
            # statblock whose only entries are cast powers: fall back to
            # listing them as actions so the row isn't actionless
            for item in (d.get("items") or []):
                if item.get("type") == "spell":
                    sy = item.get("system") or {}
                    buckets["actions"].append({
                        "name": item.get("name") or "",
                        "desc": html_to_md(
                            ((sy.get("description") or {}).get("value")) or ""),
                    })
        legact = ((sys_.get("resources") or {}).get("legact") or {})
        legendary_desc = (f"The {name} can take {legact.get('max')} legendary "
                          f"actions, choosing from the options below. Only one "
                          f"legendary action can be used at a time and only at "
                          f"the end of another creature's turn. It regains "
                          f"spent legendary actions at the start of its turn."
                          if legact.get("max") else "")
        data = {
            "slug": slug,
            "desc": desc,
            "name": name,
            "size": MONSTER_SIZES.get(tr.get("size") or "", "Medium"),
            "type": type_value,
            "subtype": ctype.get("subtype") or "",
            "group": None,
            "alignment": det.get("alignment") or "",
            "armor_class": ac.get("flat") or 0,
            "armor_desc": MONSTER_AC_DESC.get(ac.get("calc") or "", ""),
            "hit_points": hp.get("value") or 0,
            "hit_dice": str(hp.get("formula") or ""),
            "speed": speed,
            "strength": ability_scores["strength"],
            "dexterity": ability_scores["dexterity"],
            "constitution": ability_scores["constitution"],
            "intelligence": ability_scores["intelligence"],
            "wisdom": ability_scores["wisdom"],
            "charisma": ability_scores["charisma"],
            "strength_save": saves["strength_save"],
            "dexterity_save": saves["dexterity_save"],
            "constitution_save": saves["constitution_save"],
            "intelligence_save": saves["intelligence_save"],
            "wisdom_save": saves["wisdom_save"],
            "charisma_save": saves["charisma_save"],
            "perception": perception,
            "skills": skills,
            "damage_vulnerabilities": _joined((tr.get("dv") or {}).get("value", []),
                                              MONSTER_DAMAGE_LABELS,
                                              (tr.get("dv") or {}).get("custom", "")),
            "damage_resistances": _joined((tr.get("dr") or {}).get("value", []),
                                          MONSTER_DAMAGE_LABELS,
                                          (tr.get("dr") or {}).get("custom", "")),
            "damage_immunities": _joined((tr.get("di") or {}).get("value", []),
                                         MONSTER_DAMAGE_LABELS,
                                         (tr.get("di") or {}).get("custom", "")),
            "condition_immunities": _joined((tr.get("ci") or {}).get("value", []),
                                            MONSTER_CONDITION_LABELS,
                                            (tr.get("ci") or {}).get("custom", "")),
            "senses": ", ".join(sense_bits),
            "languages": _lang_text((tr.get("languages") or {}).get("value", []),
                                    (tr.get("languages") or {}).get("custom", "")),
            "challenge_rating": _cr_text(cr),
            "cr": cr,
            "actions": buckets["actions"] or None,
            "bonus_actions": buckets["bonus_actions"] or None,
            "reactions": buckets["reactions"] or None,
            "legendary_desc": legendary_desc,
            "legendary_actions": buckets["legendary_actions"] or None,
            "special_abilities": buckets["special_abilities"] or None,
            "spell_list": [],
            "page_no": 0,
            "environments": [e.strip() for e in
                             str(det.get("environment") or "").split(",")
                             if e.strip()],
            "img_main": None,
            "document__slug": doc_slug,
            "document__title": MONSTER_PACKS[pack][1],
            "document__license_url": "https://sw5e.com/attributing",
            "document__url": "https://sw5e.com/",
        }
        rows.append((slug, name, doc_slug, cr, type_value, data))
    print(f"monsters: walked {n_walked} type:npc YAMLs "
          f"({n_skipped} non-NPC skipped) -> {len(rows)} rows")
    return rows


def main():
    races, race_rows = build_races()
    used_docs = {r["document_slug"] for r in races}
    cond_rows = build_conditions()
    feat_rows = build_feats()
    bg_rows = build_backgrounds()
    spell_rows = build_spells()
    class_rows = build_classes()
    arch_rows = build_archetypes()
    item_rows = build_items()
    monster_rows = build_monsters()
    used_docs.update(row[2] for row in cond_rows)
    used_docs.update(row[2] for row in feat_rows)
    used_docs.update(row[2] for row in bg_rows)
    used_docs.update(row[2] for row in spell_rows)
    used_docs.update(row[2] for row in class_rows)
    used_docs.update(row[2] for row in arch_rows)
    used_docs.update(row[2] for row in item_rows)
    used_docs.update(row[2] for row in monster_rows)
    monster_doc_specs = {
        slug: (slug, title, MONSTER_DOC_LICENSE,
               MONSTER_DOC_AUTHOR if slug != "sw5e" else "SW5e team",
               "https://sw5e.com/")
        for slug, title in MONSTER_PACKS.values()}
    doc_specs = {spec[0]: spec for spec in
                 sorted(set(DOCS.values()) | {DOC_DEFAULT}
                        | set(monster_doc_specs.values()), key=lambda t: t[0])}
    docs = documents_rows_from(used_docs, doc_specs)
    write_pack(OUT, {
        "documents": docs,
        "races": race_rows,
        "conditions": cond_rows,
        "feats": feat_rows,
        "backgrounds": bg_rows,
        "spells": spell_rows,
        "classes": class_rows,
        "archetypes": arch_rows,
        "items": item_rows,
        "monsters": monster_rows,
    })
    print(f"races: {len(race_rows)} | conditions: {len(cond_rows)} | feats: {len(feat_rows)}"
          f" | backgrounds: {len(bg_rows)} | spells: {len(spell_rows)}"
          f" | classes: {len(class_rows)} | archetypes: {len(arch_rows)}"
          f" | items: {len(item_rows)} | monsters: {len(monster_rows)}")
    print("documents:", sorted(used_docs))


if __name__ == "__main__":
    sys.exit(main())
