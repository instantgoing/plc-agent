import os
import unittest
from unittest.mock import patch

from agent.model import ModelConfigurationError, load_model_config


class M5ModelConfigTests(unittest.TestCase):
    def test_missing_model_id_is_configuration_error(self) -> None:
        with patch.dict(os.environ, {"PLC_AGENT_API_KEY": "secret"}, clear=True):
            with self.assertRaises(ModelConfigurationError):
                load_model_config()

    def test_missing_key_is_configuration_error(self) -> None:
        with patch.dict(
            os.environ,
            {"PLC_AGENT_MODEL_ID": "test-model"},
            clear=True,
        ):
            with self.assertRaises(ModelConfigurationError):
                load_model_config()

    def test_public_config_does_not_include_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PLC_AGENT_MODEL_ID": "test-model",
                "PLC_AGENT_API_KEY": "secret",
                "PLC_AGENT_API_BASE": "https://example.invalid/v1",
            },
            clear=True,
        ):
            config = load_model_config()
        self.assertEqual(config.public_dict()["model_id"], "test-model")
        self.assertNotIn("api_key", config.public_dict())


if __name__ == "__main__":
    unittest.main()
