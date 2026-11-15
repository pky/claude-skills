#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys


def main():
    try:
        event = json.load(sys.stdin)
        command = event["tool_input"]["command"]
        if not re.search(r"(^|[\s;&|(])gh\s+pr\s+create(\s|$)", command):
            return
        response = json.dumps(event["tool_response"], ensure_ascii=False)
        if not re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/[0-9]+", response):
            return
        reminder = Path(__file__).resolve().parent.parent / "context" / "babysit-reminder.json"
        sys.stdout.buffer.write(reminder.read_bytes())
    except Exception:
        # 入力やファイルの異常で Claude の作業を止めない。
        return


if __name__ == "__main__":
    main()
