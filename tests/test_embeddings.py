from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from cogito.db import connect
from cogito.memory import add_memory, ensure_db, search_memories
from cogito.policy import ContextRequest


class EmbeddingSearchTests(unittest.TestCase):
    def test_embedding_search_ranks_relevant_memory(self):
        conn = connect(":memory:")
        ensure_db(conn)
        first = add_memory(
            conn,
            text="User is Klymenko Ruslan, software engineer in Zurich.",
            memory_type="fact",
            sensitivity="professional",
            contexts=["professional", "coding"],
        )
        second = add_memory(
            conn,
            text="User prefers direct engineering feedback.",
            memory_type="preference",
            sensitivity="professional",
            contexts=["coding"],
        )
        conn.execute(
            "UPDATE memories SET embedding = ?, embedding_model = ? WHERE id = ?",
            (json.dumps([1.0, 0.0]), "test-embed", first["id"]),
        )
        conn.execute(
            "UPDATE memories SET embedding = ?, embedding_model = ? WHERE id = ?",
            (json.dumps([0.0, 1.0]), "test-embed", second["id"]),
        )
        conn.commit()

        with patch("cogito.memory.embed_query", return_value=([1.0, 0.0], "test-embed")):
            results = search_memories(
                conn,
                query="write intro for me",
                request=ContextRequest(lens="professional", max_sensitivity="professional"),
            )

        self.assertEqual(results[0]["id"], first["id"])
        self.assertEqual(results[0]["score_source"], "embedding")


if __name__ == "__main__":
    unittest.main()

