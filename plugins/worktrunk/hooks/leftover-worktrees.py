#!/usr/bin/env python3
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys


BRANCH_PREFIX = "refs/heads/"


def list_worktrees(cwd):
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=cwd, capture_output=True, encoding="utf-8", errors="surrogateescape",
        timeout=5, check=True,
    )
    worktrees = []
    for block in result.stdout.strip("\n").split("\n\n"):
        fields = {}
        for line in block.split("\n"):
            key, _, value = line.partition(" ")
            fields[key] = value
        worktrees.append(fields)
    return worktrees


def local_head_is_ancestor(cwd, branch_ref, pr_head):
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch_ref, pr_head],
            cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, timeout=5, check=False,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main():
    try:
        cwd = json.load(sys.stdin)["cwd"]
        if not cwd or not Path(cwd).is_dir():
            return

        main_worktree, *linked_worktrees = list_worktrees(cwd)
        candidates = [
            worktree for worktree in linked_worktrees
            if worktree.get("branch", "").startswith(BRANCH_PREFIX)
            and "detached" not in worktree and "prunable" not in worktree
        ]
        if not candidates:
            return

        result = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "200",
             "--json", "number,headRefName,headRefOid,url"],
            cwd=cwd, capture_output=True, encoding="utf-8", timeout=8, check=True,
        )
        merged_prs = json.loads(result.stdout)
        log = Path(os.environ["HOME"]) / ".claude" / "hook-observe.log"
        session_cwd = Path(cwd).resolve()

        for worktree in candidates:
            branch_ref = worktree["branch"]
            branch = branch_ref[len(BRANCH_PREFIX):]
            for pr in merged_prs:
                if pr["headRefName"] != branch:
                    continue
                if not local_head_is_ancestor(cwd, branch_ref, pr["headRefOid"]):
                    continue

                worktree_path = Path(worktree["worktree"]).resolve()
                record = {
                    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "hook": "wt-leftover",
                    "repo": main_worktree["worktree"],
                    "worktree": worktree["worktree"],
                    "branch": branch,
                    "pr": pr["number"],
                    "url": pr["url"],
                    "in_session_cwd": session_cwd == worktree_path or worktree_path in session_cwd.parents,
                }
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
                break
    except Exception:
        # 入力や外部コマンド、ログの異常で Claude の作業を止めない。
        return


if __name__ == "__main__":
    main()
