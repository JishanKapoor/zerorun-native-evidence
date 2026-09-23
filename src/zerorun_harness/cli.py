# SPDX-License-Identifier: MIT
"""Strict JSON CLI; exclusive outputs avoid destroying evidence."""

import argparse, json, sys
from pathlib import Path
from .api import InvalidEvidence, audit, canonical, capture, compare, export, report

MAX_BYTES = 64 * 1024 * 1024


def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise InvalidEvidence("Duplicate JSON key: " + key)
        out[key] = value
    return out


def read(path):
    with Path(path).open("rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise InvalidEvidence("Input exceeds 64 MiB")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda s: (_ for _ in ()).throw(
                InvalidEvidence("Nonfinite JSON number")
            ),
        )
        canonical(
            value
        )  # enforce the same depth/type/finite-number contract as the Python API
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise InvalidEvidence("Invalid JSON: " + str(exc)) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="zerorun",
        description="Replay checks for pinned native observations. Executes no candidates.",
    )
    from . import __version__

    parser.add_argument(
        "--version", action="version", version="zerorun-harness " + __version__
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["capture", "audit", "compare", "export", "report"]:
        p = sub.add_parser(command)
        p.add_argument("input")
        p.add_argument("--output", required=True)
        if command == "compare":
            p.add_argument("other")
        if command == "export":
            p.add_argument(
                "--mode",
                choices=[
                    "native-values",
                    "event-replay",
                    "integration-replay",
                    "native-regression",
                ],
                default="native-values",
            )
            p.add_argument(
                "--recipe",
                help="Versioned native recipe JSON, required for native-regression",
            )
    args = parser.parse_args(argv)
    try:
        first = read(args.input)
        value = (
            export(
                first, mode=args.mode, recipe=read(args.recipe) if args.recipe else None
            )
            if args.command == "export"
            else (
                compare(first, read(args.other))
                if args.command == "compare"
                else {
                    "capture": capture,
                    "audit": audit,
                    "export": export,
                    "report": report,
                }[args.command](first)
            )
        )
        data = (
            value
            if isinstance(value, str)
            else json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )
        with Path(args.output).open("x", encoding="utf-8", newline="\n") as f:
            f.write(data)
    except (InvalidEvidence, OSError, RecursionError) as exc:
        print("zerorun: " + str(exc), file=sys.stderr)
        return 2
    return 0
