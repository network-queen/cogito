from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from cogito.chat import color, run_chat
from cogito.db import connect
from cogito.memory import ensure_db, list_memories
from cogito.sessions import create_session
from cogito.settings import set_embedding_model, set_memory_model


class ChatTests(unittest.TestCase):
    def test_chat_switches_models_and_stores_memory_without_execution(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        input_stream = io.StringIO("I prefer concise engineering answers\n/model sonnet\nexplain tradeoffs\n/exit\n")
        output_stream = io.StringIO()

        run_chat(conn, execute=False, memory_mode="sync", input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        memories = list_memories(conn)
        self.assertNotIn("Model: sonnet", output)
        self.assertNotIn("Cogito session closed.", output)
        self.assertNotIn("[cogito] stored", output)
        self.assertTrue(any("prefer concise" in memory["text"] for memory in memories))

    def test_verbose_chat_shows_metadata(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        input_stream = io.StringIO("/model sonnet\n/exit\n")
        output_stream = io.StringIO()

        run_chat(conn, execute=False, verbose=True, input_stream=input_stream, output_stream=output_stream)

        output = output_stream.getvalue()
        self.assertIn("Cogito chat.", output)
        self.assertIn("Model: sonnet", output)
        self.assertIn("Cogito session closed.", output)

    def test_quiet_chat_colors_agent_output(self):
        conn = connect(":memory:")
        ensure_db(conn)
        input_stream = io.StringIO("hello\n/exit\n")
        output_stream = io.StringIO()
        fake_result = {
            "session": {"id": "ses_test", "active_agent": "local"},
            "prompt": "",
            "output": "answer",
            "agent": "local",
            "context_pack": {},
            "stored_memories": [],
            "exit_code": 0,
        }

        with patch("cogito.chat.ask_session", return_value=fake_result) as ask:
            run_chat(conn, input_stream=input_stream, output_stream=output_stream)

        self.assertIn(color("answer", "green"), output_stream.getvalue())
        self.assertFalse(ask.call_args.kwargs["echo_output"])

    def test_chat_resumes_latest_matching_session(self):
        conn = connect(":memory:")
        ensure_db(conn)
        existing = create_session(conn, title="Cogito chat", agent="local")
        input_stream = io.StringIO("/session\n/exit\n")
        output_stream = io.StringIO()

        run_chat(conn, execute=False, verbose=True, input_stream=input_stream, output_stream=output_stream)

        self.assertIn(existing["id"], output_stream.getvalue())

    def test_research_command_routes_to_osint(self):
        conn = connect(":memory:")
        ensure_db(conn)
        input_stream = io.StringIO("/research @me https://example.com/me\n/exit\n")
        output_stream = io.StringIO()

        receipt = {
            "target": "@me",
            "query": "https://example.com/me",
            "seed_urls": ["https://example.com/me"],
            "discovered_urls": ["https://example.com/me"],
            "scanned_sources": [{"url": "https://example.com/me", "chars": 120, "preview": "Example"}],
            "failed_sources": [],
            "saved_chunks": [
                {
                    "store": "user_memory",
                    "id": "mem_test",
                    "source_url": "https://example.com/me",
                    "preview": "Example saved chunk",
                }
            ],
        }

        with patch("cogito.chat.research_target_with_receipt", return_value=receipt) as research:
            run_chat(conn, execute=False, input_stream=input_stream, output_stream=output_stream)

        research.assert_called_once_with(conn, target="@me", source="https://example.com/me")
        self.assertIn("Scanned sources:", output_stream.getvalue())
        self.assertIn("Saved chunks: 1", output_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
