#!/usr/bin/env python3
"""会話記録から拒否された操作、繰り返す失敗、訂正候補を抽出する。"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shlex
import sys


HINTS = (
    "違う", "ちがう", "じゃなく", "ではなく", "しないで", "やめて", "なんで",
    "なぜ", "言った", "勝手", "戻して", "聞いてない", "ダメ", "だめ",
)


def parse_time(value):
    """ISO 8601 の時刻を比較可能な UTC にそろえる。"""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


def reason_head(reason):
    line = next((line for line in reason.splitlines() if line.strip()), "")
    return re.sub(r"\d", "#", line[:80])


def summarize_input(tool, tool_input):
    if isinstance(tool_input, dict) and tool == "Bash":
        summary = tool_input.get("command", "")
    elif isinstance(tool_input, dict) and "file_path" in tool_input:
        summary = tool_input["file_path"]
    else:
        summary = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
    return str(summary)[:200]


def command_key(tool, tool_input):
    if tool != "Bash":
        return tool
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str):
        return tool
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    while tokens and tokens[0] == "cd" and "&&" in tokens:
        tokens = tokens[tokens.index("&&") + 1:]
    if not tokens:
        return tool
    key = os.path.basename(tokens[0])
    if len(tokens) > 1 and not tokens[1].startswith("-") and tokens[1] not in (
        "&&", "||", ";", "|", "&",
    ):
        key += " " + tokens[1]
    return key


def add_group(groups, key, fields, example):
    if key not in groups:
        groups[key] = dict(fields, count=0, sessions=set(), examples=[])
    group = groups[key]
    group["count"] += 1
    group["sessions"].add(example["session"])
    if len(group["examples"]) < 3:
        group["examples"].append(example)


def finish_groups(groups, head_field, minimum=1):
    result = [dict(group, sessions=len(group["sessions"]))
              for group in groups.values() if group["count"] >= minimum]
    return sorted(result, key=lambda group: (-group["count"], group[head_field]))


def blocked_reason(record, content):
    permission = record.get("permissionDecision")
    if isinstance(permission, dict) and permission.get("decision") == "reject":
        source = permission.get("source")
        if source == "hook":
            source = "hook"
        elif source == "user_reject":
            source = "user"
        elif permission.get("reasonType") == "classifier":
            source = "classifier"
        else:
            source = "rule"
        return source, text_content(content)
    violations = record.get("sandboxViolations")
    if isinstance(violations, list) and violations:
        reason = "\n".join(
            "{} {}:{}".format(item.get("kind", ""), item.get("host", ""),
                             item.get("port", ""))
            for item in violations if isinstance(item, dict)
        )
        return "sandbox", reason
    return None


class Extractor:
    def __init__(self, since):
        self.since = since
        self.blocked = {}
        self.failures = {}
        self.corrections = []
        self.human_sessions = set()
        self.previous_assistant = {}

    def read_file(self, path, project, subagent):
        # ツール ID はファイルとセッションの中だけで対応付ける。
        calls = {}
        with path.open("rb") as stream:
            for line in stream:
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue
                if not isinstance(record, dict):
                    continue
                timestamp = record.get("timestamp")
                if timestamp:
                    try:
                        if parse_time(timestamp) < self.since:
                            continue
                    except (AttributeError, TypeError, ValueError):
                        continue
                self.read_record(record, project, subagent, calls)

    def read_record(self, record, project, subagent, calls):
        message = record.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        session = record.get("sessionId", "")
        if not isinstance(session, str):
            return
        session_key = (project, session)
        metadata = {
            "project": project, "session": session,
            "timestamp": record.get("timestamp"),
        }
        if record.get("type") == "assistant" and isinstance(content, list):
            if not subagent:
                self.previous_assistant[session_key] = text_content(content)[-200:]
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_id = block.get("id")
                if isinstance(tool_id, str):
                    calls[(session, tool_id)] = block
        elif record.get("type") == "user":
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id")
                        call = calls.get((session, tool_id), {}) if isinstance(tool_id, str) else {}
                        self.read_result(record, block, call, metadata)
            elif isinstance(content, str) and not subagent:
                origin = record.get("origin")
                if (record.get("isMeta") or not isinstance(origin, dict)
                        or origin.get("kind") != "human"):
                    return
                first = session_key not in self.human_sessions
                self.human_sessions.add(session_key)
                if first or content.startswith(("<", "/")):
                    return
                self.corrections.append(dict(
                    metadata, text=content[:300],
                    prev_assistant=self.previous_assistant.get(session_key, ""),
                    hint=any(phrase in content for phrase in HINTS),
                ))

    def read_result(self, record, block, call, metadata):
        tool = call.get("name", "")
        tool_input = call.get("input", {})
        example = dict(metadata, input=summarize_input(tool, tool_input))
        blocked = blocked_reason(record, block.get("content"))
        if blocked is not None:
            source, reason = blocked
            head = reason_head(reason)
            add_group(
                self.blocked, (source, tool, head),
                {"source": source, "tool": tool, "reason_head": head},
                dict(example, reason=reason[:300]),
            )
        elif block.get("is_error"):
            error = text_content(block.get("content"))
            head = reason_head(error)
            key = command_key(tool, tool_input)
            add_group(
                self.failures, (tool, key, head),
                {"tool": tool, "command_key": key, "error_head": head},
                dict(example, error=error[:300]),
            )


def select_root(requested):
    candidates = ([Path(requested).expanduser()] if requested is not None else [
        Path.home() / ".claude/projects",
        Path.home() / "mac_home/.claude/projects",
    ])
    errors = []
    for root in candidates:
        try:
            with os.scandir(root) as entries:
                projects = sorted(
                    (Path(entry.path) for entry in entries if entry.is_dir()),
                    key=str,
                )
            return root, projects
        except OSError as error:
            errors.append(str(error))
    raise OSError("対象のルートを一覧できません: " + "; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--root")
    parser.add_argument("--now", type=parse_time)
    args = parser.parse_args()
    now = args.now if args.now is not None else datetime.now(timezone.utc)
    try:
        since = now - timedelta(days=args.days)
    except OverflowError:
        parser.error("--days が日時の範囲を超えています")
    try:
        root, projects = select_root(args.root)
    except OSError as error:
        print(error, file=sys.stderr)
        return 2
    extractor = Extractor(since)
    counts = [0, 0]
    for project in projects:
        for subagent, pattern in ((False, "*.jsonl"), (True, "*/subagents/*.jsonl")):
            for path in sorted(project.glob(pattern)):
                try:
                    if not path.is_file() or path.stat().st_mtime < since.timestamp():
                        continue
                    extractor.read_file(path, project.name, subagent)
                    counts[subagent] += 1
                except OSError as error:
                    print("会話記録を読めません: {}: {}".format(path, error), file=sys.stderr)
    result = {
        "since": since.isoformat().replace("+00:00", "Z"),
        "root": str(root), "files": counts[0], "subagent_files": counts[1],
        "blocked": finish_groups(extractor.blocked, "reason_head"),
        "failures": finish_groups(extractor.failures, "error_head", minimum=2),
        "corrections": sorted(
            extractor.corrections,
            key=lambda item: (
                not item["hint"],
                parse_time(item["timestamp"]) if item["timestamp"]
                else datetime.min.replace(tzinfo=timezone.utc),
            ),
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
