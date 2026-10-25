#!/usr/bin/env python3
"""Count Unicode code points or UTF-16 units; does not measure rendered width."""

import argparse
import json
from pathlib import Path
import sys


def non_negative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("limit must be non-negative")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Text to count, including spaces")
    source.add_argument("--file", type=Path, help="UTF-8 file; counts the entire file")
    parser.add_argument("--max", dest="limit", type=non_negative)
    parser.add_argument("--metric", choices=("codepoints", "utf16"), default="codepoints")
    args = parser.parse_args()

    try:
        # Decode bytes directly: CRLF remains two code points, not normalized LF.
        content = args.text if args.text is not None else args.file.read_bytes().decode("utf-8-sig")
        counts = {
            "codepoints": len(content),
            "utf16": len(content.encode("utf-16-le")) // 2,
        }
    except (OSError, UnicodeError) as error:
        print(f"Cannot read or count input: {error}", file=sys.stderr)
        return 2

    within_limit = None if args.limit is None else counts[args.metric] <= args.limit
    result = {
        "codepoints": counts["codepoints"],
        "utf16_units": counts["utf16"],
        "metric": args.metric,
        "count": counts[args.metric],
        "limit": args.limit,
        "within_limit": within_limit,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if within_limit is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
