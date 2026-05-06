from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import patch

from cogito.chat import handle_persona_command
from cogito.db import connect
from cogito.memory import add_memory, ensure_db
from cogito.persona_knowledge import (
    add_persona_knowledge,
    list_persona_knowledge,
    search_persona_knowledge,
)
from cogito.personas import add_persona_for_model, get_persona, maybe_extract_persona_call
from cogito.sessions import ask_session, create_session
from cogito.settings import set_embedding_model, set_memory_model


class PersonaKnowledgeTests(unittest.TestCase):
    def test_persona_knowledge_is_stored_and_searched(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        add_persona_for_model(
            conn,
            name="descartes",
            model="gpt-5.5",
            description="Rationalist philosopher.",
        )

        item = add_persona_knowledge(
            conn,
            persona_name="descartes",
            text="Descartes used methodological doubt as a route to certainty.",
            knowledge_type="philosophy",
        )
        results = search_persona_knowledge(conn, persona_name="descartes", query="methodological doubt")

        self.assertEqual(item["type"], "philosophy")
        self.assertEqual(len(list_persona_knowledge(conn, persona_name="descartes")), 1)
        self.assertEqual(results[0]["id"], item["id"])

    def test_session_prompt_includes_persona_knowledge(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        add_persona_for_model(
            conn,
            name="descartes",
            model="gpt-5.5",
            description="Rationalist philosopher.",
        )
        add_persona_knowledge(
            conn,
            persona_name="descartes",
            text="Descartes treats doubt as a method for reaching certainty.",
        )
        session = create_session(conn, title="Philosophy", agent="local")

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt="How should I think about doubt?",
            execute=False,
            memory_mode="off",
            persona=get_persona(conn, "descartes"),
        )

        self.assertIn("Persona knowledge:", result["prompt"])
        self.assertIn("reaching certainty", result["prompt"])

    def test_me_persona_uses_user_memory_not_persona_knowledge(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_memory_model(conn, "heuristic")
        set_embedding_model(conn, "off")
        add_memory(
            conn,
            text="User is a software engineer in Zurich.",
            memory_type="fact",
            sensitivity="professional",
            contexts=["coding", "professional"],
        )
        session = create_session(conn, title="Self", agent="local")

        persona, routed = maybe_extract_persona_call(conn, "@me what software engineer Zurich context matters?")
        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt=routed,
            execute=False,
            memory_mode="off",
            persona=persona,
        )

        self.assertEqual(persona["name"], "me")
        self.assertTrue(persona["virtual"])
        self.assertIn("self-persona", result["prompt"])
        self.assertIn("software engineer in Zurich", result["prompt"])
        self.assertNotIn("Persona knowledge:", result["prompt"])

    def test_persona_add_without_description_auto_researches(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        session = create_session(conn, title="Persona", agent="local")

        with patch("cogito.chat.research_persona_from_wikipedia") as research:
            research.return_value = [{"id": "pkg_test"}]
            output = StringIO()
            handle_persona_command(
                conn,
                ["/persona", "add", "aristotle", "gpt-5.5"],
                session=session,
                active_persona=None,
                output_stream=output,
                verbose=False,
            )

        persona = get_persona(conn, "aristotle")
        research.assert_called_once_with(conn, persona_name="aristotle", subject="aristotle")
        self.assertEqual(persona["model"], "gpt-5.5")
        self.assertIn("researched as aristotle", persona["description"])
        self.assertIn("researched chunks", output.getvalue())


if __name__ == "__main__":
    unittest.main()
