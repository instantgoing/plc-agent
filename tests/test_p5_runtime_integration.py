"""Opt-in P5 acceptance against real MatIEC and OpenPLC, never a fake Runtime."""

import json
import os
import unittest
from pathlib import Path

from agent import M5Request, PLCRepairAgent
from agent.tools import CandidateEvaluator
from plc_tools import compile_st, get_plc_status, start_plc, stop_plc
from tests.test_m5_agent import ActionSequenceModel, VALID_SPEC


_ENABLED = (
    os.getenv('PLC_M5_RUNTIME_INTEGRATION') == '1'
    and os.getenv('PLC_OPENPLC_INTEGRATION') == '1'
)


@unittest.skipUnless(_ENABLED, 'set PLC_M5_RUNTIME_INTEGRATION=1 and PLC_OPENPLC_INTEGRATION=1')
class P5RuntimeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        status = get_plc_status()
        if not status.success or status.actual_status != 'STOPPED':
            self.skipTest('test Runtime must be available and STOPPED')
        root = Path(__file__).parents[1]
        self.source = root / 'examples' / 'problem_001_solution.st'
        self.st_code = self.source.read_text(encoding='utf-8')
        self.plan = {'steps': json.loads(
            (root / 'problems' / 'problem_001' / 'tests.json').read_text(encoding='utf-8')
        )}

    def test_real_matiec_error_is_repaired_before_runtime_attempt(self):
        bad_st = self.st_code.replace('Motor := Start AND NOT Stop;',
                                      'Motor := Start AND ;')
        self.assertNotEqual(bad_st, self.st_code)
        model = ActionSequenceModel([
            ('submit_requirement_spec', VALID_SPEC),
            ('validate_candidate', {'st_code': bad_st, 'verification_plan': self.plan}),
            ('validate_candidate', {'st_code': self.st_code, 'verification_plan': self.plan}),
            ('evaluate_candidate', {'st_code': self.st_code, 'verification_plan': self.plan}),
            ('final_answer', {'answer': 'corrected and verified'}),
        ])
        events = []
        result = PLCRepairAgent(model=model).run(
            M5Request('Motor = Start AND NOT Stop', max_attempts=1, max_actions=6),
            on_event=events.append,
        )
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(len(result.attempts), 1)
        self.assertIn('check_failed', [item.name for item in events])
        self.assertTrue(result.attempts[-1].verify_result['passed'])
        self.assertEqual(result.attempts[-1].stop_result['actual_status'], 'STOPPED')

    def test_real_expected_actual_failure_is_repaired_on_second_runtime_attempt(self):
        bad_st = self.st_code.replace('Motor := Start AND NOT Stop;',
                                      'Motor := Start OR NOT Stop;')
        self.assertNotEqual(bad_st, self.st_code)
        model = ActionSequenceModel([
            ('submit_requirement_spec', VALID_SPEC),
            ('validate_candidate', {'st_code': bad_st, 'verification_plan': self.plan}),
            ('evaluate_candidate', {'st_code': bad_st, 'verification_plan': self.plan}),
            ('validate_candidate', {'st_code': self.st_code, 'verification_plan': self.plan}),
            ('evaluate_candidate', {'st_code': self.st_code, 'verification_plan': self.plan}),
            ('final_answer', {'answer': 'behavior corrected and verified'}),
        ])
        result = PLCRepairAgent(model=model).run(
            M5Request('Motor = Start AND NOT Stop', max_attempts=2, max_actions=7)
        )
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(len(result.attempts), 2)
        first, second = result.attempts
        self.assertFalse(first.verify_result['passed'])
        self.assertTrue(first.verify_result['failures'])
        self.assertNotEqual(first.verify_result['failures'][0]['expected'],
                            first.verify_result['failures'][0]['actual'])
        self.assertTrue(second.verify_result['passed'])
        self.assertEqual(second.stop_result['actual_status'], 'STOPPED')

    def test_runtime_busy_preserves_the_existing_running_program(self):
        evaluator = CandidateEvaluator(max_attempts=1, source_filename='candidate.st')
        validation = evaluator.validate(self.st_code, self.plan)
        self.assertTrue(validation['valid'], validation)
        compiled = compile_st(self.source)
        self.assertTrue(compiled.success, compiled.to_dict())
        started = start_plc()
        self.assertTrue(started.success, started.to_dict())
        try:
            response = evaluator.evaluate(self.st_code, self.plan)
            self.assertFalse(response['accepted'])
            self.assertEqual(response['feedback']['failure_kind'], 'runtime_busy')
            self.assertEqual(response['attempts_used'], 0)
            self.assertEqual(get_plc_status().actual_status, 'RUNNING')
        finally:
            stopped = stop_plc()
            self.assertTrue(stopped.success, stopped.to_dict())


if __name__ == '__main__':
    unittest.main()
