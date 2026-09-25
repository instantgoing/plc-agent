import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import run_p5_acceptance


class P5RunnerSafetyTests(unittest.TestCase):
    def test_busy_runtime_is_never_replaced_by_acceptance_runner(self):
        with patch.dict(os.environ, {
            'PLC_AGENT_API_KEY': 'test-key', 'PLC_AGENT_MODEL_ID': 'test-model'
        }), patch('run_p5_acceptance.load_project_env'), patch(
            'run_p5_acceptance.get_plc_status', return_value=SimpleNamespace(
                success=True, actual_status='RUNNING'
            )
        ), patch('run_p5_acceptance.unittest.TextTestRunner') as runner:
            code = run_p5_acceptance.main()
        self.assertEqual(code, 2)
        runner.assert_not_called()

    def test_missing_credentials_stops_before_runtime_status(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            'run_p5_acceptance.load_project_env'
        ), patch('run_p5_acceptance.get_plc_status') as status:
            code = run_p5_acceptance.main()
        self.assertEqual(code, 2)
        status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
