from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.memory import ensure_db
from cogito.personas import add_persona_for_model, get_persona, maybe_extract_persona_call


class PersonaTests(unittest.TestCase):
    def test_add_and_route_persona_call(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_persona_for_model(
            conn,
            name="architect",
            model="gpt-5.5",
            description="Senior architect.",
        )

        persona = get_persona(conn, "architect")
        called, text = maybe_extract_persona_call(conn, "@architect review this")

        self.assertEqual(persona["agent"], "codex")
        self.assertEqual(called["model"], "gpt-5.5")
        self.assertEqual(text, "review this")


if __name__ == "__main__":
    unittest.main()
