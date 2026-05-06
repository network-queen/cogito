from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.memory import add_memory, ensure_db
from cogito.settings import set_embedding_model, set_memory_model
from cogito.sessions import ask_session, create_session, get_turns, latest_session, set_session_agent


class SessionTests(unittest.TestCase):
    def test_session_prompt_can_switch_agents_without_execution(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        add_memory(
            conn,
            text="User is building Cogito Ergo Sum.",
            memory_type="goal",
            sensitivity="professional",
            contexts=["coding"],
        )
        session = create_session(conn, title="Build Cogito", agent="codex")

        first = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="review architecture",
            agent="codex",
            execute=False,
            memory_mode="sync",
        )
        set_session_agent(conn, session_id=session["id"], agent="claude")
        second = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="explain tradeoffs",
            execute=False,
            memory_mode="sync",
        )

        self.assertEqual(first["agent"], "codex")
        self.assertEqual(second["agent"], "claude")
        self.assertIn("Cogito session:", second["prompt"])
        self.assertIn("User is building Cogito Ergo Sum.", second["prompt"])
        self.assertGreaterEqual(len(get_turns(conn, session_id=session["id"])), 2)

    def test_latest_session_can_resume_same_chat_context(self):
        conn = connect(":memory:")
        ensure_db(conn)
        session = create_session(
            conn,
            title="Cogito chat",
            agent="local",
            cwd="/tmp/cogito",
            lens="coding",
            max_sensitivity="professional",
        )

        resumed = latest_session(
            conn,
            title="Cogito chat",
            cwd="/tmp/cogito",
            lens="coding",
            max_sensitivity="professional",
        )

        self.assertEqual(resumed["id"], session["id"])

    def test_persona_call_can_preserve_base_session_agent(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        session = create_session(conn, title="Cogito chat", agent="local")

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="who are you?",
            agent="codex",
            execute=False,
            memory_mode="off",
            update_active_agent=False,
        )

        self.assertEqual(result["agent"], "codex")
        self.assertEqual(result["session"]["active_agent"], "local")


if __name__ == "__main__":
    unittest.main()
