#!/usr/bin/env python3
"""Build the SW5e content pack: all open5e-schema tables into sw5e.sqlite.

Entry point for the table builders; the races pass reuses sw5e_lib.load_race.
Tables not yet implemented are created empty by the shared schema.
"""

import glob
import json
import os
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


def main():
    races, race_rows = build_races()
    used_docs = {r["document_slug"] for r in races}
    cond_rows = build_conditions()
    used_docs.update(row[2] for row in cond_rows)
    doc_specs = {spec[0]: spec for spec in
                 sorted(set(DOCS.values()) | {DOC_DEFAULT}, key=lambda t: t[0])}
    docs = documents_rows_from(used_docs, doc_specs)
    write_pack(OUT, {
        "documents": docs,
        "races": race_rows,
        "conditions": cond_rows,
    })
    print(f"races: {len(race_rows)} | conditions: {len(cond_rows)}")
    print("documents:", sorted(used_docs))


if __name__ == "__main__":
    sys.exit(main())
