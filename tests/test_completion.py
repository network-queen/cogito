from __future__ import annotations

import io
import unittest

from cogito.chat import completion_options, show_command_palette
from cogito.db import connect
from cogito.memory import ensure_db
from cogito.personas import add_persona


class CompletionTests(unittest.TestCase):
    def test_slash_and_persona_completion_options(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_persona(conn, name="architect", agent="codex", model="gpt-5.5", description="Architect")

        commands = ["/persona use", "/verbose on"]

        self.assertIn("/verbose on", completion_options(conn, "/ver", "/ver", commands))
        self.assertIn("@architect ", completion_options(conn, "@ar", "@ar", commands))
        self.assertIn("architect", completion_options(conn, "/persona use ar", "ar", commands))

    def test_command_palette_prints_options(self):
        output = io.StringIO()

        show_command_palette(output)

        self.assertIn("/persona add", output.getvalue())
        self.assertIn("/verbose on|off", output.getvalue())


if __name__ == "__main__":
    unittest.main()
