from __future__ import annotations

import unittest

from cogito.local_extractor import merge_memories


class LocalExtractorTests(unittest.TestCase):
    def test_merge_memories_keeps_fallback_without_duplicates(self):
        primary = [
            {
                "text": "User prefers concise answers.",
                "type": "preference",
                "sensitivity": "professional",
                "contexts": ["coding"],
                "confidence": 0.8,
            }
        ]
        fallback = [
            {
                "text": "User prefers concise answers.",
                "type": "preference",
                "sensitivity": "professional",
                "contexts": ["coding"],
                "confidence": 0.5,
            },
            {
                "text": "User works on Cogito.",
                "type": "fact",
                "sensitivity": "professional",
                "contexts": ["coding"],
                "confidence": 0.5,
            },
        ]

        merged = merge_memories(primary, fallback)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["text"], "User prefers concise answers.")


if __name__ == "__main__":
    unittest.main()

