#!/usr/bin/env python3
import json
import os
import shlex
import sys


def at_or_under(path, directory):
    return path == directory or path.startswith(directory + "/")


def read_uses_link(value, home, source):
    for prefix in ("~", "$HOME", "${HOME}"):
        if value == prefix or value.startswith(prefix + "/"):
            value = home + value[len(prefix):]
            break
    path = os.path.normpath(value)
    source = os.path.normpath(source)
    return (at_or_under(path, source)
            and not at_or_under(path, os.path.join(source, "projects")))


def bash_uses_link(command, source):
    lexer = shlex.shlex(command, posix=False, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        # 後半に閉じていない引用符がある場合も、判定前に検出する。
        words = list(lexer)
    except ValueError:
        return False

    for word in words:
        quote = ""
        if word[:1] in ("'", '"') and word[-1:] == word[:1]:
            quote = word[0]
            word = word[1:-1]
        prefixes = [source]
        if quote != "'":
            prefixes.extend(("$HOME/.claude", "${HOME}/.claude"))
        if not quote:
            prefixes.append("~/.claude")
        if any(at_or_under(word, prefix) for prefix in prefixes):
            return True
    return False


def main():
    try:
        event = json.load(sys.stdin)
        fields = {
            "Bash": ("command",),
            "Read": ("file_path",),
            "Grep": ("path",),
            "Glob": ("path", "pattern"),
        }.get(event["tool_name"], ())
        tool_input = event["tool_input"]
        if not fields or not isinstance(tool_input, dict):
            return

        home = os.environ.get("HOME")
        if not home:
            return
        source = os.path.join(home, ".claude")
        real = os.path.realpath(source)
        if real == os.path.join(os.path.realpath(home), ".claude"):
            return

        for field in fields:
            value = tool_input.get(field)
            if not isinstance(value, str):
                continue
            if event["tool_name"] == "Bash":
                blocked = bash_uses_link(value, source)
            else:
                blocked = read_uses_link(value, home, source)
            if not blocked:
                continue
            reason = (
                f"~/.claude は {real} へのリンクで、リンクのパスでは読めない。"
                f"{real} の下の同じパスで呼び直す"
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
