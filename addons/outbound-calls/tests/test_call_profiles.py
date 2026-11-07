import builtins
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
import call_profiles  # noqa: E402


class CallProfileTests(unittest.TestCase):
    def test_outcome_order_and_exact_default_mappings(self):
        self.assertEqual(
            call_profiles.OUTCOMES,
            ("complete", "still_running", "failed_or_blocked", "unclear"),
        )
        expected = {
            "default": ("gpt-6.1-sol", "medium", "fast"),
            "complete": ("gpt-6.1-terra", "medium", "default"),
            "still_running": ("gpt-6.1-terra", "high", "fast"),
            "failed_or_blocked": ("gpt-6.1-sol", "medium", "fast"),
            "unclear": ("gpt-6.1-sol", "medium", "fast"),
        }
        for outcome, mapping in expected.items():
            with self.subTest(outcome=outcome):
                selected = call_profiles.select_profile(
                    None if outcome == "default" else outcome
                )
                self.assertEqual(
                    (selected["model"], selected["effort"], selected["service_tier"]),
                    mapping,
                )
                self.assertEqual(selected["outcome"], outcome)

    def test_omitted_outcome_selects_copy_of_default(self):
        first = call_profiles.select_profile()
        second = call_profiles.select_profile(None)
        self.assertEqual(first, second)
        self.assertEqual(first["outcome"], "default")
        self.assertTrue(first["voice_instructions"])
        self.assertIsNot(first, second)

    def test_unknown_outcome_is_rejected(self):
        for outcome in ("default", "running", "COMPLETE", 1, []):
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                call_profiles.select_profile(outcome)

    def test_override_validation_is_strict_and_copies_input(self):
        supplied = {
            "complete": {"effort": "high"},
            "default": {"service_tier": "default"},
        }
        validated = call_profiles.validate_profiles(supplied)
        self.assertEqual(validated, supplied)
        self.assertIsNot(validated, supplied)
        self.assertIsNot(validated["complete"], supplied["complete"])

        for invalid in (
            [],
            "complete",
            {"other": {}},
            {"complete": None},
            {"complete": []},
            {"complete": {"voice_instructions": "untrusted"}},
            {"complete": {"temperature": 0}},
            {"complete": {"model": "gpt-6.1-astra"}},
            {"complete": {"effort": "low"}},
            {"complete": {"service_tier": "priority"}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                call_profiles.validate_profiles(invalid)
        self.assertEqual(call_profiles.validate_profiles(None), {})

    def test_select_merges_matching_override_and_keeps_voice_instructions_fixed(self):
        instructions = call_profiles.select_profile("complete")["voice_instructions"]
        supplied = {"complete": {"model": "gpt-6.1-sol", "effort": "high"}}
        selected = call_profiles.select_profile("complete", supplied)
        self.assertEqual(selected["model"], "gpt-6.1-sol")
        self.assertEqual(selected["effort"], "high")
        self.assertEqual(selected["service_tier"], "default")
        self.assertEqual(selected["voice_instructions"], instructions)
        self.assertEqual(selected["outcome"], "complete")
        self.assertEqual(supplied, {"complete": {"model": "gpt-6.1-sol", "effort": "high"}})

    def test_returned_profiles_and_overrides_cannot_mutate_global_profiles(self):
        first = call_profiles.select_profile("still_running")
        first["model"] = "gpt-6.1-sol"
        first["voice_instructions"] = "changed"
        second = call_profiles.select_profile("still_running")
        self.assertEqual(second["model"], "gpt-6.1-terra")
        self.assertEqual(second["effort"], "high")
        self.assertNotEqual(second["voice_instructions"], "changed")

        overrides = {"unclear": {"model": "gpt-6.1-terra"}}
        call_profiles.select_profile("unclear", overrides)
        overrides["unclear"]["model"] = "gpt-6.1-sol"
        self.assertEqual(call_profiles.select_profile("unclear")["model"], "gpt-6.1-sol")

    def test_import_and_selection_do_not_perform_io_or_start_external_work(self):
        source_path = ROOT / "runtime" / "call_profiles.py"
        source = source_path.read_text(encoding="utf-8")
        compiled = compile(source, str(source_path), "exec")
        namespace = {"__name__": "call_profiles_purity_check"}
        with (
            mock.patch.object(builtins, "open", side_effect=AssertionError("open")),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")),
            mock.patch.object(socket, "socket", side_effect=AssertionError("socket")),
        ):
            exec(compiled, namespace)
            namespace["select_profile"]("complete")
            namespace["validate_profiles"](None)


if __name__ == "__main__":
    unittest.main()
