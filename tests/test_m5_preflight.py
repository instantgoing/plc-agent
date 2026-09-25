import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent import M5Request, PLCRepairAgent
from agent._smolagents import OpenAIModel
from agent.model import ModelPreflightError, preflight_model
from smolagents.default_tools import FinalAnswerTool


def _completion(tool_name: str | None = None, arguments: str = '{}'):
    tool_calls = None if tool_name is None else [
        {'id': 'preflight-1', 'type': 'function',
         'function': {'name': tool_name, 'arguments': arguments}}
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            role='assistant', content=None if tool_calls else 'plain text',
            tool_calls=tool_calls,
        ))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )


def _model(completion):
    create = Mock(return_value=completion)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return OpenAIModel(model_id='test-model', api_key='secret', client=client,
                       tool_choice='auto', retry=False), create


class ModelPreflightTests(unittest.TestCase):
    def test_preflight_uses_auto_and_actual_tool_schema_without_executing_tool(self):
        model, create = _model(_completion('final_answer', '{"answer":"PLC_PREFLIGHT_OK"}'))
        preflight_model(model, [FinalAnswerTool()])

        sent = create.call_args.kwargs
        self.assertEqual(sent['tool_choice'], 'auto')
        self.assertEqual(sent['model'], 'test-model')
        self.assertEqual(sent['tools'][0]['function']['name'], 'final_answer')
        self.assertIn('answer', sent['tools'][0]['function']['parameters']['properties'])

    def test_plain_text_preflight_stops_before_runtime(self):
        model, create = _model(_completion())
        events = []
        with patch('agent.tools.get_plc_status') as status:
            result = PLCRepairAgent(model=model).run(
                M5Request('control a motor'), on_event=events.append,
            )

        self.assertEqual(result.failure_kind, 'model_tool_unsupported')
        self.assertEqual(result.state, 'fatal_failure')
        self.assertEqual(result.attempts, [])
        status.assert_not_called()
        names = {tool['function']['name'] for tool in create.call_args.kwargs['tools']}
        self.assertIn('validate_candidate', names)
        self.assertIn('evaluate_candidate', names)
        self.assertIn('ask_user', names)
        self.assertEqual([event.name for event in events],
                         ['model_preflight_started', 'failed'])

    def test_bad_tool_arguments_are_distinct_from_no_tool_support(self):
        model, _ = _model(_completion('final_answer', '{'))
        with self.assertRaises(ModelPreflightError) as raised:
            preflight_model(model, [FinalAnswerTool()])
        self.assertEqual(raised.exception.kind, 'model_output_invalid')

    def test_wrong_probe_tool_is_not_treated_as_capability_success(self):
        model, _ = _model(_completion('submit_requirement_spec', '{}'))
        with self.assertRaises(ModelPreflightError) as raised:
            preflight_model(model, [FinalAnswerTool()])
        self.assertEqual(raised.exception.kind, 'model_output_invalid')

    def test_auth_failure_preflight_does_not_touch_runtime(self):
        model, create = _model(_completion())
        create.side_effect = RuntimeError('401 authentication failed')
        with patch('agent.tools.get_plc_status') as status:
            result = PLCRepairAgent(model=model).run(M5Request('control a motor'))
        self.assertEqual(result.failure_kind, 'model_authentication_failed')
        self.assertEqual(result.attempts, [])
        status.assert_not_called()

    def test_endpoint_rejecting_tool_schema_is_reported_before_runtime(self):
        model, create = _model(_completion())
        create.side_effect = RuntimeError('400 invalid tools schema for this model')
        with patch('agent.tools.get_plc_status') as status:
            result = PLCRepairAgent(model=model).run(M5Request('control a motor'))
        self.assertEqual(result.failure_kind, 'model_tool_unsupported')
        self.assertEqual(result.attempts, [])
        status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
