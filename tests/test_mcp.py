from __future__ import annotations

import unittest

from cogito.db import connect
from cogito.mcp_server import handle_request
from cogito.memory import ensure_db


class McpTests(unittest.TestCase):
    def test_initialize_and_list_tools(self):
        conn = connect(":memory:")
        ensure_db(conn)

        initialized = handle_request(conn, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        tools = handle_request(conn, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "cogito")
        tool_names = {tool["name"] for tool in tools["result"]["tools"]}
        self.assertIn("store_memory", tool_names)
        self.assertIn("get_context_pack", tool_names)

    def test_store_and_context_pack_tool_call(self):
        conn = connect(":memory:")
        ensure_db(conn)

        store = handle_request(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "store_memory",
                    "arguments": {
                        "text": "User prefers concise technical answers.",
                        "type": "preference",
                        "sensitivity": "professional",
                        "contexts": ["coding"],
                    },
                },
            },
        )
        pack = handle_request(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "query": "technical answers",
                        "lens": "coding",
                        "max_sensitivity": "professional",
                    },
                },
            },
        )

        self.assertIn("technical answers", store["result"]["content"][0]["text"])
        self.assertIn("Relevant user context", pack["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()

