import tempfile
import unittest
from pathlib import Path

from scripts.train_lora import check_training_gate, dataset_digest


class TrainGateTests(unittest.TestCase):
    def test_full_train_waits_for_reloaded_smoke_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data" / "processed").mkdir(parents=True)
            (root / "data" / "processed" / "train.jsonl").write_text("train")
            (root / "data" / "processed" / "val.jsonl").write_text("val")
            digest = dataset_digest(root)
            self.assertIn("smoke", check_training_gate(root, digest)[0])
            marker = root / "outputs" / "smoke" / "status.json"
            marker.parent.mkdir(parents=True)
            marker.write_text('{"dataset_sha256":"' + digest + '",'
                              '"adapter_reloaded":false}', encoding="utf-8")
            self.assertIn("reload", check_training_gate(root, digest)[0])
            marker.write_text('{"dataset_sha256":"wrong",'
                              '"adapter_reloaded":true}', encoding="utf-8")
            self.assertIn("changed", check_training_gate(root, digest)[0])
            marker.write_text('{"dataset_sha256":"' + digest + '",'
                              '"adapter_reloaded":true}', encoding="utf-8")
            self.assertEqual(check_training_gate(root, digest), [])


if __name__ == "__main__":
    unittest.main()
