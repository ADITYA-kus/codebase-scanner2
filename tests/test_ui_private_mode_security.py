import os
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestUiPrivateModeSecurity(unittest.TestCase):
    def test_token_field_is_password_and_private_mode_text_exists(self):
        template_path = os.path.join(PROJECT_ROOT, "ui", "templates", "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="gh-token"', html)
        self.assertIn('type="password"', html)
        self.assertIn("Private Repo Mode", html)
        self.assertIn("Tokens are used only in memory", html)

    def test_token_is_cleared_and_errors_use_redaction(self):
        js_path = os.path.join(PROJECT_ROOT, "ui", "static", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function updatePrivateModeIndicator()", js)
        self.assertGreaterEqual(js.count("ghTokenEl.value = \"\";"), 2)
        self.assertIn("showToast(redactSecrets(", js)
        self.assertIn("repoModalErrorEl.textContent = redactSecrets(", js)

    def test_byok_modal_and_password_field_exist(self):
        template_path = os.path.join(PROJECT_ROOT, "ui", "templates", "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="ai-mode-select"', html)
        self.assertIn('id="byok-modal"', html)
        self.assertIn('id="byok-provider"', html)
        self.assertIn('id="byok-api-key"', html)
        self.assertIn('id="byok-api-key" type="password"', html)
        self.assertIn('id="byok-session-only"', html)
        self.assertIn('id="byok-save"', html)
        self.assertIn('id="byok-cancel"', html)
        self.assertIn('id="byok-clear"', html)

    def test_byok_key_cleared_on_close_save_and_hosted_switch(self):
        js_path = os.path.join(PROJECT_ROOT, "ui", "static", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function clearByokKeyInput()", js)
        self.assertGreaterEqual(js.count("clearByokKeyInput();"), 3)
        self.assertIn("byokApiKey = \"\";", js)
        self.assertIn("callByokProxy(", js)


if __name__ == "__main__":
    unittest.main()
