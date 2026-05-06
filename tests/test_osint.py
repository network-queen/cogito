from __future__ import annotations

import unittest
from unittest.mock import patch

from cogito.db import connect
from cogito.memory import ensure_db, list_memories
from cogito.osint import query_from_url, research_target
from cogito.persona_knowledge import list_persona_knowledge
from cogito.personas import add_persona_for_model
from cogito.settings import set_embedding_model


class OsintTests(unittest.TestCase):
    def test_query_from_url_derives_person_name(self):
        query = query_from_url("https://www.linkedin.com/in/ruslan-klymenko-927a6b67/")

        self.assertIn("ruslan", query)
        self.assertIn("klymenko", query)

    def test_research_me_stores_public_memory(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")

        with patch("cogito.osint.collect_osint_documents") as collect:
            collect.return_value = [
                {
                    "url": "https://example.com/ruslan",
                    "text": "Ruslan Klymenko is a software engineer in Zurich with AI agent interests.",
                }
            ]
            created = research_target(conn, target="@me", source="Ruslan Klymenko")

        memories = list_memories(conn)
        self.assertEqual(len(created), 1)
        self.assertEqual(memories[0]["type"], "public_research")
        self.assertIn("software engineer in Zurich", memories[0]["text"])

    def test_research_persona_stores_persona_knowledge(self):
        conn = connect(":memory:")
        ensure_db(conn)
        set_embedding_model(conn, "off")
        add_persona_for_model(conn, name="architect", model="gpt-5.5", description="Architect.")

        with patch("cogito.osint.collect_osint_documents") as collect:
            collect.return_value = [
                {
                    "url": "https://example.com/architecture",
                    "text": "The architect persona prefers evolutionary architecture and pragmatic design.",
                }
            ]
            created = research_target(conn, target="@architect", source="architecture")

        knowledge = list_persona_knowledge(conn, persona_name="architect")
        self.assertEqual(len(created), 1)
        self.assertEqual(knowledge[0]["type"], "public_research")
        self.assertIn("evolutionary architecture", knowledge[0]["text"])


if __name__ == "__main__":
    unittest.main()
