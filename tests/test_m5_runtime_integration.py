import json
import os
import unittest
from pathlib import Path

from agent import M5Request, PLCRepairAgent, PLCSession
from agent.tools import CandidateEvaluator
from tests.test_m5_agent import ActionSequenceModel, VALID_SPEC


_ENABLED = os.getenv("PLC_M5_RUNTIME_INTEGRATION") == "1" and os.getenv("PLC_OPENPLC_INTEGRATION") == "1"


@unittest.skipUnless(
    _ENABLED,
    "set PLC_M5_RUNTIME_INTEGRATION=1 and PLC_OPENPLC_INTEGRATION=1 with the real runtime configured",
)
class RealM5RuntimeIntegrationTests(unittest.TestCase):
    @staticmethod
    def _problem() -> tuple[str, dict]:
        root = Path(__file__).parents[1]
        source = root / "examples" / "problem_001_solution.st"
        steps = json.loads(
            (root / "problems" / "problem_001" / "tests.json").read_text(
                encoding="utf-8"
            )
        )
        return source.read_text(encoding="utf-8"), {"steps": steps}

    def test_candidate_evaluator_passes_real_problem_001(self) -> None:
        st_code, plan = self._problem()
        evaluator = CandidateEvaluator(max_attempts=1, source_filename="candidate.st")
        validation = evaluator.validate(st_code, plan)
        self.assertTrue(validation["valid"], validation)
        result = evaluator.evaluate(st_code, plan)
        self.assertTrue(result["accepted"], result)
        self.assertTrue(result["verify_result"]["passed"])
        self.assertEqual(result["stop_result"]["actual_status"], "STOPPED")

    def test_agent_orchestration_passes_real_problem_001(self) -> None:
        st_code, plan = self._problem()
        model = ActionSequenceModel(
            [
                ("submit_requirement_spec", VALID_SPEC),
                ("validate_candidate", {"st_code": st_code, "verification_plan": plan}),
                ("evaluate_candidate", {"st_code": st_code, "verification_plan": plan}),
                ("final_answer", {"answer": "verified by the real Runtime"}),
            ]
        )
        result = PLCRepairAgent(model=model).run(
            M5Request("control a motor", max_attempts=1, max_actions=5)
        )
        self.assertTrue(result.success, result.to_dict())
        self.assertEqual(result.state, "accepted")
        self.assertEqual(result.attempts[-1].verify_result["passed"], True)
        self.assertEqual(result.attempts[-1].stop_result["actual_status"], "STOPPED")

    def test_session_modifies_verified_program_and_revalidates(self) -> None:
        st_initial, plan_initial = self._problem()
        st_modified = st_initial.replace(
            "    Stop AT %IX0.1 : BOOL;",
            "    Stop AT %IX0.1 : BOOL;\n    Enable AT %IX0.2 : BOOL;",
        ).replace("Motor := Start AND NOT Stop;", "Motor := Start AND NOT Stop AND Enable;")
        self.assertNotEqual(st_initial, st_modified)
        plan_modified = {"steps": [
            {"inputs": {"Start": False, "Stop": False, "Enable": True},
             "expected": {"Motor": False}},
            {"inputs": {"Start": True, "Stop": False, "Enable": False},
             "expected": {"Motor": False}},
            {"inputs": {"Start": True, "Stop": False, "Enable": True},
             "expected": {"Motor": True}},
            {"inputs": {"Start": True, "Stop": True, "Enable": True},
             "expected": {"Motor": False}},
        ]}
        spec_modified = {**VALID_SPEC,
                         "inputs": ["Start at %IX0.0", "Stop at %IX0.1", "Enable at %IX0.2"],
                         "state_rules": ["Motor requires Start and Enable, without Stop"],
                         "observable_assertions": ["Enable=false blocks Motor"]}
        model = ActionSequenceModel([
            ("submit_requirement_spec", VALID_SPEC),
            ("validate_candidate", {"st_code": st_initial, "verification_plan": plan_initial}),
            ("evaluate_candidate", {"st_code": st_initial, "verification_plan": plan_initial}),
            ("final_answer", {"answer": "original verified"}),
            ("submit_requirement_spec", spec_modified),
            ("validate_candidate", {"st_code": st_modified, "verification_plan": plan_modified}),
            ("evaluate_candidate", {"st_code": st_modified, "verification_plan": plan_modified}),
            ("final_answer", {"answer": "Enable change verified"}),
        ])
        events = []
        session = PLCSession(
            agent=PLCRepairAgent(model=model),
            max_runtime_attempts=1,
            on_event=events.append,
        )
        first = session.submit("Control Motor with Start and Stop")
        second = session.resume("Add Enable at %IX0.2; Motor must not run without it")
        self.assertTrue(first.success, first.to_dict())
        self.assertTrue(second.success, second.to_dict())
        self.assertEqual(session.current_st, st_modified)
        self.assertEqual(session.requirement_spec.inputs[-1], "Enable at %IX0.2")
        self.assertTrue(any(
            step["actual"]["motor"] for step in first.attempts[-1].verify_result["steps"]
        ))
        self.assertTrue(any(
            step["actual"]["motor"] for step in second.attempts[-1].verify_result["steps"]
        ))
        self.assertEqual(second.attempts[-1].stop_result["actual_status"], "STOPPED")
        self.assertEqual(len([e for e in events if e.name == "verification_step"]), 7)

    def test_session_changes_real_delay_from_10_to_5_seconds(self) -> None:
        st_10 = (Path(__file__).parents[1] / "examples" / "p2_delay_10s.st").read_text(
            encoding="utf-8"
        )
        st_5 = st_10.replace("T#10s", "T#5s")
        self.assertNotEqual(st_10, st_5)
        spec_10 = {
            "goal": "Turn Motor on after Start remains true for 10 seconds",
            "inputs": ["Start at %IX0.0"],
            "outputs": ["Motor at %QX0.0"],
            "timing_rules": ["10 second on-delay"],
            "state_rules": ["Reset Motor when Start is false"],
            "safety_rules": ["Motor stays off until delay completes"],
            "observable_assertions": ["Motor off before delay, on after delay"],
            "assumptions": [],
            "open_questions": [],
        }
        spec_5 = {
            **spec_10,
            "goal": spec_10["goal"].replace("10", "5"),
            "timing_rules": ["5 second on-delay"],
        }

        def plan(delay_ms):
            # settle_ms is relative to the preceding step's actual force/read;
            # absolute time_ms would include those I/O latencies.
            steps = [
                {"inputs": {"Start": False}, "expected": {"Motor": False}},
                {"inputs": {"Start": True}, "expected": {"Motor": False}, "settle_ms": 0},
                {"inputs": {}, "expected": {"Motor": delay_ms == 5000},
                 "settle_ms": 7500},
            ]
            if delay_ms == 10000:
                steps.append({"inputs": {}, "expected": {"Motor": True},
                              "settle_ms": 4500})
            return {"steps": steps}

        plan_10 = plan(10000)
        plan_5 = plan(5000)
        model = ActionSequenceModel([
            ("submit_requirement_spec", spec_10),
            ("validate_candidate", {"st_code": st_10, "verification_plan": plan_10}),
            ("evaluate_candidate", {"st_code": st_10, "verification_plan": plan_10}),
            ("final_answer", {"answer": "10 seconds verified"}),
            ("submit_requirement_spec", spec_5),
            ("validate_candidate", {"st_code": st_5, "verification_plan": plan_5}),
            ("evaluate_candidate", {"st_code": st_5, "verification_plan": plan_5}),
            ("final_answer", {"answer": "5 seconds verified"}),
        ])
        events = []
        session = PLCSession(
            agent=PLCRepairAgent(model=model), max_runtime_attempts=1,
            on_event=events.append,
        )
        first = session.submit("Turn Motor on after Start remains true for 10 seconds")
        second = session.resume("把刚才的 10 秒改成 5 秒")
        self.assertTrue(first.success, first.to_dict())
        self.assertTrue(second.success, second.to_dict())
        self.assertEqual(session.current_st, st_5)
        self.assertEqual(session.requirement_spec.timing_rules, ["5 second on-delay"])
        self.assertEqual(first.attempts[-1].verify_result["steps"][-1]["actual"]["motor"], True)
        self.assertEqual(second.attempts[-1].verify_result["steps"][-1]["actual"]["motor"], True)
        self.assertEqual(second.attempts[-1].stop_result["actual_status"], "STOPPED")
        self.assertEqual(len([e for e in events if e.name == "verification_step"]), 7)

    def test_session_cancellation_releases_forces_and_stops_runtime(self) -> None:
        st_code, _ = self._problem()
        plan = {"steps": [
            {"inputs": {"Start": False, "Stop": False}, "expected": {"Motor": False}},
            {"time_ms": 10000, "inputs": {"Start": True, "Stop": False},
             "expected": {"Motor": True}},
        ]}
        model = ActionSequenceModel([
            ("submit_requirement_spec", VALID_SPEC),
            ("validate_candidate", {"st_code": st_code, "verification_plan": plan}),
            ("evaluate_candidate", {"st_code": st_code, "verification_plan": plan}),
            ("final_answer", {"answer": "cancelled"}),
        ])
        events = []
        session = PLCSession(agent=PLCRepairAgent(model=model), max_runtime_attempts=1)

        def on_event(event):
            events.append(event)
            if event.name == "verification_step":
                session.cancel()

        result = session.submit("Control a motor", on_event=on_event)
        self.assertEqual(result.state, "cancelled", result.to_dict())
        verification = result.attempts[-1].verify_result
        self.assertTrue(verification["cancelled"])
        self.assertTrue(verification["cleanup_result"]["success"])
        self.assertEqual(result.attempts[-1].stop_result["actual_status"], "STOPPED")
        self.assertIn("cleanup_completed", [event.name for event in events])


if __name__ == "__main__":
    unittest.main()
