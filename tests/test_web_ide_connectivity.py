"""Proxy startup is opt-in and never changes global network settings."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.codex_client import CodexInfrastructureError
from web_ide.connectivity import ensure_local_proxy


class ConnectivityTests(unittest.TestCase):
    def test_running_proxy_is_reused(self):
        with patch.dict(os.environ, {"PLC_CODEX_PROXY": "http://127.0.0.1:7897"}), \
                patch("web_ide.connectivity.socket.create_connection"), \
                patch("web_ide.connectivity.subprocess.Popen") as launch:
            self.assertIn("ready", ensure_local_proxy())
            launch.assert_not_called()

    def test_missing_proxy_fails_without_launch_configuration(self):
        with patch.dict(os.environ, {"PLC_CODEX_PROXY": "http://127.0.0.1:7897", "PLC_CODEX_PROXY_EXECUTABLE": ""}), \
                patch("web_ide.connectivity.socket.create_connection", side_effect=OSError("offline")):
            with self.assertRaisesRegex(CodexInfrastructureError, "automatic startup"):
                ensure_local_proxy()

    def test_configured_executable_starts_only_after_connection_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "proxy.exe"
            executable.touch()
            with patch.dict(os.environ, {"PLC_CODEX_PROXY": "http://127.0.0.1:7897", "PLC_CODEX_PROXY_EXECUTABLE": str(executable)}), \
                    patch("web_ide.connectivity.socket.create_connection", side_effect=[OSError("offline"), unittest.mock.MagicMock()]), \
                    patch("web_ide.connectivity.subprocess.Popen") as launch:
                self.assertIn("started automatically", ensure_local_proxy())
                self.assertEqual(launch.call_args.args[0], [str(executable)])
                self.assertNotIn("shell", launch.call_args.kwargs)
                if os.name == "nt":
                    self.assertEqual(launch.call_args.kwargs["startupinfo"].wShowWindow, 0)

    def test_remote_proxy_does_not_launch_local_program(self):
        with patch.dict(os.environ, {"PLC_CODEX_PROXY": "http://proxy.example:8080"}), \
                patch("web_ide.connectivity.subprocess.Popen") as launch:
            self.assertIn("remote", ensure_local_proxy())
            launch.assert_not_called()

    def test_started_proxy_has_bounded_wait_when_port_never_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "proxy.exe"
            executable.touch()
            with patch.dict(os.environ, {"PLC_CODEX_PROXY": "http://127.0.0.1:7897", "PLC_CODEX_PROXY_EXECUTABLE": str(executable)}), \
                    patch("web_ide.connectivity.socket.create_connection", side_effect=OSError("offline")), \
                    patch("web_ide.connectivity.subprocess.Popen"), \
                    patch("web_ide.connectivity.time.monotonic", side_effect=[0, 0, 11]), \
                    patch("web_ide.connectivity.time.sleep"):
                with self.assertRaisesRegex(CodexInfrastructureError, "still unavailable"):
                    ensure_local_proxy()


if __name__ == "__main__":
    unittest.main()
