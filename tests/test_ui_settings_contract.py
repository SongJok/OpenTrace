import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiSettingsContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_ui_settings_router_has_get_and_patch(self):
        txt = self._read("gateway/api_gateway/routers/ui_settings.py")
        self.assertRegex(txt, r"@router\.get\(['\"]\/users\/ui-settings['\"]\)")
        self.assertRegex(txt, r"@router\.patch\(['\"]\/users\/ui-settings['\"]\)")

    def test_ui_settings_router_included_in_main(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("ui_settings.router", txt)

    def test_user_ui_settings_model_exists(self):
        txt = self._read("infra/storage/models.py")
        self.assertIn("class UserUiSettings(Base)", txt)
        self.assertIn('__tablename__ = "user_ui_settings"', txt)


if __name__ == "__main__":
    unittest.main()
