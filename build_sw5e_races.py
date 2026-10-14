#!/usr/bin/env python3
# Vertical slice: build an ODM open5e-schema `races` table (+ `documents`)
# from sw5e-foundry/sw5e-module's YAML source packs.
#
# Target schema (from ODM data/content/open5e.sqlite):
#   races(slug PK, name, document_slug, is_subrace, parent_slug, data_json)
#   documents(slug PK, name, title, license, author, url, data_json)
#
# data_json mirrors ODM's open5e normalize.py shape for races:
#   name, slug, desc, asi_desc, asi[{attributes,value}], age, alignment,
#   size, size_raw, speed{walk}, speed_desc, languages, vision, traits,
#   document__slug, document__title, document__license_url, document__url
#
# Source layout (sw5e-module/packs/_source/species/):
#   <slug>.yml                      -> race entry (type: race)
#   species-features/<slug>/<t>.yml -> trait feats (type: feat, species subtype)
#                                      _id = the UUID the race's advancement references

import glob
import os
import re
import sqlite3
import sys

import yaml

SRC = os.path.expanduser("~/projects/sw5e-module/packs/_source/species")
OUT = os.path.expanduser("~/projects/sw5e-odm-pack/sw5e.sqlite")

BOILERPLATE = {"ability-score-increase", "age", "alignment", "languages",
               "size", "speed", "darkvision", "blindsight", "special-senses"}

# SW5e source.custom values -> document metadata (url points at sw5e content)
DOCS = {
    "PHB": ("sw5e-phb", "SW5e Player's Handbook", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/"),
    "EC":  ("sw5e-ec", "SW5e Expanded Content", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/content/expandedcontent"),
    "UAC": ("sw5e-uac", "SW5e Unsplash a Collab", "CC-BY-NC-SA-4.0",
            "SW5e team", "https://sw5e.com/"),
}
DOC_DEFAULT = ("sw5e-module", "SW5e Foundry Module", "CC-BY-NC-SA-4.0",
               "sw5e-foundry", "https://github.com/sw5e-foundry/sw5e-module")

ABILITIES = ["Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma"]
SIZES = ["Small", "Medium", "Large", "Huge", "Gargantuan"]


def html_to_md(html: str) -> str:
    """Naive Foundry HTML -> markdown-ish prose (enough for the slice)."""
    s = html
    s = re.sub(r"<h(\d)[^>]*>(.*?)</h\1>", r"\n## \2\n", s, flags=re.S)
    s = re.sub(r"<strong>(.*?)</strong>", r"**\1**", s, flags=re.S)
    s = re.sub(r"<em>(.*?)</em>", r"*\1*", s, flags=re.S)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n\n", s, flags=re.S)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


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
    for m in re.finditer(
        r"(" + "|".join(ABILITIES) + r")\s+score(?:\s+and\s+your\s+"
        + "(" + "|".join(ABILITIES) + r")\s+score)?\s+(?:increases|increase|is raised|improves)"
        + r"(?:\s+by)?\s*(\d+)|(?:by|at)\s+(\d+)\s+(?:points)?",
        text, re.I,
    ):
        pass  # complex alternations are brittle; use a simpler scan below
    # simpler: find every "<Ability> ... <num>" pairing in the sentence
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
    feats_dir = os.path.join(SRC, "species-features", slug)
    data = {
        "name": d["name"], "slug": slug, "desc": html_to_md(
            (sys_.get("description", {}) or {}).get("value", "")),
    }
    asi_text = None
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
                asi_text = text
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
    custom = ((sys_.get("source", {}) or {}).get("custom") or "").strip()
    doc = DOCS.get(custom, DOC_DEFAULT)
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


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.yml")))
    races = [load_race(f) for f in files]
    used_docs = sorted({r["document_slug"] for r in races})
    if os.path.exists(OUT):
        os.remove(OUT)
    con = sqlite3.connect(OUT)
    con.executescript("""
CREATE TABLE documents (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, title TEXT NOT NULL,
  license TEXT NOT NULL, author TEXT NOT NULL, url TEXT NOT NULL,
  data_json TEXT NOT NULL);
CREATE TABLE races (
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, document_slug TEXT NOT NULL,
  is_subrace INTEGER NOT NULL, parent_slug TEXT NOT NULL, data_json TEXT NOT NULL);
""")
    import json
    for spec in sorted(set(DOCS.values()) | {DOC_DEFAULT}, key=lambda t: t[0]):
        if spec[0] not in used_docs:
            continue
        con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
                    (spec[0], spec[1], spec[1], spec[2], spec[3], spec[4],
                     json.dumps({"slug": spec[0]})))
    for r in races:
        con.execute("INSERT INTO races VALUES (?,?,?,?,?,?)",
                    (r["slug"], r["name"], r["document_slug"], r["is_subrace"],
                     r["parent_slug"], json.dumps(r["data_json"])))
    con.commit()
    # report
    asi = sum(1 for r in races if r["data_json"]["asi"])
    sizes = sum(1 for r in races if r["data_json"].get("size_raw"))
    traits = sum(1 for r in races if r["data_json"]["traits"])
    print(f"races: {len(races)} | with asi: {asi} | with size: {sizes} | with traits: {traits}")
    print("documents:", {d: sum(1 for r in races if r['document_slug'] == d) for d in used_docs})
    missing_speed = [r["slug"] for r in races if not r["data_json"]["speed"].get("walk")]
    print("no walk speed:", len(missing_speed), missing_speed[:8])
    con.close()


if __name__ == "__main__":
    sys.exit(main())
