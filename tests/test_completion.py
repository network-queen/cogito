from __future__ import annotations

import io
import unittest

from cogito.chat import command_matches, completion_options, prompt_completions, show_help, show_command_matches
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

    def test_prompt_completions_include_metadata(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_persona(conn, name="architect", agent="codex", model="gpt-5.5", description="Architect")

        self.assertTrue(any(value.startswith("/persona") for value, _, _ in prompt_completions(conn, "/per")))
        self.assertIn(("@architect ", "codex", -3), prompt_completions(conn, "@ar"))

    def test_command_matches_filter_by_substring(self):
        matches = command_matches("/per")

        commands = [command for command, _ in matches]
        self.assertIn("/persona add NAME AGENT MODEL DESCRIPTION", commands)
        self.assertNotIn("/tool codex|claude|opencode", commands)

    def test_command_match_output_prints_options(self):
        output = io.StringIO()

        show_command_matches(output, "/per")

        self.assertIn("/persona add", output.getvalue())
        self.assertNotIn("/verbose on|off", output.getvalue())

    def test_help_prints_full_reference(self):
        output = io.StringIO()

        show_help(output)

        self.assertIn("Commands", output.getvalue())
        self.assertIn("Examples", output.getvalue())


if __name__ == "__main__":
    unittest.main()
