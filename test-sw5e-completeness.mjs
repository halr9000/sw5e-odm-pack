// The anti-regression net for the SW5e content pack: every name in
// expected-sw5e.json is content an SW5e table expects to find in sw5e.sqlite,
// and the test asserts it resolves. The expectation lists are GENERATED from
// the source YAMLs by scripts/gen-expectations.py (one entry per source
// entity) — never hand-edit them to make a failure pass: fix the normalizer
// or regenerate.
//
// Modeled on open-dungeon-master's scripts/test-content-completeness.mjs
// (the has(table, name) pattern, node:assert/strict, `ok - <name>` output),
// with only the pack-based assertions: the 5e manifest/subclass sections are
// 5e-specific and do not apply to an SW5e-only pack.
//
// Run: cd ~/projects/sw5e-odm-pack && node test-sw5e-completeness.mjs
//      (CONTENT_DB_PATH overrides the pack path; default ./sw5e.sqlite)
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const ODM_ROOT = join(process.env.HOME || "", "projects", "open-dungeon-master");
const EXPECTATIONS = JSON.parse(readFileSync(new URL("./expected-sw5e.json", import.meta.url), "utf8"));

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

// Driver: reuse ODM's better-sqlite3-multiple-ciphers (same trick as ODM's
// pack scripts — createRequire against its package.json); fall back to a
// plain better-sqlite3 require if that is ever missing. Nothing is installed
// by this test.
function openDatabase(packPath) {
  const requireFromOdm = createRequire(join(ODM_ROOT, "package.json"));
  let Database;
  try {
    Database = requireFromOdm("better-sqlite3-multiple-ciphers");
  } catch {
    Database = createRequire(import.meta.url)("better-sqlite3");
  }
  return new Database(packPath, { readonly: true, fileMustExist: true });
}

const packPath = process.env.CONTENT_DB_PATH || join(process.cwd(), "sw5e.sqlite");
if (!existsSync(packPath)) {
  console.error(`content pack not found at ${packPath} — build it first (python3 build_sw5e_pack.py)`);
  process.exit(1);
}
const db = openDatabase(packPath);

const count = (table) => db.prepare(`SELECT COUNT(*) AS count FROM ${table}`).get().count;
const has = (table, name) =>
  db.prepare(`SELECT COUNT(*) AS count FROM ${table} WHERE name = ? COLLATE NOCASE`).get(name)
    .count > 0;

// One completeness test per table: the expected list IS the source walk, so
// a missing row (dropped by a normalizer crash-skip, a filename filter change,
// a source addition) fails the build with the exact name named.
for (const [table, key] of [
  ["races", "species"],
  ["conditions", "conditions"],
  ["feats", "feats"],
  ["backgrounds", "backgrounds"],
  ["classes", "classes"],
  ["archetypes", "archetypes"],
]) {
  test(`every expected ${table} entry is in the content pack (${EXPECTATIONS[key].length})`, () => {
    const missing = EXPECTATIONS[key].filter((name) => !has(table, name));
    assert.deepEqual(
      missing,
      [],
      `${missing.length} expected ${table} missing from the pack (first: ${missing.slice(0, 5).join(", ")})`,
    );
    // The generated list is one-per-source-entity: the row count must match
    // it exactly, so extra/duplicated rows are caught too.
    assert.equal(
      count(table),
      EXPECTATIONS[key].length,
      `${table} row count does not match the generated expectation list`,
    );
  });
}

test("every expected spell is in the content pack (465 Force/Tech powers)", () => {
  const missing = EXPECTATIONS.spells.filter((name) => !has("spells", name));
  assert.deepEqual(
    missing,
    [],
    `${missing.length} expected spells missing (first: ${missing.slice(0, 5).join(", ")})`,
  );
  assert.equal(count("spells"), EXPECTATIONS.spells.length);
});

test("every spell carries a Force or Tech school and a sane level", () => {
  const bad = db
    .prepare(
      `SELECT name FROM spells WHERE school NOT IN ('Force', 'Tech')
         OR level IS NULL OR level < 0 OR level > 9`,
    )
    .all()
    .map((r) => r.name);
  assert.deepEqual(bad, []);
});

test("every archetype points at a class that exists", () => {
  const orphans = db
    .prepare(
      `SELECT a.name FROM archetypes a
         LEFT JOIN classes c ON c.slug = a.class_slug WHERE c.slug IS NULL`,
    )
    .all()
    .map((r) => r.name);
  assert.deepEqual(orphans, [], "archetypes with a dangling class_slug");
});

test("every expected class has at least one archetype", () => {
  const empty = db
    .prepare(
      `SELECT c.name FROM classes c
         WHERE NOT EXISTS (SELECT 1 FROM archetypes a WHERE a.class_slug = c.slug)`,
    )
    .all()
    .map((r) => r.name);
  assert.deepEqual(empty, [], "classes with no archetypes");
});

test("monster spot-checks resolve across packs and CR brackets (30)", () => {
  const missing = EXPECTATIONS.monsters_spot_checks.filter((name) => !has("monsters", name));
  assert.deepEqual(
    missing,
    [],
    `${missing.length} monster spot-checks missing (first: ${missing.slice(0, 5).join(", ")})`,
  );
  // Full-coverage decision: the row count must match the source walk total.
  assert.equal(
    count("monsters"),
    EXPECTATIONS.monsters_total,
    `monsters row count (${count("monsters")}) != source npc statblocks (${EXPECTATIONS.monsters_total})`,
  );
});

test("monster statblocks carry core fields (CR/type sane across packs)", () => {
  const perPack = db
    .prepare(
      `SELECT document_slug, COUNT(*) AS total,
              SUM(CASE WHEN cr > 0 THEN 1 ELSE 0 END) AS with_cr,
              SUM(CASE WHEN type != '' THEN 1 ELSE 0 END) AS with_type
         FROM monsters GROUP BY document_slug`,
    )
    .all();
  assert.ok(perPack.length >= 2, "expected several monster source packs");
  const broken = perPack
    .filter((p) => p.with_cr === 0 || p.with_type === 0)
    .map((p) => `${p.document_slug}: all ${p.total} rows missing CR/type`);
  assert.deepEqual(broken, [], "packs whose statblocks normalize to nothing");
});

test("documents table covers every document_slug actually used", () => {
  const dangling = db
    .prepare(
      `SELECT DISTINCT f.document_slug FROM feats f
         LEFT JOIN documents d ON d.slug = f.document_slug
        WHERE d.slug IS NULL`,
    )
    .all()
    .map((r) => r.document_slug);
  assert.deepEqual(dangling, [], "document_slugs with no documents row");
});

db.close();
console.log(`\ntest-sw5e-completeness: ${passed} passed`);
