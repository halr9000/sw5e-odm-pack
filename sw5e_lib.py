#!/usr/bin/env python3
"""Shared library for building the SW5e open5e-schema content pack.

Imported by the per-table builders (build_sw5e_races.py, build_sw5e_pack.py).
Provides: YAML helpers, HTML->markdown, the SW5e document mapping, the races
normalizer, the full 10-table SCHEMA_SQL (copied verbatim from ODM's
data/content/open5e.sqlite) and the write_pack() helper that creates the
schema and fills only the tables passed in.
"""

import glob
import json
import os
import re
import sqlite3

import yaml

SRC_ROOT = os.path.expanduser("~/projects/sw5e-module/packs/_source")

BOILERPLATE = {"ability-score-increase", "age", "alignment", "languages",
               "size", "speed", "darkvision", "blindsight", "special-senses"}

# SW5e source.custom values -> document metadata (url points at sw5e content).
# "WH" = SW5e Wretched Hives (module utils/book-journal-config.mjs).
DOCS = {
    "PHB": ("sw5e-phb", "SW5e Player's Handbook", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/"),
    "EC":  ("sw5e-ec", "SW5e Expanded Content", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/content/expandedcontent"),
    "UAC": ("sw5e-uac", "SW5e Unsplash a Collab", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/"),
    "WH":  ("sw5e-wh", "SW5e Wretched Hives", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/"),
}
DOC_DEFAULT = ("sw5e-module", "SW5e Foundry Module", "CC-BY-NC-SA-4.0",
               "sw5e-foundry", "https://github.com/sw5e-foundry/sw5e-module")

ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
SIZES = ["Small", "Medium", "Large", "Huge", "Gargantuan"]


def html_to_md(html: str) -> str:
    """Naive Foundry HTML -> markdown-ish prose (enough for the pack)."""
    s = html or ""
    s = re.sub(r"<h(\d)[^>]*>(.*?)</h\1>", r"\n## \2\n", s, flags=re.S)
    s = re.sub(r"<strong>(.*?)</strong>", r"**\1**", s, flags=re.S)
    s = re.sub(r"<em>(.*?)</em>", r"*\1*", s, flags=re.S)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n\n", s, flags=re.S)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def sw5e_doc(src: dict):
    """(slug, title, author, url) from a Foundry `system.source` dict.

    Accepts source.custom ("PHB"/"EC"/"UAC"/"WH"), with source.book /
    source.page fallbacks for files that carry no custom tag.
    """
    custom = (src or {}).get("custom") or ""
    book = (src or {}).get("book") or ""
    if custom:
        return DOCS.get(custom.strip(), DOC_DEFAULT)
    if book:
        return DOCS.get(book.strip(), DOC_DEFAULT)
    return DOC_DEFAULT


def trait_text(slug_dir: str, name: str):
    """Return (identifier, markdown_text) for a species trait file, or None."""
    path = os.path.join(slug_dir, name + ".yml")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        d = yaml.safe_load(fh)
    desc = html_to_md((d.get("system", {}).get("description", {}) or {}).get("value", ""))
    return d["system"].get("identifier", name), desc


def parse_asi(text: str):
    """'Your Constitution score increases by 2, and your Strength score
    increases by 1.' -> [{'attributes':['Constitution'],'value':2}, ...]"""
    out = []
    # find every "<Ability> ... <num>" pairing in the sentence
    for chunk in re.split(r",\s*(?:and\s+)?|\s+and\s+", text):
        m = re.search(r"(" + "|".join(ABILITIES) + r")", chunk, re.I)
        n = re.search(r"(\d+)", chunk)
        if m and n:
            out.append({"attributes": [m.group(1).title()], "value": int(n.group(1))})
    return out


def load_race(path: str):
    with open(path) as fh:
        d = yaml.safe_load(fh)
    sys_ = d.get("system", {})
    slug = sys_.get("identifier") or os.path.basename(path)[:-4]
    feats_dir = os.path.join(SRC_ROOT, "species", "species-features", slug)
    data = {
        "name": d["name"], "slug": slug, "desc": html_to_md(
            (sys_.get("description", {}) or {}).get("value", "")),
    }
    traits = []
    vision_bits = []
    if os.path.isdir(feats_dir):
        for f in sorted(glob.glob(os.path.join(feats_dir, "*.yml"))):
            base = os.path.basename(f)[:-4]
            if base.startswith("_"):
                continue
            got = trait_text(os.path.dirname(f), base)
            if not got:
                continue
            ident, text = got
            if base == "ability-score-increase":
                data["asi"] = parse_asi(text)
                data["asi_desc"] = text
            elif base == "size":
                data["size"] = text
                for s in SIZES:
                    if re.search(r"\b" + s + r"\b", text):
                        data["size_raw"] = s
                        break
            elif base == "speed":
                data["speed_desc"] = text
            elif base == "age":
                data["age"] = text
            elif base == "alignment":
                data["alignment"] = text
            elif base == "languages":
                data["languages"] = text
            elif base in {"darkvision", "blindsight", "special-senses"}:
                vision_bits.append(text)
            else:
                traits.append(f"**{ident.replace('-', ' ').title()}.** {text}" if text else f"**{ident}**")
    movement = (sys_.get("movement", {}) or {})
    walk = movement.get("walk")
    data.setdefault("speed", {"walk": walk if isinstance(walk, int) else None})
    if vision_bits:
        data["vision"] = "\n\n".join(vision_bits)
    data["traits"] = "\n\n".join(traits)
    doc = sw5e_doc((sys_.get("source", {}) or {}))
    doc_slug = doc[0]
    data["document__slug"] = doc_slug
    data["document__title"] = doc[1]
    data["document__license_url"] = "https://sw5e.com/attributing"
    data["document__url"] = doc[4]
    data.setdefault("asi", [])
    data.setdefault("asi_desc", "")
    for k in ("size", "size_raw", "age", "alignment", "languages", "speed_desc"):
        data.setdefault(k, "")
    return {
        "slug": slug, "name": d["name"], "document_slug": doc_slug,
        "is_subrace": 0, "parent_slug": "", "data_json": data,
    }


# Full 10-table schema, copied VERBATIM from
#   sqlite3 ~/projects/open-dungeon-master/data/content/open5e.sqlite .schema
SCHEMA_SQL = """
CREATE TABLE spells (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      level INTEGER NOT NULL, school TEXT NOT NULL, classes_csv TEXT NOT NULL,
      ritual INTEGER NOT NULL, concentration INTEGER NOT NULL,
      -- Other names the same spell is printed under. The SRD renames every
      -- wizard-named PHB spell ("Melf's Acid Arrow" -> "Acid Arrow"), so a
      -- player searching the name in their book found nothing until searches
      -- started matching this column too.
      aliases_csv TEXT NOT NULL DEFAULT '',
      data_json TEXT NOT NULL
    );
CREATE TABLE feats (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      aliases_csv TEXT NOT NULL DEFAULT '', data_json TEXT NOT NULL
    );
CREATE TABLE conditions (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      data_json TEXT NOT NULL
    );
CREATE TABLE backgrounds (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      skills_csv TEXT NOT NULL, data_json TEXT NOT NULL
    );
CREATE TABLE races (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      is_subrace INTEGER NOT NULL, parent_slug TEXT NOT NULL, data_json TEXT NOT NULL
    );
CREATE TABLE classes (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      hit_die INTEGER NOT NULL, data_json TEXT NOT NULL
    );
CREATE TABLE archetypes (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      class_slug TEXT NOT NULL, data_json TEXT NOT NULL
    );
CREATE TABLE items (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      kind TEXT NOT NULL CHECK (kind IN ('weapon','armor','gear','magic_item')),
      rarity TEXT NOT NULL, cost TEXT NOT NULL, category TEXT NOT NULL,
      -- Pounds. 0 means "the source did not say", not "weightless"; the
      -- encumbrance rule reports how many carried items are unweighed rather
      -- than pretending the total is exact.
      weight REAL NOT NULL DEFAULT 0,
      data_json TEXT NOT NULL
    );
CREATE TABLE monsters (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
      cr REAL NOT NULL, type TEXT NOT NULL, data_json TEXT NOT NULL
    );
CREATE TABLE documents (
      slug TEXT PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL,
      license TEXT NOT NULL, author TEXT NOT NULL, url TEXT NOT NULL,
      data_json TEXT NOT NULL
    );
CREATE INDEX idx_spells_search ON spells(level, school);
CREATE INDEX idx_items_kind ON items(kind);
CREATE INDEX idx_monsters_cr ON monsters(cr);
CREATE INDEX idx_archetypes_class ON archetypes(class_slug);
"""


def write_pack(path: str, inserts: dict) -> None:
    """Create the full 10-table schema at `path` (overwriting it) and fill
    only the tables present in `inserts` ({table: [row tuples,...]})."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA_SQL)
    for table, rows in inserts.items():
        if not rows:
            continue
        ncol = len(rows[0])
        con.executemany(
            f"INSERT INTO {table} VALUES ({','.join('?' * ncol)})",
            [tuple(
                json.dumps(r[-1]) if k == ncol - 1 else r[k]
                for k in range(ncol)
            ) for r in rows],
        )
    con.commit()
    con.close()


def documents_rows_from(used_slugs, entries=None):
    """Documents-table rows for every document slug in `used_slugs`.
    `entries` maps slug -> (slug, title, license, author, url) — the DOCS
    tuple shape; both `name` and `title` columns carry the title text
    (same convention as the original races slice)."""
    entries = entries or {}
    return [
        (slug, e[1], e[1], e[2], e[3], e[4], {"slug": slug})
        for slug, e in sorted(entries.items()) if slug in used_slugs
    ]
