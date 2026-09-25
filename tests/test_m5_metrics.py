import unittest
from types import SimpleNamespace

from agent import M5Result, PLCEvent, SessionMetrics
from agent._smolagents import AgentParsingError
from agent.contracts import AttemptRecord
from agent.events import EventEmitter
from agent.plc_agent import PLCRepairAgent


def event(name, data=None):
    return PLCEvent(name=name, session_id='s1', turn=1, sequence=1, data=data or {})


def result(success, attempts=0):
    return M5Result(
        success=success, failure_kind=None if success else 'behavior_verification_failed',
        st_code=None, verification_plan=None,
        attempts=[AttemptRecord(i + 1, 'digest', 'accepted' if success else 'failed')
                  for i in range(attempts)],
        final_message='done', state='accepted' if success else 'exhausted',
    )


class SessionMetricsTests(unittest.TestCase):
    def test_counts_and_rates_have_explicit_denominators(self):
        metrics = SessionMetrics()
        metrics.first_event_delays_ms.append(120)
        metrics.first_event_delays_ms.append(80)
        metrics.record_event(event('waiting_for_user'))
        metrics.record_event(event('tool_call_rejected', {'reason': 'schema_error'}))
        metrics.record_event(event('tool_call_rejected', {'reason': 'candidate_not_validated'}))
        metrics.record_event(event('tool_call_rejected', {'reason': 'tool_exception'}))
        metrics.record_event(event('cleanup_completed', {
            'stop_result': {'success': True}, 'release_result': {'success': True},
        }))
        metrics.record_event(event('cleanup_completed', {
            'stop_result': {'success': False}, 'release_result': {'success': True},
        }))
        metrics.record_turn(result(False, 2), resumed=False, repaired=True)
        metrics.record_turn(result(True, 1), resumed=True, repaired=True)

        value = metrics.to_dict()
        self.assertEqual(value['first_progress_event_delay_ms'], 80)
        self.assertEqual(value['average_first_progress_event_delay_ms'], 100)
        self.assertEqual(value['clarification_questions'], 1)
        self.assertEqual(value['meaningless_tool_calls'], 2)
        self.assertEqual(value['schema_errors'], 1)
        self.assertEqual(value['runtime_attempts'], 3)
        self.assertEqual(value['repair_success_rate'], 0.5)
        self.assertEqual(value['continuation_success_rate'], 1.0)
        self.assertEqual(value['cleanup_success_rate'], 0.5)

    def test_unobserved_rates_are_null_not_false_success(self):
        value = SessionMetrics().to_dict()
        self.assertIsNone(value['repair_success_rate'])
        self.assertIsNone(value['cleanup_success_rate'])

    def test_recovered_model_parse_error_is_counted(self):
        error = AgentParsingError('invalid tool JSON', SimpleNamespace(log_error=lambda _: None))
        agent = SimpleNamespace(memory=SimpleNamespace(steps=[SimpleNamespace(error=error)]))
        events = []
        PLCRepairAgent._record_parse_errors(agent, EventEmitter(events.append))
        metrics = SessionMetrics()
        for item in events:
            metrics.record_event(item)
        self.assertEqual(metrics.schema_errors, 1)
        self.assertEqual(metrics.meaningless_tool_calls, 1)


if __name__ == '__main__':
    unittest.main()
