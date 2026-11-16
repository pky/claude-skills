"""会話記録抽出 CLI の公開契約を検証する。"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone


SCRIPT = Path(__file__).resolve().parents[1] / "skills/retro/scripts/retro_extract.py"
NOW = "2026-11-16T12:00:00Z"
SINCE = "2026-11-09T12:00:00Z"
RECENT = "2026-11-15T12:00:00Z"
OLD = "2026-11-08T12:00:00Z"


class RetroExtractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.tool_number = 0

    def record(self, kind, content, session="session-a", timestamp=RECENT, **extra):
        record = {
            "type": kind,
            "sessionId": session,
            "message": {"content": content},
        }
        if timestamp is not None:
            record["timestamp"] = timestamp
        record.update(extra)
        return record

    def tool_result(
        self, text="失敗しました", *, tool="Bash", tool_input=None,
        session="session-a", timestamp=RECENT, is_error=True,
        permission=None, violations=None,
    ):
        self.tool_number += 1
        tool_id = f"tool-{self.tool_number}"
        if tool_input is None:
            tool_input = {"command": "git push origin topic"}
        call = self.record("assistant", [{
            "type": "tool_use", "id": tool_id, "name": tool, "input": tool_input,
        }], session, timestamp)
        result = self.record("user", [{
            "type": "tool_result", "tool_use_id": tool_id,
            "content": text, "is_error": is_error,
        }], session, timestamp)
        if permission is not None:
            result["permissionDecision"] = permission
        if violations is not None:
            result["sandboxViolations"] = violations
        return [call, result]

    def rejected(self, text="操作が拒否されました", *, source="hook", **kwargs):
        permission = {"decision": "reject", "source": source}
        permission.update(kwargs.pop("permission_fields", {}))
        return self.tool_result(text, permission=permission, **kwargs)

    def human(self, text, session="session-a", timestamp=RECENT, **extra):
        extra.setdefault("origin", {"kind": "human"})
        return self.record("user", text, session, timestamp, **extra)

    def assistant(self, text, session="session-a", timestamp=RECENT):
        return self.record("assistant", [{"type": "text", "text": text}],
                           session, timestamp)

    def write_log(self, records, *, session="session-a", project="project-a",
                  subagent=False):
        if subagent:
            path = self.root / project / session / "subagents/agent-x.jsonl"
        else:
            path = self.root / project / f"{session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n"
                                for record in records), encoding="utf-8")
        recent_mtime = datetime.fromisoformat(NOW.replace("Z", "+00:00")).timestamp()
        os.utime(path, (recent_mtime, recent_mtime))
        return path

    def run_cli(self, *, root=None, days=7):
        return subprocess.run(
            ["python3", str(SCRIPT), "--root", str(root if root is not None else self.root),
             "--now", NOW, "--days", str(days)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def extract(self, *, days=7):
        result = self.run_cli(days=days)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def repeated_rejections(self):
        for session, numbers in (("session-a", (1, 2, 3)), ("session-b", (4, 5))):
            records = []
            for number in numbers:
                records.extend(self.rejected(f"拒否 {number}", session=session))
            self.write_log(records, session=session)

    def repeated_failures(self):
        for session, numbers in (("session-a", (1, 2, 3)), ("session-b", (4, 5))):
            records = []
            for number in numbers:
                records.extend(self.tool_result(f"失敗 {number}", session=session))
            self.write_log(records, session=session)

    def test_output_has_contract_fields(self):
        result = self.extract()
        self.assertEqual(set(result), {
            "since", "root", "files", "subagent_files", "blocked", "failures",
            "corrections_total", "corrections",
        })
        for key in ("blocked", "failures", "corrections"):
            self.assertEqual(result[key], [])

    def test_output_root_is_requested_root(self):
        self.assertEqual(self.extract()["root"], str(self.root))

    def test_since_is_now_minus_requested_days(self):
        since = self.extract(days=3)["since"]
        self.assertEqual(datetime.fromisoformat(since.replace("Z", "+00:00")),
                         datetime(2026, 11, 13, 12, tzinfo=timezone.utc))

    def test_nonexistent_root_exits_with_code_two_and_reason(self):
        result = self.run_cli(root=self.root / "does-not-exist")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("can't open file", result.stderr)

    def test_output_preserves_japanese_characters(self):
        self.write_log(self.rejected("日本語の拒否理由"))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("日本語の拒否理由", result.stdout)

    def test_output_uses_one_space_indentation(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'\n "[^"\n]+":')

    def test_blocked_source_hook(self):
        self.write_log(self.rejected(source="hook"))
        self.assertEqual(self.extract()["blocked"][0]["source"], "hook")

    def test_blocked_source_user(self):
        self.write_log(self.rejected(source="user_reject"))
        self.assertEqual(self.extract()["blocked"][0]["source"], "user")

    def test_blocked_source_classifier(self):
        self.write_log(self.rejected(source="config",
                                     permission_fields={"reasonType": "classifier"}))
        self.assertEqual(self.extract()["blocked"][0]["source"], "classifier")

    def test_blocked_source_rule(self):
        self.write_log(self.rejected(source="config",
                                     permission_fields={"reasonType": "rule"}))
        self.assertEqual(self.extract()["blocked"][0]["source"], "rule")

    def test_blocked_source_sandbox(self):
        self.write_log(self.tool_result(violations=[{
            "kind": "network", "host": "example.test", "port": 8,
        }], is_error=False))
        self.assertEqual(self.extract()["blocked"][0]["source"], "sandbox")

    def test_hook_source_takes_precedence_over_classifier_reason(self):
        self.write_log(self.rejected(source="hook",
                                     permission_fields={"reasonType": "classifier"}))
        self.assertEqual(self.extract()["blocked"][0]["source"], "hook")

    def test_user_source_takes_precedence_over_classifier_reason(self):
        self.write_log(self.rejected(source="user_reject",
                                     permission_fields={"reasonType": "classifier"}))
        self.assertEqual(self.extract()["blocked"][0]["source"], "user")

    def test_reject_is_blocked_even_without_error_flag(self):
        self.write_log(self.rejected(is_error=False))
        self.assertEqual(self.extract()["blocked"][0]["count"], 1)

    def test_accept_and_empty_sandbox_are_not_blocked(self):
        self.write_log(self.tool_result(is_error=False,
                                       permission={"decision": "accept", "source": "config"},
                                       violations=[]))
        self.assertEqual(self.extract()["blocked"], [])

    def test_sandbox_reason_uses_kind_host_and_port(self):
        self.write_log(self.tool_result("本文は使わない", violations=[{
            "kind": "network", "host": "example.test", "port": 8,
        }]))
        group = self.extract()["blocked"][0]
        self.assertEqual(group["reason_head"], "network example.test:#")
        self.assertEqual(group["examples"][0]["reason"], "network example.test:8")

    def test_blocked_normalizes_digits_and_counts_same_key(self):
        self.repeated_rejections()
        groups = self.extract()["blocked"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["reason_head"], "拒否 #")
        self.assertEqual(groups[0]["count"], 5)

    def test_blocked_counts_distinct_sessions(self):
        self.repeated_rejections()
        self.assertEqual(self.extract()["blocked"][0]["sessions"], 2)

    def test_blocked_keeps_at_most_two_examples(self):
        self.repeated_rejections()
        examples = self.extract()["blocked"][0]["examples"]
        self.assertEqual(len(examples), 2)
        self.assertTrue(all(example["reason"].startswith("拒否 ") for example in examples))

    def test_blocked_separates_sources(self):
        self.write_log(self.rejected(source="hook") + self.rejected(source="user_reject"))
        self.assertEqual(len(self.extract()["blocked"]), 2)

    def test_blocked_separates_tools(self):
        self.write_log(self.rejected(tool="Bash") +
                       self.rejected(tool="Read", tool_input={"file_path": "/tmp/a"}))
        self.assertEqual({group["tool"] for group in self.extract()["blocked"]},
                         {"Bash", "Read"})

    def test_blocked_separates_reason_heads(self):
        self.write_log(self.rejected("理由あ") + self.rejected("理由い"))
        self.assertEqual(len(self.extract()["blocked"]), 2)

    def test_blocked_head_uses_first_nonempty_line_and_eighty_characters(self):
        self.write_log(self.rejected("\n\n" + "あ" * 85 + "\n二行目"))
        self.assertEqual(self.extract()["blocked"][0]["reason_head"], "あ" * 80)

    def test_blocked_sorts_by_count_descending_then_head_ascending(self):
        records = []
        for reason, count in (("い", 2), ("う", 3), ("あ", 2)):
            for _ in range(count):
                records.extend(self.rejected(reason))
        self.write_log(records)
        self.assertEqual([(group["reason_head"], group["count"])
                          for group in self.extract()["blocked"]],
                         [("う", 3), ("あ", 2), ("い", 2)])

    def test_blocked_example_has_project_session_timestamp_and_command(self):
        self.write_log(self.rejected("理由", session="actual-session"),
                       session="filename-session", project="project-b")
        self.assertEqual(self.extract()["blocked"][0]["examples"], [{
            "project": "project-b", "session": "actual-session", "timestamp": RECENT,
            "input": "git push origin topic", "reason": "理由",
        }])

    def test_blocked_input_uses_file_path_for_file_tools(self):
        self.write_log(self.rejected(tool="Read", tool_input={"file_path": "/tmp/test.txt"}))
        self.assertEqual(self.extract()["blocked"][0]["examples"][0]["input"],
                         "/tmp/test.txt")

    def test_blocked_input_uses_compact_json_for_other_tools(self):
        self.write_log(self.rejected(tool="Search", tool_input={"query": "sample", "limit": 2}))
        summary = self.extract()["blocked"][0]["examples"][0]["input"]
        self.assertEqual(json.loads(summary), {"query": "sample", "limit": 2})
        self.assertNotIn(" ", summary)

    def test_blocked_input_is_truncated_to_one_hundred_fifty_characters(self):
        self.write_log(self.rejected(tool_input={"command": "あ" * 205}))
        self.assertEqual(self.extract()["blocked"][0]["examples"][0]["input"], "あ" * 150)

    def test_blocked_file_input_is_truncated_to_one_hundred_fifty_characters(self):
        path = "/tmp/" + "あ" * 200
        self.write_log(self.rejected(tool="Read", tool_input={"file_path": path}))
        self.assertEqual(self.extract()["blocked"][0]["examples"][0]["input"], path[:150])

    def test_blocked_json_input_is_truncated_to_one_hundred_fifty_characters(self):
        tool_input = {"query": "あ" * 200}
        self.write_log(self.rejected(tool="Search", tool_input=tool_input))
        expected = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))[:150]
        self.assertEqual(self.extract()["blocked"][0]["examples"][0]["input"], expected)

    def test_blocked_reason_is_truncated_to_two_hundred_characters(self):
        self.write_log(self.rejected("あ" * 305))
        self.assertEqual(self.extract()["blocked"][0]["examples"][0]["reason"], "あ" * 200)

    def test_blocked_accepts_text_block_result_content(self):
        self.write_log(self.rejected([{"type": "text", "text": "拒否理由"}]))
        self.assertEqual(self.extract()["blocked"][0]["reason_head"], "拒否理由")

    def test_failures_exclude_permission_rejections(self):
        self.write_log(self.rejected() + self.rejected())
        result = self.extract()
        self.assertEqual(result["blocked"][0]["count"], 2)
        self.assertEqual(result["failures"], [])

    def test_failures_exclude_sandbox_violations(self):
        records = []
        for _ in range(2):
            records.extend(self.tool_result(violations=[{
                "kind": "network", "host": "example.test", "port": 8,
            }]))
        self.write_log(records)
        result = self.extract()
        self.assertEqual(result["blocked"][0]["count"], 2)
        self.assertEqual(result["failures"], [])

    def test_failures_omit_single_occurrence(self):
        self.write_log(self.tool_result())
        self.assertEqual(self.extract()["failures"], [])

    def test_failures_ignore_successful_tool_results(self):
        self.write_log(self.tool_result(is_error=False) + self.tool_result(is_error=False))
        self.assertEqual(self.extract()["failures"], [])

    def test_failures_normalize_digits_and_count_same_key(self):
        self.repeated_failures()
        groups = self.extract()["failures"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["error_head"], "失敗 #")
        self.assertEqual(groups[0]["count"], 5)

    def test_failures_counts_distinct_sessions(self):
        self.repeated_failures()
        self.assertEqual(self.extract()["failures"][0]["sessions"], 2)

    def test_failures_keeps_at_most_two_examples(self):
        self.repeated_failures()
        self.assertEqual(len(self.extract()["failures"][0]["examples"]), 2)

    def test_bash_command_key_strips_cd_and_keeps_subcommand(self):
        self.write_log(self.tool_result(tool_input={"command": "cd x && git push origin a"}) +
                       self.tool_result(tool_input={"command": "cd y && git push origin b"}))
        groups = self.extract()["failures"]
        self.assertEqual([(group["command_key"], group["count"]) for group in groups],
                         [("git push", 2)])

    def test_bash_command_key_uses_basename_and_omits_option(self):
        self.write_log(self.tool_result(tool_input={"command": "/usr/bin/xcodebuild -scheme A"}) +
                       self.tool_result(tool_input={"command": "/usr/bin/xcodebuild -scheme B"}))
        self.assertEqual(self.extract()["failures"][0]["command_key"], "xcodebuild")

    def test_non_bash_command_key_is_tool_name(self):
        self.write_log(self.tool_result(tool="Read", tool_input={"file_path": "/tmp/a"}) +
                       self.tool_result(tool="Read", tool_input={"file_path": "/tmp/b"}))
        group = self.extract()["failures"][0]
        self.assertEqual((group["tool"], group["command_key"], group["count"]),
                         ("Read", "Read", 2))

    def test_failures_separate_command_keys(self):
        records = []
        for command in ("git push origin a", "git status", "git push origin b", "git status"):
            records.extend(self.tool_result(tool_input={"command": command}))
        self.write_log(records)
        self.assertEqual({group["command_key"] for group in self.extract()["failures"]},
                         {"git push", "git status"})

    def test_failures_head_uses_first_nonempty_line_and_eighty_characters(self):
        text = "\n\n" + "あ" * 85 + "\n二行目"
        self.write_log(self.tool_result(text) + self.tool_result(text))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "あ" * 80)

    def test_failures_head_skips_exit_code_line_and_normalizes_error_digits(self):
        text = "Exit code 1\nerror: foo 12"
        self.write_log(self.tool_result(text) + self.tool_result(text))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "error: foo ##")

    def test_failures_separate_errors_after_exit_code_lines(self):
        records = []
        for text in ("Exit code 1\nerror: foo", "Exit code 2\nerror: bar"):
            for _ in range(2):
                records.extend(self.tool_result(text))
        self.write_log(records)
        self.assertEqual([(group["error_head"], group["count"])
                          for group in self.extract()["failures"]],
                         [("error: bar", 2), ("error: foo", 2)])

    def test_failures_head_falls_back_when_only_exit_code_line_remains(self):
        text = "Exit code 1"
        self.write_log(self.tool_result(text) + self.tool_result(text))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "Exit code #")

    def test_failures_head_skips_padded_exit_code_line_and_blank_line(self):
        text = "  Exit code 128  \n\nfatal: x"
        self.write_log(self.tool_result(text) + self.tool_result(text))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "fatal: x")

    def test_failures_head_keeps_error_before_exit_code_line(self):
        text = "error: foo\nExit code 1"
        self.write_log(self.tool_result(text) + self.tool_result(text))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "error: foo")

    def test_failures_sorts_by_count_descending_then_head_ascending(self):
        records = []
        for error, count in (("い", 2), ("う", 3), ("あ", 2)):
            for _ in range(count):
                records.extend(self.tool_result(error))
        self.write_log(records)
        self.assertEqual([(group["error_head"], group["count"])
                          for group in self.extract()["failures"]],
                         [("う", 3), ("あ", 2), ("い", 2)])

    def test_failure_examples_include_metadata_and_file_input(self):
        records = self.tool_result("失敗", tool="Read", tool_input={"file_path": "/tmp/a"},
                                   session="actual-session")
        records += self.tool_result("失敗", tool="Read", tool_input={"file_path": "/tmp/a"},
                                    session="actual-session")
        self.write_log(records, project="project-b", session="filename-session")
        for example in self.extract()["failures"][0]["examples"]:
            self.assertEqual(example, {
                "project": "project-b", "session": "actual-session", "timestamp": RECENT,
                "input": "/tmp/a", "error": "失敗",
            })

    def test_failure_input_is_truncated_to_one_hundred_fifty_characters(self):
        records = []
        for _ in range(2):
            records.extend(self.tool_result(tool_input={"command": "echo " + "あ" * 205}))
        self.write_log(records)
        for example in self.extract()["failures"][0]["examples"]:
            self.assertEqual(example["input"], "echo " + "あ" * 145)

    def test_failure_file_input_is_truncated_to_one_hundred_fifty_characters(self):
        path = "/tmp/" + "あ" * 200
        records = []
        for _ in range(2):
            records.extend(self.tool_result(tool="Read", tool_input={"file_path": path}))
        self.write_log(records)
        for example in self.extract()["failures"][0]["examples"]:
            self.assertEqual(example["input"], path[:150])

    def test_failure_json_input_is_truncated_to_one_hundred_fifty_characters(self):
        tool_input = {"query": "あ" * 200}
        records = []
        for _ in range(2):
            records.extend(self.tool_result(tool="Search", tool_input=tool_input))
        self.write_log(records)
        expected = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))[:150]
        for example in self.extract()["failures"][0]["examples"]:
            self.assertEqual(example["input"], expected)

    def test_failure_error_is_truncated_to_two_hundred_characters(self):
        self.write_log(self.tool_result("あ" * 305) + self.tool_result("あ" * 305))
        for example in self.extract()["failures"][0]["examples"]:
            self.assertEqual(example["error"], "あ" * 200)

    def test_failures_accept_text_block_result_content(self):
        content = [{"type": "text", "text": "失敗理由"}]
        self.write_log(self.tool_result(content) + self.tool_result(content))
        self.assertEqual(self.extract()["failures"][0]["error_head"], "失敗理由")

    def test_corrections_exclude_first_human_message_in_each_session(self):
        for session in ("session-a", "session-b"):
            self.write_log([self.human("違う、最初の依頼", session),
                            self.human("違う、続けてください", session)], session=session)
        corrections = self.extract()["corrections"]
        self.assertEqual(len(corrections), 2)
        self.assertEqual({item["session"] for item in corrections}, {"session-a", "session-b"})
        self.assertTrue(all(item["text"] == "違う、続けてください" for item in corrections))

    def test_corrections_exclude_angle_bracket_prefix(self):
        self.write_log([self.human("最初の依頼"), self.human("<command>違う</command>"),
                        self.human("違う、続けてください")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、続けてください"])

    def test_corrections_exclude_slash_prefix(self):
        self.write_log([self.human("最初の依頼"), self.human("/retro 違う"),
                        self.human("違う、続けてください")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、続けてください"])

    def test_corrections_exclude_meta_messages(self):
        self.write_log([self.human("最初の依頼"), self.human("違う", isMeta=True),
                        self.human("違う、続けてください", isMeta=False)])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、続けてください"])

    def test_corrections_exclude_nonhuman_origin(self):
        self.write_log([self.human("最初の依頼"),
                        self.human("違う", origin={"kind": "agent"}),
                        self.human("違う、続けてください")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、続けてください"])

    def test_corrections_require_human_origin(self):
        self.write_log([self.human("最初の依頼"), self.record("user", "違う"),
                        self.human("違う、続けてください")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、続けてください"])

    def test_corrections_exclude_subagent_files(self):
        self.write_log([self.human("最初の依頼"), self.human("違う、戻して")], subagent=True)
        self.assertEqual(self.extract()["corrections"], [])

    def test_corrections_prev_assistant_is_latest_text_tail(self):
        latest = "直前の説明" + "あ" * 210 + "末尾の説明"
        assistant = self.record("assistant", [
            {"type": "text", "text": "前半の説明"},
            {"type": "text", "text": latest},
        ])
        self.write_log([self.human("最初の依頼"), self.assistant("古い説明"),
                        assistant, self.human("違う")])
        self.assertEqual(self.extract()["corrections"][0]["prev_assistant"],
                         latest[-200:])

    def test_corrections_prev_assistant_does_not_leak_between_sessions(self):
        self.write_log([self.human("最初の依頼"), self.assistant("別セッションの説明")])
        self.write_log([self.human("最初の依頼", "session-b"),
                        self.human("違う", "session-b")], session="session-b")
        self.assertEqual(self.extract()["corrections"][0]["prev_assistant"], "")

    def test_corrections_match_original_specified_phrases(self):
        phrases = ["違う", "ちがう", "じゃなく", "ではなく", "しないで", "やめて", "なんで",
                   "なぜ", "言った", "勝手", "戻して", "聞いてない", "ダメ", "だめ"]
        self.write_log([self.human("最初の依頼")] +
                       [self.human(f"これは{phrase}という発言です") for phrase in phrases])
        corrections = self.extract()["corrections"]
        self.assertEqual([item["text"] for item in corrections],
                         [f"これは{phrase}という発言です" for phrase in phrases])

    def test_corrections_match_itte(self):
        self.write_log([self.human("最初の依頼"), self.human("言って")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["言って"])

    def test_corrections_match_daro(self):
        self.write_log([self.human("最初の依頼"), self.human("だろ")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["だろ"])

    def test_corrections_match_dakara(self):
        self.write_log([self.human("最初の依頼"), self.human("だから")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["だから"])

    def test_corrections_match_wakaranai(self):
        self.write_log([self.human("最初の依頼"), self.human("わからない")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["わからない"])

    def test_corrections_match_wakarinikui(self):
        self.write_log([self.human("最初の依頼"), self.human("わかりにくい")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["わかりにくい"])

    def test_corrections_match_imi(self):
        self.write_log([self.human("最初の依頼"), self.human("意味")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["意味"])

    def test_corrections_match_iya_with_comma(self):
        self.write_log([self.human("最初の依頼"), self.human("いや、続けて")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["いや、続けて"])

    def test_corrections_match_iya_with_space(self):
        self.write_log([self.human("最初の依頼"), self.human("いや 続けて")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["いや 続けて"])

    def test_corrections_match_toiuka(self):
        self.write_log([self.human("最初の依頼"), self.human("というか")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["というか"])

    def test_corrections_match_ndaga(self):
        self.write_log([self.human("最初の依頼"), self.human("んだが")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["んだが"])

    def test_corrections_match_ndayo(self):
        self.write_log([self.human("最初の依頼"), self.human("んだよ")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]], ["んだよ"])

    def test_corrections_do_not_match_tsukaiyasui(self):
        self.write_log([self.human("最初の依頼"), self.human("使いやすい")])
        self.assertEqual(self.extract()["corrections"], [])

    def test_corrections_exclude_messages_without_keywords(self):
        self.write_log([self.human("最初の依頼"), self.human("続けてください")])
        self.assertEqual(self.extract()["corrections"], [])

    def test_corrections_have_no_hint_field(self):
        self.write_log([self.human("最初の依頼"), self.human("違う")])
        self.assertNotIn("hint", self.extract()["corrections"][0])

    def test_corrections_total_is_zero_without_messages(self):
        self.assertEqual(self.extract().get("corrections_total"), 0)

    def test_corrections_total_includes_messages_without_keywords(self):
        self.write_log([self.human("最初の依頼"), self.human("違う"),
                        self.human("続けてください")])
        self.assertEqual(self.extract().get("corrections_total"), 2)

    def test_corrections_total_excludes_ineligible_messages(self):
        self.write_log([
            self.human("違う、最初の依頼"),
            self.human("<command>違う</command>"),
            self.human("/retro 違う"),
            self.human("違う", isMeta=True),
            self.human("違う", origin={"kind": "agent"}),
            self.record("user", "違う"),
            self.human("違う", timestamp=OLD),
            self.assistant("違う"),
            self.human("続けてください"),
        ] + self.tool_result("違う"))
        self.write_log([self.human("最初の依頼", "session-b"),
                        self.human("違う", "session-b")], session="session-b", subagent=True)
        self.assertEqual(self.extract().get("corrections_total"), 1)

    def test_corrections_sort_by_timestamp_ascending(self):
        self.write_log([
            self.human("最初の依頼"),
            self.human("言って、後", timestamp="2026-11-15T13:00:00Z"),
            self.human("違う、後", timestamp="2026-11-15T14:00:00Z"),
            self.human("違う、先", timestamp="2026-11-15T11:00:00Z"),
            self.human("言って、先", timestamp="2026-11-15T10:00:00Z"),
        ])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["言って、先", "違う、先", "言って、後", "違う、後"])

    def test_corrections_include_project_session_timestamp_and_text(self):
        self.write_log([self.human("最初の依頼", "actual-session"),
                        self.assistant("説明", "actual-session"),
                        self.human("違う、続けてください", "actual-session")],
                       project="project-b", session="filename-session")
        self.assertEqual(self.extract()["corrections"], [{
            "project": "project-b", "session": "actual-session", "cwd": "", "timestamp": RECENT,
            "text": "違う、続けてください", "prev_assistant": "説明",
        }])

    def test_corrections_text_is_truncated_to_three_hundred_characters(self):
        self.write_log([self.human("最初の依頼"), self.human("違う" + "あ" * 305)])
        self.assertEqual(self.extract()["corrections"][0]["text"], "違う" + "あ" * 298)

    def test_corrections_accept_all_documented_prompt_sources(self):
        sources = ("typed", "queued", "suggestion_accepted")
        self.write_log([self.human("最初の依頼")] +
                       [self.human("違う、" + source, promptSource=source) for source in sources])
        self.assertEqual({item["text"] for item in self.extract()["corrections"]},
                         {"違う、" + source for source in sources})

    def test_old_blocked_records_are_excluded_by_timestamp(self):
        self.write_log(self.rejected("古い拒否", timestamp=OLD) + self.rejected("新しい拒否"))
        self.assertEqual([group["reason_head"] for group in self.extract()["blocked"]],
                         ["新しい拒否"])

    def test_old_failure_records_are_excluded_by_timestamp(self):
        self.write_log(self.tool_result("古い失敗", timestamp=OLD) +
                       self.tool_result("古い失敗", timestamp=OLD) +
                       self.tool_result("新しい失敗") + self.tool_result("新しい失敗"))
        self.assertEqual([group["error_head"] for group in self.extract()["failures"]],
                         ["新しい失敗"])

    def test_old_corrections_are_excluded_by_timestamp(self):
        self.write_log([self.human("最初の依頼"),
                        self.human("違う、古い訂正", timestamp=OLD),
                        self.human("違う、新しい訂正")])
        self.assertEqual([item["text"] for item in self.extract()["corrections"]],
                         ["違う、新しい訂正"])

    def test_timestamp_at_since_boundary_is_included(self):
        self.write_log(self.rejected(timestamp=SINCE))
        self.assertEqual(self.extract()["blocked"][0]["count"], 1)

    def test_records_without_timestamp_are_not_dropped(self):
        self.write_log(self.rejected(timestamp=None))
        self.assertEqual(self.extract()["blocked"][0]["count"], 1)

    def test_old_mtime_file_content_is_excluded(self):
        path = self.write_log(self.rejected("古いファイル内の新しいレコード"))
        old_mtime = datetime.fromisoformat(OLD.replace("Z", "+00:00")).timestamp()
        os.utime(path, (old_mtime, old_mtime))
        self.write_log(self.rejected("新しいファイル"), session="session-b")
        self.assertEqual([group["reason_head"] for group in self.extract()["blocked"]],
                         ["新しいファイル"])

    def test_subagent_blocked_results_are_counted(self):
        self.write_log(self.rejected() + self.rejected(), subagent=True)
        self.assertEqual(self.extract()["blocked"][0]["count"], 2)

    def test_subagent_failures_are_counted(self):
        self.write_log(self.tool_result() + self.tool_result(), subagent=True)
        self.assertEqual(self.extract()["failures"][0]["count"], 2)

    def test_main_and_subagent_file_counts(self):
        self.write_log([], session="session-a")
        self.write_log([], session="session-b")
        self.write_log([], subagent=True)
        self.write_log([], session="session-b", subagent=True)
        self.write_log([], session="session-c", subagent=True)
        result = self.extract()
        self.assertEqual((result["files"], result["subagent_files"]), (2, 3))

    def test_malformed_json_line_is_skipped_without_losing_valid_records(self):
        records = self.rejected("有効な拒否") + self.tool_result() + self.tool_result()
        path = self.write_log(records)
        mtime = path.stat().st_mtime
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("壊れたJSON\n" + lines[0] + "{bad json\n" + "".join(lines[1:]),
                        encoding="utf-8")
        os.utime(path, (mtime, mtime))
        result = self.extract()
        self.assertEqual(result["blocked"][0]["reason_head"], "有効な拒否")
        self.assertEqual(result["failures"][0]["count"], 2)

    def test_corrections_include_first_recent_message_after_old_first_message(self):
        self.write_log([self.human("最初の依頼", timestamp=OLD),
                        self.human("違う", timestamp=RECENT)])
        result = self.extract()
        self.assertEqual([item["text"] for item in result["corrections"]], ["違う"])
        self.assertEqual(result["corrections_total"], 1)

    def test_corrections_cwd_comes_from_each_message_record(self):
        self.write_log([self.human("最初の依頼", cwd="/tmp/initial-project"),
                        self.human("違う", cwd="/tmp/corrected-project")])
        corrections = self.extract()["corrections"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].get("cwd"), "/tmp/corrected-project")

    def test_corrections_cwd_defaults_to_empty_string_when_missing(self):
        self.write_log([self.human("最初の依頼", cwd="/tmp/initial-project"),
                        self.human("違う")])
        corrections = self.extract()["corrections"]
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].get("cwd"), "")

    def write_escaped_log(self, records):
        path = self.write_log([])
        mtime = path.stat().st_mtime
        path.write_text("".join(json.dumps(record) + "\n" for record in records),
                        encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_failure_with_unpaired_surrogate_outputs_valid_json(self):
        text = "失敗しました\ud83d"
        self.write_escaped_log(self.tool_result(text) + self.tool_result(text))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(len(output["failures"]), 1)
        self.assertEqual(output["failures"][0]["count"], 2)
        self.assertEqual(output["failures"][0]["examples"][0]["error"], text)

    def test_correction_with_unpaired_surrogate_outputs_valid_json(self):
        text = "違う\ud83d"
        self.write_escaped_log([self.human("最初の依頼"), self.human(text)])
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([item["text"] for item in output["corrections"]], [text])

    def test_failures_stringify_list_tool_name(self):
        tool = ["Read", "Search"]
        self.write_log(self.tool_result(tool=tool) + self.tool_result(tool=tool))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        failures = json.loads(result.stdout)["failures"]
        self.assertEqual([(group["tool"], group["command_key"], group["count"])
                          for group in failures], [(str(tool), str(tool), 2)])

    def test_failures_stringify_dict_tool_name(self):
        tool = {"name": "Read"}
        self.write_log(self.tool_result(tool=tool) + self.tool_result(tool=tool))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        failures = json.loads(result.stdout)["failures"]
        self.assertEqual([(group["tool"], group["command_key"], group["count"])
                          for group in failures], [(str(tool), str(tool), 2)])

    def test_numeric_timestamp_is_not_dropped(self):
        self.write_log(self.rejected("数値の時刻", timestamp=1))
        blocked = self.extract()["blocked"]
        self.assertEqual([(group["reason_head"], group["count"]) for group in blocked],
                         [("数値の時刻", 1)])

    def test_non_iso_timestamp_is_not_dropped(self):
        self.write_log(self.rejected("読めない時刻", timestamp="2026/11/15 12:00"))
        blocked = self.extract()["blocked"]
        self.assertEqual([(group["reason_head"], group["count"]) for group in blocked],
                         [("読めない時刻", 1)])

    def run_default_root_cli(self):
        env = os.environ.copy()
        env["HOME"] = str(self.root)
        return subprocess.run(
            ["python3", str(SCRIPT), "--now", NOW, "--days", "7"],
            env=env, capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def test_default_root_selects_claude_projects_when_only_it_exists(self):
        root = self.root / ".claude/projects"
        root.mkdir(parents=True)
        result = self.run_default_root_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["root"], str(root))

    def test_default_root_selects_mac_home_projects_when_only_it_exists(self):
        root = self.root / "mac_home/.claude/projects"
        root.mkdir(parents=True)
        result = self.run_default_root_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["root"], str(root))

    def test_default_root_prefers_claude_projects_when_both_exist(self):
        root = self.root / ".claude/projects"
        root.mkdir(parents=True)
        (self.root / "mac_home/.claude/projects").mkdir(parents=True)
        result = self.run_default_root_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["root"], str(root))

    def test_default_root_exits_with_code_two_when_neither_exists(self):
        result = self.run_default_root_cli()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
