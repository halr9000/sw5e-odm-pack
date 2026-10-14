#!/usr/bin/env python3
"""Build the `races` table (+ `documents`) of the SW5e open5e-schema pack.

Uses the shared sw5e_lib (normalizers + full 10-table SCHEMA_SQL via
write_pack). Only `races` and `documents` are filled here; the other eight
tables are created empty by the shared schema and filled by build_sw5e_pack.py.
"""

import glob
import os
import sys

import yaml

from sw5e_lib import (DOCS, DOC_DEFAULT, SRC_ROOT, documents_rows_from,
                      load_race, write_pack)

OUT = os.path.expanduser("~/projects/sw5e-odm-pack/sw5e.sqlite")


def main():
    files = sorted(glob.glob(os.path.join(SRC_ROOT, "species", "*.yml")))
    races = [load_race(f) for f in files]
    used_docs = {r["document_slug"] for r in races}
    by_slug = {spec[0]: spec for spec in sorted(set(DOCS.values()) | {DOC_DEFAULT}, key=lambda t: t[0])}
    docs = documents_rows_from(used_docs, by_slug)
    write_pack(OUT, {
        "documents": docs,
        "races": [(r["slug"], r["name"], r["document_slug"], r["is_subrace"],
                   r["parent_slug"], r["data_json"]) for r in races],
    })
    # report
    asi = sum(1 for r in races if r["data_json"]["asi"])
    sizes = sum(1 for r in races if r["data_json"].get("size_raw"))
    traits = sum(1 for r in races if r["data_json"]["traits"])
    print(f"races: {len(races)} | with asi: {asi} | with size: {sizes} | with traits: {traits}")
    print("documents:", {d: sum(1 for r in races if r['document_slug'] == d) for d in sorted(used_docs)})
    missing_speed = [r["slug"] for r in races if not r["data_json"]["speed"].get("walk")]
    print("no walk speed:", len(missing_speed), missing_speed[:8])


if __name__ == "__main__":
    sys.exit(main())
