from __future__ import annotations

import unittest
from unittest.mock import patch

from cogito.db import connect
from cogito.memory import add_memory, ensure_db, list_memories
from cogito.persona_knowledge import add_persona_knowledge, list_persona_knowledge
from cogito.personas import add_persona_for_model
from cogito.settings import set_embedding_model
from cogito.web_ui import approve_research, build_state, create_persona, preview_research


class WebUiTests(unittest.TestCase):
    def test_build_state_lists_user_and_persona_facts(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        add_memory(conn, text="User is a software engineer in Zurich.")
        add_persona_for_model(conn, name="aristotle", model="gpt-5.5", description="Philosopher.")
        add_persona_knowledge(conn, persona_name="aristotle", text="Aristotle wrote on virtue ethics.")

        state = build_state(conn)

        self.assertEqual(state["memories"][0]["text"], "User is a software engineer in Zurich.")
        self.assertEqual(state["personas"][0]["name"], "aristotle")
        self.assertEqual(state["personas"][0]["knowledge_count"], 1)
        self.assertNotIn("embedding", state["memories"][0])

    def test_create_persona_from_description(self):
        conn = connect(":memory:")
        ensure_db(conn)

        result = create_persona(
            conn,
            {"name": "architect", "model": "gpt-5.5", "description": "Pragmatic architect."},
        )

        self.assertEqual(result["persona"]["name"], "architect")
        self.assertEqual(result["persona"]["model"], "gpt-5.5")

    def test_preview_and_approve_research_saves_only_selected_sources(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        pending = {}

        with patch("cogito.web_ui.collect_osint_documents", return_value=fake_collection()):
            preview = preview_research({"target": "@me", "source": "Ruslan Klymenko"}, pending)
        receipt = approve_research(
            conn,
            {"token": preview["token"], "selected_urls": ["https://example.com/ruslan"]},
            pending,
        )

        memories = list_memories(conn)
        self.assertEqual(receipt["saved_chunks"][0]["store"], "user_memory")
        self.assertIn("software engineer in Zurich", memories[0]["text"])

    def test_delete_persona_knowledge_hides_rejected_fact(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        add_persona_for_model(conn, name="aristotle", model="gpt-5.5", description="Philosopher.")
        item = add_persona_knowledge(conn, persona_name="aristotle", text="Wrong fact.")

        from cogito.persona_knowledge import delete_persona_knowledge

        delete_persona_knowledge(conn, item["id"])

        self.assertEqual(list_persona_knowledge(conn, persona_name="aristotle"), [])


def fake_collection():
    return {
        "query": "Ruslan Klymenko",
        "seed_urls": [],
        "discovered_urls": ["https://example.com/ruslan", "https://example.com/wrong"],
        "scanned_sources": [
            {"url": "https://example.com/ruslan", "chars": 78, "preview": "Ruslan Klymenko"},
            {"url": "https://example.com/wrong", "chars": 55, "preview": "Wrong person"},
        ],
        "failed_sources": [],
        "documents": [
            {
                "url": "https://example.com/ruslan",
                "text": "Ruslan Klymenko is a software engineer in Zurich with AI agent interests.",
            },
            {"url": "https://example.com/wrong", "text": "Wrong person and unrelated content."},
        ],
    }


if __name__ == "__main__":
    unittest.main()
