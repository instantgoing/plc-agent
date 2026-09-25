import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.env import load_project_env


class M5EnvironmentTests(unittest.TestCase):
    def test_local_file_takes_precedence_over_default_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("PLC_AGENT_MODEL_ID=from-default\n", encoding="utf-8")
            (root / ".env.local").write_text("PLC_AGENT_MODEL_ID=from-local\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                load_project_env(root)
                self.assertEqual(os.environ["PLC_AGENT_MODEL_ID"], "from-local")

    def test_process_environment_takes_precedence_over_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text("PLC_AGENT_API_KEY=from-file\n", encoding="utf-8")

            with patch.dict(os.environ, {"PLC_AGENT_API_KEY": "from-process"}, clear=True):
                load_project_env(root)
                self.assertEqual(os.environ["PLC_AGENT_API_KEY"], "from-process")

    def test_core_configuration_loads_without_python_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text('PLC_MATIEC_BACKEND="docker"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch.dict("sys.modules", {"dotenv": None}):
                load_project_env(root)
                self.assertEqual(os.environ["PLC_MATIEC_BACKEND"], "docker")


if __name__ == "__main__":
    unittest.main()
