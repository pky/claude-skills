#!/usr/bin/env python3
import json
import os
import re
import sys


def main():
    try:
        event = json.load(sys.stdin)
        fields = {
            "Bash": ("command",),
            "Read": ("file_path",),
            "Edit": ("file_path",),
            "Write": ("file_path",),
            "NotebookEdit": ("file_path", "notebook_path"),
            "Grep": ("path",),
            "Glob": ("path",),
        }.get(event["tool_name"], ())
        tool_input = event["tool_input"]
        if not fields or not isinstance(tool_input, dict):
            return

        source = os.path.join(os.environ["HOME"], ".claude")
        real = os.path.realpath(source)
        if real == source:
            return

        pattern = re.compile(
            re.escape(source) + r"(?=/|$)"
            r"|~/\.claude(?=/|$|[\s\"';&|()<>`])"
            r"|(?:\$HOME|\$\{HOME\})/\.claude(?=/)"
        )
        for field in fields:
            value = tool_input.get(field)
            if not isinstance(value, str):
                continue
            if event["tool_name"] != "Bash" and value.startswith(tuple(
                prefix + "/projects/"
                for prefix in (source, "~/.claude", "$HOME/.claude", "${HOME}/.claude")
            )):
                continue
            rewritten, count = pattern.subn(lambda match: real, value)
            if not count:
                continue
            reason = (
                f"~/.claude は {real} へのリンクで、リンクのパスでは読めない。"
                f"{real} のパスで呼び直す: {rewritten[:200]}"
            )
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            }, ensure_ascii=False))
            return
    except Exception:
        # 入力やパスの異常で Claude の作業を止めない。
        return


if __name__ == "__main__":
    main()
