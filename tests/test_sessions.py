from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.memory import add_memory, ensure_db
from cogito.settings import set_memory_model
from cogito.sessions import ask_session, create_session, get_turns, set_session_agent


class SessionTests(unittest.TestCase):
    def test_session_prompt_can_switch_agents_without_execution(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
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
        )
        set_session_agent(conn, session_id=session["id"], agent="claude")
        second = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="explain tradeoffs",
            execute=False,
        )

        self.assertEqual(first["agent"], "codex")
        self.assertEqual(second["agent"], "claude")
        self.assertIn("Cogito session:", second["prompt"])
        self.assertIn("User is building Cogito Ergo Sum.", second["prompt"])
        self.assertGreaterEqual(len(get_turns(conn, session_id=session["id"])), 2)


if __name__ == "__main__":
    unittest.main()
