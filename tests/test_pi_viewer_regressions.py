import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PiViewerRegressionTests(unittest.TestCase):
    def test_maintenance_startup_uses_existing_notification_badge_helper(self):
        tree = ast.parse((PROJECT_ROOT / "pi_viewer.py").read_text(encoding="utf-8"))
        viewer_class = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ViewerWindow"
        )
        method_names = {
            node.name for node in viewer_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        maintenance_method = next(
            node
            for node in viewer_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "apply_maintenance_config"
        )
        self_calls = {
            node.func.attr
            for node in ast.walk(maintenance_method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        }

        self.assertIn("update_notification_queue_badge", method_names)
        self.assertIn("update_notification_queue_badge", self_calls)
        self.assertNotIn("update_alert_queue_badge", self_calls)


if __name__ == "__main__":
    unittest.main()
