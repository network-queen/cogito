from __future__ import annotations

import unittest

from cogito.agent_bridge import build_enriched_prompt


class AgentBridgeTests(unittest.TestCase):
    def test_build_enriched_prompt_contains_context_and_request(self):
        prompt = build_enriched_prompt("Lens: coding\n- User likes terse output.", "Fix tests")

        self.assertIn("Lens: coding", prompt)
        self.assertIn("Fix tests", prompt)
        self.assertIn("Respect access policy", prompt)


if __name__ == "__main__":
    unittest.main()

