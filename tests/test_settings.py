from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.memory import ensure_db
from cogito.settings import get_memory_model, set_memory_model


class SettingsTests(unittest.TestCase):
    def test_memory_model_defaults_and_normalizes(self):
        conn = connect(":memory:")
        ensure_db(conn)

        self.assertEqual(get_memory_model(conn), "ollama:qwen3:0.6b")
        self.assertEqual(set_memory_model(conn, "qwen3:1.7b"), "ollama:qwen3:1.7b")
        self.assertEqual(get_memory_model(conn), "ollama:qwen3:1.7b")
        self.assertEqual(set_memory_model(conn, "heuristic"), "heuristic")


if __name__ == "__main__":
    unittest.main()
