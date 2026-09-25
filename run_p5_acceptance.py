"""Opt-in end-to-end P5 acceptance; never starts over an occupied Runtime."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from agent.env import load_project_env
from plc_tools import get_plc_status


TESTS = (
    'tests.test_p5_real_llm_integration.P5RealLLMAcceptanceTests.test_invalid_real_api_key_fails_before_plc_tools',
    'tests.test_m5_integration.RealM5IntegrationTests.test_real_llm_generates_and_verifies_problem_001',
    'tests.test_p5_real_llm_integration.P5RealLLMAcceptanceTests.test_clarify_then_verify_then_modify_in_same_session',
    'tests.test_p5_runtime_integration.P5RuntimeAcceptanceTests.test_real_matiec_error_is_repaired_before_runtime_attempt',
    'tests.test_p5_runtime_integration.P5RuntimeAcceptanceTests.test_real_expected_actual_failure_is_repaired_on_second_runtime_attempt',
    'tests.test_p5_runtime_integration.P5RuntimeAcceptanceTests.test_runtime_busy_preserves_the_existing_running_program',
    'tests.test_m5_runtime_integration.RealM5RuntimeIntegrationTests.test_session_changes_real_delay_from_10_to_5_seconds',
    'tests.test_m5_runtime_integration.RealM5RuntimeIntegrationTests.test_session_cancellation_releases_forces_and_stops_runtime',
)


def main() -> int:
    load_project_env(Path(__file__).resolve().parent)
    if not os.getenv('PLC_AGENT_API_KEY') or not os.getenv('PLC_AGENT_MODEL_ID'):
        print('P5 requires a real PLC_AGENT_API_KEY and PLC_AGENT_MODEL_ID.', file=sys.stderr)
        return 2
    status = get_plc_status()
    if not status.success or status.actual_status != 'STOPPED':
        print('P5 requires an available, STOPPED test Runtime; existing programs are untouched.',
              file=sys.stderr)
        return 2
    os.environ['PLC_AGENT_INTEGRATION'] = '1'
    os.environ['PLC_M5_RUNTIME_INTEGRATION'] = '1'
    os.environ['PLC_OPENPLC_INTEGRATION'] = '1'
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name) for name in TESTS
    )
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if outcome.wasSuccessful() and not outcome.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
