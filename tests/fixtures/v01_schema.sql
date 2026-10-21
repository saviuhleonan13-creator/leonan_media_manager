-- V0.1 schema from commit d8804db, no operator data.

PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS episodes (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS takes (
 id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id),
 number INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'investigating'
 CHECK(status IN ('investigating','approved','discarded')),
 UNIQUE(episode_id, number)
);
CREATE TABLE IF NOT EXISTS assets (
 id INTEGER PRIMARY KEY, sha TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 original_name TEXT NOT NULL, extension TEXT NOT NULL, dhash TEXT,
 width INTEGER NOT NULL, height INTEGER NOT NULL, duration REAL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bindings (
 id INTEGER PRIMARY KEY, take_id INTEGER NOT NULL REFERENCES takes(id),
 asset_id INTEGER NOT NULL REFERENCES assets(id), kind TEXT NOT NULL,
 version TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '', original_name TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS active_binding ON bindings(take_id, kind) WHERE active=1;
