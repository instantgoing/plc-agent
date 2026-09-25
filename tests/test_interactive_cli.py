import unittest
from threading import Event, Thread
from unittest.mock import patch

from agent import AttemptRecord, M5Result, PLCEvent
from interactive_cli import _run_turn, print_progress, print_result, run_interactive
from main import build_parser


def reply(state, *, success=False, question='', st=None):
    return M5Result(
        success=success,
        failure_kind=None,
        st_code=st,
        verification_plan={'steps': [{'inputs': {'Start': True},
                                      'expected': {'Motor': True}}]} if st else None,
        attempts=[AttemptRecord(
            attempt=1, st_code_digest='digest', phase='accepted', accepted=True,
            verify_result={'steps': [{'step': 1, 'passed': True,
                                      'expected': {'Motor': True},
                                      'actual': {'motor': True}}],
                           'failures': [], 'cleanup_result': {'success': True}},
            stop_result={'success': True, 'actual_status': 'STOPPED'},
        )] if st else [],
        final_message=question or 'verified',
        state=state,
        clarification_options=['I will provide actual addresses.',
                               'Start=%IX0.0, Motor=%QX0.0'] if question else [],
    )


class FakeSession:
    def __init__(self):
        self.turn = 0
        self.last_result = None
        self.calls = []

    def submit(self, message):
        self.turn += 1
        self.calls.append(('submit', message))
        self.last_result = reply('needs_user_input', question='What are the real addresses?')
        return self.last_result

    def resume(self, message):
        self.turn += 1
        self.calls.append(('resume', message))
        self.last_result = reply('accepted', success=True, st='PROGRAM Main\nEND_PROGRAM')
        return self.last_result

    def metrics_dict(self):
        return {'turns': self.turn}

    def cancel(self):
        return True


class InteractiveCliTests(unittest.TestCase):
    def test_chat_command_is_separate_from_json_agent(self):
        self.assertEqual(build_parser().parse_args(['chat']).command, 'chat')
        self.assertTrue(build_parser().parse_args(['agent', 'task', '--json']).json)

    def test_same_session_resumes_selected_answer_and_prints_evidence(self):
        session = FakeSession()
        answers = iter(['2', '/metrics', '/json', '/quit'])
        lines = []
        code = run_interactive(
            session, first_message='Build a motor controller',
            input_fn=lambda prompt: next(answers), output=lines.append,
        )
        rendered = '\n'.join(lines)
        self.assertEqual(code, 0)
        self.assertEqual(session.calls, [
            ('submit', 'Build a motor controller'),
            ('resume', 'Start=%IX0.0, Motor=%QX0.0'),
        ])
        self.assertIn('What are the real addresses?', rendered)
        self.assertIn('--- 最终 ST ---', rendered)
        self.assertIn('--- 验证计划 ---', rendered)
        self.assertIn('expected=', rendered)
        self.assertIn('actual=', rendered)
        self.assertIn('"turns": 2', rendered)

    def test_progress_step_exposes_expected_and_actual(self):
        lines = []
        print_progress(PLCEvent('verification_step', 's1', 1, 1, {
            'step': 2, 'passed': False,
            'expected': {'Motor': True}, 'actual': {'motor': False},
        }), output=lines.append)
        self.assertIn('expected=', lines[0])
        self.assertIn('actual=', lines[0])

    def test_failed_candidate_is_labeled_unverified(self):
        lines = []
        result = reply('exhausted', st='PROGRAM Main\nEND_PROGRAM')
        result.success = False
        result.failure_kind = 'attempt_limit_reached'
        print_result(result, output=lines.append)
        self.assertIn('未验证的候选 ST', '\n'.join(lines))

    def test_keyboard_interrupt_requests_cancel_and_waits_for_worker(self):
        class WaitingSession:
            def __init__(self):
                self.cancelled = Event()
                self.calls = 0

            def submit(self, message):
                self.cancelled.wait(2)
                return reply('cancelled')

            def cancel(self):
                self.calls += 1
                self.cancelled.set()
                return True

        session = WaitingSession()
        original_join = Thread.join
        interrupted = False

        def interrupt_once(thread, timeout=None):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original_join(thread, timeout)

        lines = []
        with patch('interactive_cli.Thread.join', interrupt_once):
            result = _run_turn(session, 'task', first=True, output=lines.append)
        self.assertEqual(result.state, 'cancelled')
        self.assertGreaterEqual(session.calls, 1)
        self.assertTrue(any('等待 Runtime 停止' in line for line in lines))


if __name__ == '__main__':
    unittest.main()
