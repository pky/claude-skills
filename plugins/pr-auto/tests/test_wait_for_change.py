"""PR の監視スクリプトを偽の gh で検証する。"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills/babysit"
SCRIPT = SKILL_ROOT / "scripts/wait-for-change"
PR_VIEW_ARGS = [
    "pr", "view", "23", "--repo", "example/project", "--json",
    "headRefOid,statusCheckRollup,reviews,comments",
]
GRAPHQL_ARGS = [
    "api", "graphql", "-F", f"query=@{SKILL_ROOT / 'review-threads.graphql'}",
    "-f", "owner=example", "-f", "repo=project", "-F", "number=23",
]
OLD_HEAD = "a" * 40
NEW_HEAD = "b" * 40
FIRST_COMMENT = "2026-11-24T01:00:00Z"
LATEST_COMMENT = "2026-11-24T02:00:00Z"

FAKE_GH = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

directory = Path(os.environ["WAIT_FOR_CHANGE_TEST_DIR"])
log = directory / "gh-calls.jsonl"
state = directory / "PR state.json"
args = sys.argv[1:]
kind = {("pr", "view"): "pr_view", ("api", "graphql"): "graphql"}.get(tuple(args[:2]))
previous_calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "argv": args,
        "kind": kind,
        "state": state.read_text(encoding="utf-8") if state.exists() else None,
    }) + "\\n")
if kind is None:
    sys.exit("想定外の gh コマンド")

index = sum(json.loads(line)["kind"] == kind for line in previous_calls)
responses = json.loads((directory / f"{kind}.json").read_text(encoding="utf-8"))
if index >= len(responses):
    sys.exit(f"{kind} の応答を使い切った")

response = responses[index]
sys.stdout.write(response["stdout"])
sys.stderr.write(response.get("stderr", ""))
sys.exit(response.get("status", 0))
"""


def pr_view(*, head=OLD_HEAD, checks=(), reviews=(), comments=()):
    return {
        "headRefOid": head,
        "statusCheckRollup": list(checks),
        "reviews": list(reviews),
        "comments": list(comments),
    }


def check_run(name, status, conclusion):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def status_context(context, state):
    return {"__typename": "StatusContext", "context": context, "state": state}


def thread(thread_id, created_at=None, *, resolved=False):
    comments = [] if created_at is None else [{"createdAt": created_at}]
    return {"id": thread_id, "isResolved": resolved, "comments": {"nodes": comments}}


def graphql_page(*threads, cursor=None):
    review_threads = {
        "nodes": list(threads),
        "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
    }
    return {"data": {"repository": {"pullRequest": {"reviewThreads": review_threads}}}}


def response(payload):
    return {"stdout": json.dumps(payload)}


def saved_state(*, head=OLD_HEAD, checks=(), threads=(), reviews=0, comments=0):
    return {
        "head": head,
        "checks": list(checks),
        "threads": list(threads),
        "reviews": reviews,
        "comments": comments,
    }


class WaitForChangeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.state_file = self.directory / "PR state.json"
        self.call_log = self.directory / "gh-calls.jsonl"
        bin_dir = self.directory / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update({
            "PATH": os.pathsep.join((str(bin_dir), os.environ.get("PATH", os.defpath))),
            "WAIT_FOR_CHANGE_TEST_DIR": str(self.directory),
        })

    def run_wait(self, *, pr, graphql, max_failures=None):
        self.call_log.unlink(missing_ok=True)
        for kind, responses in (("pr_view", pr), ("graphql", graphql)):
            (self.directory / f"{kind}.json").write_text(json.dumps(responses), encoding="utf-8")
        args = [
            str(SCRIPT), "--repo", "example/project", "--pr", "23", "--state",
            str(self.state_file), "--interval", "0",
        ]
        if max_failures is not None:
            args.extend(("--max-failures", str(max_failures)))
        return subprocess.run(
            args, cwd=self.directory, env=self.environment, capture_output=True,
            text=True, encoding="utf-8", timeout=10, check=False,
        )

    def write_state(self, state):
        raw = json.dumps(state, indent=2) + "\n"
        self.state_file.write_text(raw, encoding="utf-8")
        return raw

    def read_state(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def read_calls(self):
        return [
            json.loads(line)
            for line in self.call_log.read_text(encoding="utf-8").splitlines()
        ]

    def assert_success(self, result, line):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, line + "\n")

    def test_reports_all_changed_fields_in_order_and_saves_them(self):
        self.write_state(saved_state())
        result = self.run_wait(
            pr=[response(pr_view(
                head=NEW_HEAD, checks=[check_run("build", "COMPLETED", "FAILURE")],
                reviews=[{"id": "R1"}], comments=[{"id": "C1"}, {"id": "C2"}],
            ))],
            graphql=[response(graphql_page(thread("T1", LATEST_COMMENT)))],
        )

        self.assert_success(result, "changed: head,checks,threads,reviews,comments")
        self.assertEqual(self.read_state(), saved_state(
            head=NEW_HEAD, checks=[["build", "COMPLETED", "FAILURE"]],
            threads=[["T1", LATEST_COMMENT]], reviews=1, comments=2,
        ))

    def test_reports_each_changed_field_independently(self):
        initial_checks = [check_run("build", "IN_PROGRESS", None), status_context("lint", "PENDING")]
        initial_thread = thread("T1", FIRST_COMMENT)
        old = saved_state(
            checks=[["build", "IN_PROGRESS", ""], ["lint", "PENDING", ""]],
            threads=[["T1", FIRST_COMMENT]],
        )
        cases = [
            ("head", {"head": NEW_HEAD}, initial_thread, {"head": NEW_HEAD}),
            ("checks", {"checks": [check_run("build", "COMPLETED", None), initial_checks[1]]},
             initial_thread, {"checks": [["build", "COMPLETED", ""], ["lint", "PENDING", ""]]}),
            ("checks", {"checks": [check_run("build", "IN_PROGRESS", "FAILURE"), initial_checks[1]]},
             initial_thread, {"checks": [["build", "IN_PROGRESS", "FAILURE"], ["lint", "PENDING", ""]]}),
            ("checks", {"checks": [initial_checks[0], status_context("lint", "SUCCESS")]},
             initial_thread, {"checks": [["build", "IN_PROGRESS", ""], ["lint", "SUCCESS", ""]]}),
            ("threads", {}, thread("T1", LATEST_COMMENT), {"threads": [["T1", LATEST_COMMENT]]}),
            ("threads", {}, thread("T1", FIRST_COMMENT, resolved=True), {"threads": []}),
            ("reviews", {"reviews": [{"id": "R1"}]}, initial_thread, {"reviews": 1}),
            ("comments", {"comments": [{"id": "C1"}]}, initial_thread, {"comments": 1}),
        ]

        for field, pr_changes, current_thread, expected_changes in cases:
            with self.subTest(field=field, expected=expected_changes):
                self.write_state(old)
                pr_fields = {"checks": initial_checks, **pr_changes}
                result = self.run_wait(
                    pr=[response(pr_view(**pr_fields))],
                    graphql=[response(graphql_page(current_thread))],
                )

                self.assert_success(result, f"changed: {field}")
                self.assertEqual(self.read_state(), {**old, **expected_changes})

    def test_polls_silently_while_only_order_and_resolved_threads_change(self):
        checks = [check_run("build", "COMPLETED", "SUCCESS"), status_context("lint", "SUCCESS")]
        first_thread = thread("T1", FIRST_COMMENT)
        second_thread = thread("T2")
        old = saved_state(
            checks=[["build", "COMPLETED", "SUCCESS"], ["lint", "SUCCESS", ""]],
            threads=[["T1", FIRST_COMMENT], ["T2", ""]],
        )
        original = self.write_state(old)
        result = self.run_wait(
            pr=[
                response(pr_view(checks=checks)),
                response(pr_view(checks=checks[::-1])),
                response(pr_view(head=NEW_HEAD, checks=checks)),
            ],
            graphql=[
                response(graphql_page(first_thread, second_thread, thread("T3", FIRST_COMMENT, resolved=True))),
                response(graphql_page(second_thread, thread("T4", LATEST_COMMENT, resolved=True), first_thread)),
                response(graphql_page(first_thread, second_thread)),
            ],
        )

        self.assert_success(result, "changed: head")
        self.assertEqual(self.read_state(), {**old, "head": NEW_HEAD})
        calls = self.read_calls()
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "pr_view"], [PR_VIEW_ARGS] * 3)
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "graphql"], [GRAPHQL_ARGS] * 3)
        self.assertEqual([call["state"] for call in calls], [original] * 6)

    def test_initializes_state_from_all_pages_and_passes_gh_arguments(self):
        result = self.run_wait(
            pr=[response(pr_view(
                checks=[status_context("lint", "SUCCESS"), status_context("empty", None),
                        check_run("build", None, None)],
                reviews=[{"id": "R1"}, {"id": "R2"}], comments=[{"id": "C1"}],
            ))],
            graphql=[
                response(graphql_page(thread("T2"), cursor="page-two")),
                response(graphql_page(thread("T1", LATEST_COMMENT), thread("T3", FIRST_COMMENT, resolved=True))),
            ],
        )

        self.assert_success(result, f"initial: {self.state_file}")
        self.assertEqual(self.read_state(), saved_state(
            checks=[["build", "", ""], ["empty", "", ""], ["lint", "SUCCESS", ""]],
            threads=[["T1", LATEST_COMMENT], ["T2", ""]], reviews=2, comments=1,
        ))
        calls = self.read_calls()
        self.assertEqual(len(calls), 3)
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "pr_view"], [PR_VIEW_ARGS])
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "graphql"], [
            GRAPHQL_ARGS, [*GRAPHQL_ARGS, "-f", "cursor=page-two"],
        ])
        self.assertEqual([call["state"] for call in calls], [None] * 3)

    def test_retries_after_failed_page_without_saving_partial_state(self):
        original = self.write_state(saved_state())
        result = self.run_wait(
            pr=[response(pr_view(head=NEW_HEAD))] * 2,
            graphql=[
                response(graphql_page(thread("T1", FIRST_COMMENT), cursor="page-two")),
                {"stdout": "", "stderr": "一時的な通信エラー\n", "status": 1},
                response(graphql_page()),
            ],
            max_failures=2,
        )

        self.assert_success(result, "changed: head")
        self.assertEqual(self.read_state(), saved_state(head=NEW_HEAD))
        calls = self.read_calls()
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "graphql"], [
            GRAPHQL_ARGS, [*GRAPHQL_ARGS, "-f", "cursor=page-two"], GRAPHQL_ARGS,
        ])
        self.assertEqual([call["state"] for call in calls], [original] * len(calls))

    def test_successful_poll_resets_consecutive_failures(self):
        original = self.write_state(saved_state())
        result = self.run_wait(
            pr=[response(pr_view())] * 4,
            graphql=[
                {"stdout": "invalid JSON"},
                response(graphql_page()),
                {"stdout": "", "status": 1},
                response(graphql_page(thread("T1", LATEST_COMMENT))),
            ],
            max_failures=2,
        )

        self.assert_success(result, "changed: threads")
        self.assertEqual(self.read_state(), saved_state(threads=[["T1", LATEST_COMMENT]]))
        calls = self.read_calls()
        self.assertEqual([call["argv"] for call in calls if call["kind"] == "graphql"], [GRAPHQL_ARGS] * 4)
        self.assertEqual([call["state"] for call in calls], [original] * len(calls))

    def test_exits_after_consecutive_failures_and_preserves_state(self):
        failures = [
            {"stdout": "invalid JSON"},
            {"stdout": "", "stderr": "一時的な通信エラー\n", "status": 17},
            {"stdout": "", "stderr": "接続が切断された\n追加の詳細\n", "status": 42},
        ]
        for max_failures, replies in ((None, failures), (2, failures[1:])):
            with self.subTest(max_failures=max_failures):
                original = self.write_state(saved_state())
                result = self.run_wait(
                    pr=[response(pr_view(head=NEW_HEAD))] * len(replies),
                    graphql=replies,
                    max_failures=max_failures,
                )

                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertRegex(result.stdout, r"\Aerror: \S[^\n]*\n\Z")
                self.assertRegex(result.stdout, r"接続が切断された|\b42\b")
                self.assertEqual(self.state_file.read_text(encoding="utf-8"), original)
                calls = self.read_calls()
                graphql_calls = [call["argv"] for call in calls if call["kind"] == "graphql"]
                self.assertEqual(graphql_calls, [GRAPHQL_ARGS] * len(replies))
                self.assertEqual([call["state"] for call in calls], [original] * len(calls))


if __name__ == "__main__":
    unittest.main()
