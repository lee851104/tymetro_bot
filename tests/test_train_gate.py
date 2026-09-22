import json
import tempfile
import unittest
from pathlib import Path

from scripts.train_lora import check_training_gate, config_digest, dataset_digest


class TrainGateTests(unittest.TestCase):
    def test_full_train_waits_for_reloaded_smoke_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data" / "training").mkdir(parents=True)
            (root / "data" / "training" / "train.jsonl").write_text("train")
            (root / "data" / "training" / "val.jsonl").write_text("val")
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
            self.assertIn("configuration", check_training_gate(root, digest)[0])
            status = {"dataset_sha256": digest, "adapter_reloaded": True,
                      "config_sha256": config_digest(), "reload_forward_finite": False}
            marker.write_text(json.dumps(status), encoding="utf-8")
            self.assertIn("forward", check_training_gate(root, digest)[0])
            status["reload_forward_finite"] = True
            marker.write_text(json.dumps(status), encoding="utf-8")
            self.assertIn("update", check_training_gate(root, digest)[0])
            status["adapter_updated"] = True
            marker.write_text(json.dumps(status), encoding="utf-8")
            self.assertEqual(check_training_gate(root, digest), [])
            self.assertIn("configuration", check_training_gate(root, digest, "changed")[0])


if __name__ == "__main__":
    unittest.main()
