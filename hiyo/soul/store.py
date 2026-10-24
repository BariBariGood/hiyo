"""Small local SQLite memory. Consent is enforced by SoulEngine, not this storage primitive.

Records are user-scoped. This local prototype uses OS file permissions, not encryption.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class SoulStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create sets permissions before any data is written.
        import os
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        con = sqlite3.connect(self.path, timeout=5)
        try:
            con.execute("PRAGMA secure_delete=ON")
            con.execute("CREATE TABLE IF NOT EXISTS records (user_id TEXT, kind TEXT, key TEXT, payload TEXT, PRIMARY KEY(user_id, kind, key))")
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def write(con, user_id: str, kind: str, key: str, payload: dict, *, once=False):
        verb = "INSERT OR IGNORE" if once else "INSERT OR REPLACE"
        cursor = con.execute(f"{verb} INTO records VALUES (?, ?, ?, ?)",
                             (user_id, kind, key, json.dumps(payload, ensure_ascii=False)))
        return cursor.rowcount == 1

    @staticmethod
    def rows(con, user_id: str, kind: str) -> list[dict]:
        return [json.loads(row[0]) for row in con.execute(
            "SELECT payload FROM records WHERE user_id=? AND kind=? ORDER BY key", (user_id, kind))]

    def read(self, user_id: str, kind: str) -> list[dict]:
        if not self.path.exists():
            return []
        with self.transaction() as con:
            return self.rows(con, user_id, kind)

    def export(self, user_id: str) -> dict:
        if not self.path.exists():
            return {}
        with self.transaction() as con:
            kinds = [r[0] for r in con.execute("SELECT DISTINCT kind FROM records WHERE user_id=?", (user_id,))]
            return {kind: self.rows(con, user_id, kind) for kind in kinds if kind != "contact"}

    def forget(self, user_id: str) -> None:
        if self.path.exists():
            with self.transaction() as con:
                # Minimal contact receipts remain to prevent opt-out/reset bypass of contact caps.
                con.execute("DELETE FROM records WHERE user_id=? AND kind!='contact'", (user_id,))

    def prune(self, user_id: str, before: str) -> None:
        if not self.path.exists():
            return
        from datetime import datetime
        cutoff = datetime.fromisoformat(before)
        with self.transaction() as con:
            records = list(con.execute("SELECT kind,key,payload FROM records WHERE user_id=? AND kind!='profile'", (user_id,)))
            for kind, key, text in records:
                value = json.loads(text)
                at = value.get("at") or value.get("observed_at") or value.get("created_at")
                if at and datetime.fromisoformat(at) < cutoff:
                    con.execute("DELETE FROM records WHERE user_id=? AND kind=? AND key=?", (user_id, kind, key))
