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

    def test_normalize_memory_snapshot_adds_slot_metadata(self):
        snapshot = normalize_memory_snapshot(
            {
                "domain": "pest",
                "region_name": "徐州市",
                "window": {"window_type": "months", "window_value": 5},
                "conversation_state": {"last_intent": "data_query"},
            }
        )

        self.assertIn("slots", snapshot)
        self.assertEqual(snapshot["slots"]["domain"]["value"], "pest")
        self.assertEqual(snapshot["slots"]["region"]["value"], "徐州市")
        self.assertEqual(snapshot["slots"]["time_range"]["value"], {"mode": "relative", "value": "5_months"})
        self.assertEqual(snapshot["slots"]["intent"]["value"], "data_query")
        for slot_name in ["domain", "region", "time_range", "intent"]:
            for field in ["value", "source", "priority", "ttl", "updated_at_turn"]:
                self.assertIn(field, snapshot["slots"][slot_name])

    def test_normalize_memory_snapshot_adds_three_layer_context(self):
        snapshot = normalize_memory_snapshot(
            {
                "domain": "pest",
                "region_name": "徐州市",
                "query_type": "pest_top",
                "window": {"window_type": "months", "window_value": 5},
                "route": {"query_type": "pest_top", "region_level": "city"},
                "user_preferences": {"answer_style": "concise"},
            }
        )

        self.assertIn("memory_layers", snapshot)
        self.assertEqual(snapshot["memory_layers"]["session_context"]["domain"], "pest")
        self.assertEqual(snapshot["memory_layers"]["session_context"]["region_name"], "徐州市")
        self.assertEqual(snapshot["memory_layers"]["task_context"]["query_type"], "pest_top")
        self.assertEqual(snapshot["memory_layers"]["task_context"]["time_range"]["value"], "5_months")
        self.assertEqual(snapshot["memory_layers"]["user_context"]["answer_style"], "concise")

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

    def test_local_memory_store_recovers_from_corrupted_utf8_payload(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "agent-memory.json")
            with open(path, "wb") as handle:
                handle.write(b'{"thread-bad": "\x83"}')

            store = LocalMemoryStore(path)

            snapshot = store.load("thread-bad")

            self.assertEqual(snapshot["memory_version"], 2)
            self.assertEqual(snapshot["domain"], "")
            store.remember("thread-good", {"domain": "pest", "region_name": "常州市"})
            repaired = store.load("thread-good")
            self.assertEqual(repaired["domain"], "pest")
            self.assertEqual(repaired["region_name"], "常州市")

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
