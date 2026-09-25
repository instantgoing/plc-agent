import os
import unittest
from unittest.mock import patch

from agent.model import ModelConfig, ModelConfigurationError, build_model, load_model_config


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

    @patch("agent.model.OpenAIModel")
    def test_deepseek_uses_auto_without_disabling_thinking(self, model_mock) -> None:
        config = ModelConfig(
            provider="openai",
            model_id="deepseek-flash",
            api_key="secret",
            api_base="https://api.deepseek.com",
        )

        build_model(config)

        self.assertEqual(model_mock.call_args.kwargs["tool_choice"], "auto")
        self.assertNotIn("extra_body", model_mock.call_args.kwargs)

    @patch("agent.model.OpenAIModel")
    def test_non_deepseek_endpoint_receives_no_vendor_thinking_parameter(self, model_mock) -> None:
        config = ModelConfig(
            provider="openai",
            model_id="gpt-test",
            api_key="secret",
            api_base="https://example.invalid/v1",
        )

        build_model(config)

        self.assertNotIn("extra_body", model_mock.call_args.kwargs)
        self.assertEqual(model_mock.call_args.kwargs["tool_choice"], "auto")


if __name__ == "__main__":
    unittest.main()
