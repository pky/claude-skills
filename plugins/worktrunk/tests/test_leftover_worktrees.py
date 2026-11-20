"""残っている worktree を記録する hook の公開入出力と登録を検証する。"""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "hooks/leftover-worktrees.py"
HOOKS = PLUGIN_ROOT / "hooks/hooks.json"


class LeftoverWorktreeTests(unittest.TestCase):
    branch = "feature/merged"

    def setUp(self):
        temporary_home = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(temporary_home.cleanup)
        self.home = Path(temporary_home.name).resolve()
        self.repo = self.home / "main repo"
        self.linked = self.home / "linked worktree"
        self.launch_dir = self.home / "launch"
        self.log = self.home / ".claude/hook-observe.log"
        self.gh_called = self.home / "gh-called"
        self.repo.mkdir()
        self.launch_dir.mkdir()

        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(
            '#!/bin/sh\n'
            ': > "$WT_TEST_GH_MARKER"\n'
            'printf "%s" "$WT_TEST_GH_OUTPUT"\n'
            'if [ "$WT_TEST_GH_STATUS" -ne 0 ]; then\n'
            '    printf "gh のテスト用エラー\\n" >&2\n'
            'fi\n'
            'exit "$WT_TEST_GH_STATUS"\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": os.pathsep.join((str(bin_dir), os.environ.get("PATH", os.defpath))),
            "WT_TEST_GH_MARKER": str(self.gh_called),
        })

        self.git("init", "--initial-branch=main")
        self.git("config", "--local", "user.name", "Worktree Test")
        self.git("config", "--local", "user.email", "worktree@example.invalid")
        self.head = self.commit(self.repo, "初期コミット")

    def git(self, *args, cwd=None):
        result = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.environment,
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, cwd, message):
        self.git("commit", "--allow-empty", "-m", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def add_worktree(self):
        self.git("worktree", "add", "-b", self.branch, str(self.linked))

    def merged_pr(self, head=None, *, branch=None):
        return {
            "number": 23,
            "headRefName": branch or self.branch,
            "headRefOid": head or self.head,
            "url": "https://example.invalid/repo/pull/23",
        }

    def run_raw(self, raw, *, gh_output="[]", gh_status=0):
        self.gh_called.unlink(missing_ok=True)
        environment = self.environment.copy()
        environment["WT_TEST_GH_OUTPUT"] = gh_output
        environment["WT_TEST_GH_STATUS"] = str(gh_status)
        result = subprocess.run(
            ["python3", str(SCRIPT)], input=raw, cwd=self.launch_dir,
            env=environment, capture_output=True, text=True, encoding="utf-8",
            timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def run_hook(self, *prs, cwd=None):
        self.run_raw(json.dumps({"cwd": str(cwd or self.repo)}),
                     gh_output=json.dumps(prs))

    def read_log(self):
        self.assertTrue(self.log.is_file(), "観測ログが作成されていない")
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_matching_head_logs_worktree(self):
        self.add_worktree()
        pr = self.merged_pr()

        self.run_hook(pr, cwd=self.linked)

        self.assertTrue(self.gh_called.is_file())
        records = self.read_log()
        self.assertEqual(len(records), 1)
        record = records[0]
        timestamp = record.pop("time")
        self.assertRegex(
            timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})\Z",
        )
        self.assertIsNotNone(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset())
        self.assertEqual(record, {
            "hook": "wt-leftover",
            "repo": str(self.repo),
            "worktree": str(self.linked),
            "branch": self.branch,
            "pr": pr["number"],
            "url": pr["url"],
            "in_session_cwd": True,
        })

    def test_session_cwd_in_worktree_subdirectory(self):
        self.add_worktree()
        subdirectory = self.linked / "subdirectory"
        subdirectory.mkdir()

        self.run_hook(self.merged_pr(), cwd=subdirectory)

        records = self.read_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["worktree"], str(self.linked))
        self.assertIs(records[0]["in_session_cwd"], True)

    def test_session_cwd_in_main_worktree(self):
        self.add_worktree()

        self.run_hook(self.merged_pr(), cwd=self.repo)

        records = self.read_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["worktree"], str(self.linked))
        self.assertIs(records[0]["in_session_cwd"], False)

    def test_session_cwd_in_worktree_with_same_path_prefix(self):
        self.add_worktree()
        other_worktree = self.linked.with_name(self.linked.name + "-other")
        self.git("worktree", "add", "-b", "feature/other", str(other_worktree))

        self.run_hook(self.merged_pr(), cwd=other_worktree)

        records = self.read_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["worktree"], str(self.linked))
        self.assertIs(records[0]["in_session_cwd"], False)

    def test_local_head_is_ancestor_of_pr_head(self):
        self.add_worktree()
        self.git("worktree", "add", "--detach", str(self.home / "pr"))
        pr_head = self.commit(self.home / "pr", "PR に追加されたコミット")

        self.run_hook(self.merged_pr(pr_head))

        records = self.read_log()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["worktree"], str(self.linked))

    def test_local_head_ahead_of_pr_head_is_not_logged(self):
        self.add_worktree()
        self.commit(self.linked, "マージ後のローカルコミット")

        self.run_hook(self.merged_pr())

        self.assertTrue(self.gh_called.is_file())
        self.assertFalse(self.log.exists())

    def test_pr_head_missing_locally_is_not_logged(self):
        self.add_worktree()
        self.run_hook(self.merged_pr("f" * len(self.head)))

        self.assertTrue(self.gh_called.is_file())
        self.assertFalse(self.log.exists())

    def test_pr_for_another_branch_is_not_logged(self):
        self.add_worktree()
        self.run_hook(self.merged_pr(branch="feature/other"))

        self.assertTrue(self.gh_called.is_file())
        self.assertFalse(self.log.exists())

    def test_main_worktree_is_not_logged_even_if_its_pr_matches(self):
        self.add_worktree()
        self.run_hook(self.merged_pr(branch="main"))

        self.assertTrue(self.gh_called.is_file())
        self.assertFalse(self.log.exists())

    def test_detached_worktree_does_not_trigger_gh(self):
        self.git("worktree", "add", "--detach", str(self.linked))
        self.run_hook(self.merged_pr())

        self.assertFalse(self.gh_called.exists())
        self.assertFalse(self.log.exists())

    def test_main_worktree_alone_does_not_trigger_gh(self):
        self.run_hook(self.merged_pr(branch="main"))

        self.assertFalse(self.gh_called.exists())
        self.assertFalse(self.log.exists())

    def test_cwd_outside_git_does_not_trigger_gh(self):
        self.add_worktree()
        non_repo = self.home / "non-repo"
        non_repo.mkdir()
        self.run_hook(self.merged_pr(), cwd=non_repo)

        self.assertFalse(self.gh_called.exists())
        self.assertFalse(self.log.exists())

    def test_gh_failure_or_invalid_json_is_silent(self):
        self.add_worktree()
        raw = json.dumps({"cwd": str(self.repo)})
        for gh_status, gh_output in ((1, json.dumps([self.merged_pr()])), (0, "not JSON")):
            with self.subTest(gh_status=gh_status):
                self.run_raw(raw, gh_output=gh_output, gh_status=gh_status)
                self.assertTrue(self.gh_called.is_file())
                self.assertFalse(self.log.exists())

    def test_invalid_json_or_missing_cwd_is_silent(self):
        for raw in ("{invalid json", "{}"):
            with self.subTest(raw=raw):
                self.run_raw(raw)
                self.assertFalse(self.gh_called.exists())
                self.assertFalse(self.log.exists())

    def test_existing_log_is_preserved_when_new_record_is_appended(self):
        self.add_worktree()
        self.log.parent.mkdir()
        previous_line = json.dumps({"hook": "another-hook", "time": "2026-01-01T00:00:00Z"})
        self.log.write_text(previous_line + "\n", encoding="utf-8")

        self.run_hook(self.merged_pr())

        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], previous_line)
        self.assertEqual(json.loads(lines[1])["worktree"], str(self.linked))


class HookRegistrationTests(unittest.TestCase):
    def test_session_start_registers_existing_python_script(self):
        self.assertTrue(HOOKS.is_file(), f"{HOOKS} が存在しない")
        config = json.loads(HOOKS.read_text(encoding="utf-8"))
        self.assertEqual(len(config["description"].strip().splitlines()), 1)
        args = ["${CLAUDE_PLUGIN_ROOT}/hooks/leftover-worktrees.py"]
        for entry in config["hooks"]["SessionStart"]:
            if entry["matcher"] != "startup|resume":
                continue
            for hook in entry["hooks"]:
                if hook["type"] == "command" and hook["command"] == "python3" and hook["args"] == args:
                    self.assertEqual(hook["timeout"], 15)
                    script = Path(hook["args"][0].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT)))
                    self.assertTrue(script.is_file(), f"{script} が存在しない")
                    return
        self.fail("startup と resume で leftover-worktrees.py を起動する登録がない")


if __name__ == "__main__":
    unittest.main()
