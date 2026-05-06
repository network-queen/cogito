from __future__ import annotations

import io
import unittest

from cogito.chat import (
    CogitoCompleter,
    command_matches,
    completion_options,
    get_instruction_hint,
    prompt_completions,
    show_command_matches,
    show_help,
)
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
        self.assertIn("gpt-5.5", completion_options(conn, "/persona add boo gp", "gp", commands))

    def test_prompt_completions_include_metadata(self):
        conn = connect(":memory:")
        ensure_db(conn)
        add_persona(conn, name="architect", agent="codex", model="gpt-5.5", description="Architect")

        self.assertTrue(any(value.startswith("/persona") for value, _, _, _ in prompt_completions(conn, "/per")))
        self.assertIn(("@architect ", "@architect", "codex", -3), prompt_completions(conn, "@ar"))

    def test_prompt_command_completion_inserts_command_not_usage(self):
        conn = connect(":memory:")
        ensure_db(conn)

        completions = prompt_completions(conn, "/mo")

        self.assertIn(("/model ", "/model", "[MODEL] - show or change active model", -3), completions)
        self.assertNotIn(
            ("/model gpt-5.5", "/model gpt-5.5", "show or change active model", -3),
            completions,
        )

    def test_prompt_argument_completions_and_hints(self):
        conn = connect(":memory:")
        ensure_db(conn)

        self.assertIn(("gpt-5.5 ", "gpt-5.5", "model", 0), prompt_completions(conn, "/model "))
        self.assertIn(("gpt-5.5 ", "gpt-5.5", "model; adapter inferred", -2), prompt_completions(conn, "/persona add boo gp"))
        self.assertEqual(get_instruction_hint("/persona add"), "next: NAME MODEL DESCRIPTION")
        self.assertEqual(get_instruction_hint("/persona add boo"), "next: MODEL DESCRIPTION")
        self.assertEqual(get_instruction_hint("/persona add boo gpt-5.5"), "next: DESCRIPTION")

    def test_command_matches_filter_by_substring(self):
        matches = command_matches("/per")

        commands = [command for command, _ in matches]
        self.assertIn("/persona add NAME MODEL DESCRIPTION", commands)
        self.assertNotIn("/tool local|codex|claude|opencode", commands)

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

    def test_prompt_toolkit_completer_supports_async_api(self):
        conn = connect(":memory:")
        ensure_db(conn)

        self.assertTrue(hasattr(CogitoCompleter(conn), "get_completions_async"))


if __name__ == "__main__":
    unittest.main()
