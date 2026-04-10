import os
import tempfile
import unittest

from doc_ai_agent.letta_memory import LocalMemoryStore, LettaMemoryStore, normalize_memory_snapshot


class FakeBlock:
    def __init__(self, block_id: str, value: str):
        self.id = block_id
        self.value = value


class FakeBlocksResource:
    def __init__(self):
        self.blocks = {}

    def list(self, *, label=None, limit=None):
        if label and label in self.blocks:
            return [self.blocks[label]]
        return []

    def create(self, *, label, value, metadata=None, **_kwargs):
        block = FakeBlock(f"block-{len(self.blocks) + 1}", value)
        self.blocks[label] = block
        return block

    def update(self, block_id, *, value=None, **_kwargs):
        for block in self.blocks.values():
            if block.id == block_id:
                block.value = value
                return block
        raise AssertionError("unknown block id")


class FakeLettaClient:
    def __init__(self):
        self.blocks = FakeBlocksResource()


class MemoryStoreTests(unittest.TestCase):
    def test_local_memory_store_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            store = LocalMemoryStore(os.path.join(td, "agent-memory.json"))

            store.remember(
                "thread-1",
                {
                    "domain": "pest",
                    "region_name": "徐州市",
                    "window": {"window_type": "months", "window_value": 5},
                },
            )

            snapshot = store.load("thread-1")
            self.assertEqual(snapshot["domain"], "pest")
            self.assertEqual(snapshot["region_name"], "徐州市")
            self.assertEqual(snapshot["window"]["window_value"], 5)

    def test_letta_memory_store_round_trip(self):
        store = LettaMemoryStore(FakeLettaClient(), block_prefix="doc-cloud-test")

        store.remember(
            "thread-2",
            {
                "domain": "soil",
                "region_name": "淮安市",
                "forecast": {"horizon_days": 14},
            },
        )

        snapshot = store.load("thread-2")
        self.assertEqual(snapshot["domain"], "soil")
        self.assertEqual(snapshot["forecast"]["horizon_days"], 14)

    def test_normalize_memory_snapshot_upgrades_sparse_payload(self):
        snapshot = normalize_memory_snapshot({"domain": "pest", "region_name": "徐州市"})

        self.assertEqual(snapshot["memory_version"], 2)
        self.assertEqual(snapshot["domain"], "pest")
        self.assertEqual(snapshot["region_name"], "徐州市")
        self.assertEqual(snapshot["pending_user_question"], None)
        self.assertEqual(snapshot["user_preferences"], {})
        self.assertEqual(snapshot["last_verified_answer"], "")

    def test_local_memory_store_load_normalizes_legacy_payload(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "agent-memory.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"thread-legacy":{"domain":"soil","region_name":"淮安市"}}')

            store = LocalMemoryStore(path)
            snapshot = store.load("thread-legacy")

            self.assertEqual(snapshot["memory_version"], 2)
            self.assertEqual(snapshot["domain"], "soil")
            self.assertEqual(snapshot["region_name"], "淮安市")
            self.assertIn("conversation_state", snapshot)

    def test_letta_memory_store_normalizes_sparse_payload_on_load(self):
        client = FakeLettaClient()
        store = LettaMemoryStore(client, block_prefix="doc-cloud-test")
        client.blocks.create(label="doc-cloud-test:thread-legacy", value='{"domain":"pest","query_type":"pest_top"}')

        snapshot = store.load("thread-legacy")

        self.assertEqual(snapshot["memory_version"], 2)
        self.assertEqual(snapshot["domain"], "pest")
        self.assertEqual(snapshot["query_type"], "pest_top")
        self.assertEqual(snapshot["user_preferences"], {})


if __name__ == "__main__":
    unittest.main()
