"""guard hook の公開入出力と登録内容を検証する。"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "hooks/claude-path-guard.py"
HOOKS = PLUGIN_ROOT / "hooks/hooks.json"
CONTEXT = PLUGIN_ROOT / "context/reply-short.md"


class ClaudePathGuardTests(unittest.TestCase):
    def setUp(self):
        temporary_home = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temporary_home.cleanup)
        self.home = Path(temporary_home.name).resolve()
        self.real = self.home / "real/.claude"
        self.real.mkdir(parents=True)
        self.link = self.home / ".claude"
        self.link.symlink_to(self.real, target_is_directory=True)

    def run_raw(self, raw):
        environment = os.environ.copy()
        environment["HOME"] = str(self.home)
        result = subprocess.run(
            ["python3", str(SCRIPT)], input=raw, env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def run_guard(self, tool_name, tool_input):
        return self.run_raw(json.dumps({
            "tool_name": tool_name, "tool_input": tool_input,
        }))

    def denied(self, tool_name, field, value, rewritten):
        output = json.loads(self.run_guard(tool_name, {field: value}))
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        reason = specific["permissionDecisionReason"]
        self.assertIsInstance(reason, str)
        self.assertIn(str(self.real), reason)
        self.assertIn(rewritten, reason)
        return reason

    def test_bash_absolute_path_is_denied(self):
        self.denied("Bash", "command", f"cat {self.link}/settings.json",
                    f"cat {self.real}/settings.json")

    def test_bash_tilde_path_is_denied(self):
        self.denied("Bash", "command", "cat ~/.claude/settings.json",
                    f"cat {self.real}/settings.json")

    def test_bash_home_variable_path_is_denied(self):
        self.denied("Bash", "command", "cat $HOME/.claude/x",
                    f"cat {self.real}/x")

    def test_bash_braced_home_variable_path_is_denied(self):
        self.denied("Bash", "command", "cat ${HOME}/.claude/x",
                    f"cat {self.real}/x")

    def test_bash_absolute_directory_at_end_is_denied(self):
        self.denied("Bash", "command", f"ls {self.link}", f"ls {self.real}")

    def test_bash_tilde_directory_at_end_is_denied(self):
        self.denied("Bash", "command", "ls ~/.claude", f"ls {self.real}")

    def test_bash_tilde_directory_word_before_option_is_denied(self):
        self.denied("Bash", "command", "ls ~/.claude -la", f"ls {self.real} -la")

    def test_bash_all_spellings_are_rewritten(self):
        command = (f"cat {self.link}/a ~/.claude/b "
                   "$HOME/.claude/c ${HOME}/.claude/d")
        rewritten = (f"cat {self.real}/a {self.real}/b "
                     f"{self.real}/c {self.real}/d")
        # 全書式の置換を、200文字の切り詰めとは独立して確かめる。
        self.assertLessEqual(len(rewritten), 200)
        self.denied("Bash", "command", command, rewritten)

    def test_bash_repeated_path_is_rewritten_every_time(self):
        self.denied("Bash", "command", "cat ~/.claude/a ~/.claude/a",
                    f"cat {self.real}/a {self.real}/a")

    def test_read_file_path_is_denied(self):
        self.denied("Read", "file_path", f"{self.link}/a", f"{self.real}/a")

    def test_grep_path_is_denied(self):
        self.denied("Grep", "path", f"{self.link}/a", f"{self.real}/a")

    def test_glob_path_is_denied(self):
        self.denied("Glob", "path", f"{self.link}/a", f"{self.real}/a")

    def test_edit_file_path_is_denied(self):
        self.denied("Edit", "file_path", f"{self.link}/a", f"{self.real}/a")

    def test_write_file_path_is_denied(self):
        self.denied("Write", "file_path", f"{self.link}/a", f"{self.real}/a")

    def test_notebook_edit_notebook_path_is_denied(self):
        self.denied("NotebookEdit", "notebook_path", f"{self.link}/a.ipynb",
                    f"{self.real}/a.ipynb")

    def test_notebook_edit_file_path_is_denied(self):
        self.denied("NotebookEdit", "file_path", f"{self.link}/a.ipynb",
                    f"{self.real}/a.ipynb")

    def test_read_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": f"{self.link}/projects/p/memory/a.md"}), "")

    def test_write_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Write", {"file_path": f"{self.link}/projects/p/memory/a.md"}), "")

    def test_edit_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Edit", {"file_path": f"{self.link}/projects/p/memory/a.md"}), "")

    def test_read_tilde_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": "~/.claude/projects/p/a.md"}), "")

    def test_read_home_variable_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": "$HOME/.claude/projects/p/a.md"}), "")

    def test_read_braced_home_variable_projects_file_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": "${HOME}/.claude/projects/p/a.md"}), "")

    def test_grep_projects_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Grep", {"path": f"{self.link}/projects/p"}), "")

    def test_glob_projects_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Glob", {"path": f"{self.link}/projects/p"}), "")

    def test_notebook_edit_projects_notebook_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "NotebookEdit", {"notebook_path": f"{self.link}/projects/p/a.ipynb"}), "")

    def test_bash_projects_path_is_denied(self):
        self.denied("Bash", "command", "cat ~/.claude/projects/p/a.md",
                    f"cat {self.real}/projects/p/a.md")

    def test_read_similar_projects_directory_name_is_denied(self):
        self.denied("Read", "file_path", f"{self.link}/projectsX/a",
                    f"{self.real}/projectsX/a")

    def test_read_settings_file_path_is_denied(self):
        self.denied("Read", "file_path", f"{self.link}/settings.json",
                    f"{self.real}/settings.json")

    def test_absolute_path_with_similar_directory_name_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Bash", {"command": f"cat {self.home}/.claudeX/a"}), "")

    def test_tilde_path_with_similar_directory_name_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Bash", {"command": "cat ~/.claudeX/a"}), "")

    def test_real_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Bash", {"command": f"cat {self.real}/settings.json"}), "")

    def test_unrelated_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": str(self.home / "project/a")}), "")

    def test_read_real_path_is_allowed(self):
        self.assertEqual(self.run_guard(
            "Read", {"file_path": f"{self.real}/settings.json"}), "")

    def test_regular_claude_directory_produces_no_output(self):
        self.link.unlink()
        self.link.mkdir()
        self.assertEqual(self.run_guard(
            "Bash", {"command": f"cat {self.link}/settings.json"}), "")

    def test_missing_claude_directory_produces_no_output(self):
        self.link.unlink()
        self.assertEqual(self.run_guard(
            "Bash", {"command": "cat ~/.claude/settings.json"}), "")

    def test_rewritten_command_is_truncated_at_200_characters(self):
        command = "cat ~/.claude/" + "あ" * 210
        rewritten = f"cat {self.real}/" + "あ" * 210
        reason = self.denied("Bash", "command", command, rewritten[:200])
        self.assertTrue(reason.endswith(rewritten[:200]))
        self.assertNotIn(rewritten[:201], reason)

    def test_rewritten_command_of_200_characters_is_preserved(self):
        prefix = f"cat {self.real}/"
        suffix = "x" * (200 - len(prefix))
        reason = self.denied("Bash", "command", "cat ~/.claude/" + suffix,
                             prefix + suffix)
        self.assertTrue(reason.endswith(prefix + suffix))

    def test_invalid_json_produces_no_output(self):
        self.assertEqual(self.run_raw("{invalid json"), "")

    def test_empty_input_produces_no_output(self):
        self.assertEqual(self.run_raw(""), "")

    def test_missing_tool_input_produces_no_output(self):
        self.assertEqual(self.run_raw(json.dumps({"tool_name": "Bash"})), "")

    def test_missing_command_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", {}), "")

    def test_numeric_command_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", {"command": 42}), "")

    def test_null_command_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", {"command": None}), "")

    def test_list_command_produces_no_output(self):
        self.assertEqual(self.run_guard(
            "Bash", {"command": ["cat", "~/.claude/a"]}), "")

    def test_object_command_produces_no_output(self):
        self.assertEqual(self.run_guard(
            "Bash", {"command": {"path": "~/.claude/a"}}), "")

    def test_null_tool_input_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", None), "")

    def test_list_tool_input_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", []), "")

    def test_string_tool_input_produces_no_output(self):
        self.assertEqual(self.run_guard("Bash", "~/.claude/a"), "")

    def test_non_object_json_produces_no_output(self):
        self.assertEqual(self.run_raw("[]"), "")

    def test_non_string_file_path_produces_no_output(self):
        self.assertEqual(self.run_guard("Read", {"file_path": 42}), "")

    def test_unrelated_input_field_produces_no_output(self):
        self.assertEqual(self.run_guard("Read", {"command": "cat ~/.claude/a"}), "")

    def test_output_is_one_json_object(self):
        output = json.loads(self.run_guard("Bash", {"command": "cat ~/.claude/a"}))
        self.assertIsInstance(output, dict)
        self.assertIsInstance(output["hookSpecificOutput"], dict)

    def test_output_event_name_is_pre_tool_use(self):
        output = json.loads(self.run_guard("Bash", {"command": "cat ~/.claude/a"}))
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_output_permission_decision_is_deny(self):
        output = json.loads(self.run_guard("Bash", {"command": "cat ~/.claude/a"}))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")


class HookRegistrationTests(unittest.TestCase):
    def read_hooks(self):
        return json.loads(HOOKS.read_text(encoding="utf-8"))

    def command_tokens(self, hook):
        # 既存プラグインの command + args と、単一の command の両方を扱う。
        return shlex.split(hook["command"]) + hook.get("args", [])

    def test_hooks_file_is_json_object(self):
        self.assertIsInstance(self.read_hooks(), dict)

    def test_pre_tool_use_matcher_matches_specification(self):
        entries = self.read_hooks()["hooks"]["PreToolUse"]
        self.assertEqual([entry["matcher"] for entry in entries], [
            "Read|Grep|Glob|Bash|Edit|Write|NotebookEdit",
        ])

    def test_pre_tool_use_calls_guard_script(self):
        entries = self.read_hooks()["hooks"]["PreToolUse"]
        target = "${CLAUDE_PLUGIN_ROOT}/hooks/claude-path-guard.py"
        commands = [self.command_tokens(hook) for entry in entries
                    for hook in entry["hooks"] if hook["type"] == "command"]
        self.assertTrue(any(
            tokens == [target] or
            (len(tokens) == 2 and Path(tokens[0]).name == "python3"
             and tokens[1] == target)
            for tokens in commands
        ), commands)

    def test_user_prompt_submit_cats_reply_context(self):
        entries = self.read_hooks()["hooks"]["UserPromptSubmit"]
        commands = [self.command_tokens(hook) for entry in entries
                    for hook in entry["hooks"] if hook["type"] == "command"]
        self.assertIn(["cat", "${CLAUDE_PLUGIN_ROOT}/context/reply-short.md"], commands)


class ReplyShortTests(unittest.TestCase):
    def test_reply_context_exists(self):
        self.assertTrue(CONTEXT.is_file())

    def test_reply_context_requires_conclusion_on_first_line(self):
        self.assertIn("1行目に結論", CONTEXT.read_text(encoding="utf-8"))

    def test_reply_context_requires_at_most_five_lines(self):
        self.assertIn("5行以内", CONTEXT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
