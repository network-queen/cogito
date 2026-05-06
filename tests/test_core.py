from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.memory import add_memory, context_pack, ensure_db, search_memories
from cogito.policy import ContextRequest


class CoreTests(unittest.TestCase):
    def test_context_pack_filters_by_lens_and_sensitivity(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_memory(
            conn,
            text="User is building Cogito Ergo Sum.",
            memory_type="goal",
            sensitivity="professional",
            contexts=["coding", "professional"],
        )
        add_memory(
            conn,
            text="User has an intimate private memory.",
            memory_type="fact",
            sensitivity="intimate",
            contexts=["intimate"],
        )

        pack = context_pack(
            conn,
            query="Cogito architecture",
            request=ContextRequest(lens="coding", max_sensitivity="professional"),
        )

        self.assertIn("Cogito Ergo Sum", pack["context"])
        self.assertNotIn("intimate private", pack["context"])
        self.assertTrue(pack["receipt"]["memory_ids"])

    def test_search_returns_only_active_memories(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_memory(
            conn,
            text="User prefers terse engineering answers.",
            memory_type="preference",
            sensitivity="professional",
            contexts=["coding"],
        )

        results = search_memories(
            conn,
            query="engineering answers",
            request=ContextRequest(lens="coding", max_sensitivity="professional"),
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "preference")

    def test_existing_db_without_embedding_columns_migrates_before_indexing(self):
        conn = connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE memories (
              id TEXT PRIMARY KEY,
              text TEXT NOT NULL,
              type TEXT NOT NULL,
              sensitivity TEXT NOT NULL,
              contexts TEXT NOT NULL,
              confidence REAL NOT NULL,
              source_event_id TEXT,
              state TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              expires_at TEXT
            );
            """
        )

        ensure_db(conn)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(memories)").fetchall()}
        self.assertIn("embedding", columns)
        self.assertIn("embedding_model", columns)
        self.assertIn("idx_memories_embedding_model", indexes)


if __name__ == "__main__":
    unittest.main()
