from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import JsoncSyntaxError
from .transform import sort_jsonc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sort JSONC object keys alphabetically while preserving comments and whitespace."
    )
    parser.add_argument("file", type=Path, help="JSONC file to process")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-w", "--write", action="store_true", help="overwrite the input file"
    )
    mode.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="exit nonzero if the file is not sorted/normalized",
    )
    mode.add_argument("-o", "--output", type=Path, help="write output to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = args.file.read_text(encoding="utf-8")
        result = sort_jsonc(source, str(args.file))
    except FileNotFoundError:
        print(f"jsonc-sort-keys: file not found: {args.file}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"jsonc-sort-keys: {exc}", file=sys.stderr)
        return 2
    except JsoncSyntaxError as exc:
        print(f"jsonc-sort-keys: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if result != source:
            print(f"jsonc-sort-keys: {args.file} is not sorted", file=sys.stderr)
            return 1
        return 0

    if args.write:
        args.file.write_text(result, encoding="utf-8")
        return 0

    if args.output:
        args.output.write_text(result, encoding="utf-8")
        return 0

    print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
