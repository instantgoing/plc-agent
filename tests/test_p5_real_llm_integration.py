"""Opt-in real-model multi-turn P5 acceptance with real PLC execution."""

import os
import unittest
from unittest.mock import patch

from agent import M5Request, PLCRepairAgent, PLCSession
from plc_tools import get_plc_status


_ENABLED = all((
    os.getenv('PLC_AGENT_INTEGRATION') == '1',
    os.getenv('PLC_OPENPLC_INTEGRATION') == '1',
    bool(os.getenv('PLC_AGENT_API_KEY')),
    bool(os.getenv('PLC_AGENT_MODEL_ID')),
))


@unittest.skipUnless(_ENABLED, 'set real LLM, MatIEC, and OpenPLC integration environment')
class P5RealLLMAcceptanceTests(unittest.TestCase):
    def test_invalid_real_api_key_fails_before_plc_tools(self):
        with patch('agent.tools.get_plc_status') as status:
            result = PLCRepairAgent(api_key='p5-intentionally-invalid-key').run(
                M5Request('Control a motor with Start=%IX0.0 and Motor=%QX0.0')
            )
        self.assertEqual(result.failure_kind, 'model_authentication_failed')
        self.assertEqual(result.attempts, [])
        status.assert_not_called()

    def test_clarify_then_verify_then_modify_in_same_session(self):
        status = get_plc_status()
        if not status.success or status.actual_status != 'STOPPED':
            self.skipTest('test Runtime must be available and STOPPED')

        session = PLCSession(max_actions=8, max_runtime_attempts=3)
        first = session.submit(
            'Write a simple combinational motor program. Start directly controls '
            'Motor; I will provide the actual PLC input and output addresses next. '
            'Do not guess the addresses.'
        )
        self.assertEqual(first.state, 'needs_user_input', first.to_dict())
        self.assertEqual(first.attempts, [])

        second = session.resume(
            'Start is a located BOOL input at %IX0.0 and Motor is a located BOOL '
            'output at %QX0.0. Motor equals Start on each scan; no latch, delay, '
            'or other inputs. Motor must be false whenever Start is false.'
        )
        self.assertTrue(second.success, second.to_dict())
        self.assertTrue(second.attempts[-1].verify_result['passed'])
        self.assertEqual(second.attempts[-1].stop_result['actual_status'], 'STOPPED')

        third = session.resume(
            'Change only the Start input address from %IX0.0 to %IX0.2. Keep '
            'Motor at %QX0.0 and the same combinational behavior. Revalidate '
            'the full modified program on the real Runtime.'
        )
        self.assertTrue(third.success, third.to_dict())
        self.assertIn('%IX0.2', session.current_st)
        self.assertTrue(third.attempts[-1].verify_result['passed'])
        self.assertEqual(third.attempts[-1].stop_result['actual_status'], 'STOPPED')

        metrics = session.metrics_dict()
        self.assertEqual(metrics['turns'], 3)
        self.assertGreaterEqual(metrics['clarification_questions'], 1)
        self.assertGreaterEqual(metrics['runtime_attempts'], 2)
        self.assertEqual(metrics['continuation_success_rate'], 1.0)
        self.assertEqual(metrics['cleanup_success_rate'], 1.0)


if __name__ == '__main__':
    unittest.main()
