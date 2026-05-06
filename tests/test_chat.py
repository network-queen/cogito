from __future__ import annotations

import io
import unittest

from cogito.chat import run_chat
from cogito.db import connect
from cogito.memory import ensure_db, list_memories
from cogito.settings import set_embedding_model, set_memory_model


class ChatTests(unittest.TestCase):
    def test_chat_switches_tools_and_stores_memory_without_execution(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        input_stream = io.StringIO("I prefer concise engineering answers\n/tool claude\nexplain tradeoffs\n/exit\n")
        output_stream = io.StringIO()

        run_chat(conn, execute=False, memory_mode="sync", input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        memories = list_memories(conn)
        self.assertNotIn("Tool: claude", output)
        self.assertNotIn("Cogito session closed.", output)
        self.assertNotIn("[cogito] stored", output)
        self.assertTrue(any("prefer concise" in memory["text"] for memory in memories))

    def test_verbose_chat_shows_metadata(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        input_stream = io.StringIO("/tool claude\n/exit\n")
        output_stream = io.StringIO()

        run_chat(conn, execute=False, verbose=True, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        self.assertIn("Cogito chat.", output)
        self.assertIn("Tool: claude", output)
        self.assertIn("Cogito session closed.", output)


if __name__ == "__main__":
    unittest.main()
