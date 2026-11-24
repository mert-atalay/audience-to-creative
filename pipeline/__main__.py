"""Command line: python -m pipeline <run|demo|review|results|fixtures>."""
from __future__ import annotations

import argparse
import os
import sys

from . import fixtures, review, run
from .config import PROFILES, load_profile
from .sources import SourceUnavailable
from .storage import StorageUnavailable, open_store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    store_help = "output folder or gs://bucket/prefix (default: $PIPELINE_STORE or 'out')"

    def add(name, help_text, profile=True):
        p = sub.add_parser(name, help=help_text)
        if profile:
            p.add_argument("--profile", choices=PROFILES, required=True)
        p.add_argument("--out", default=os.environ.get("PIPELINE_STORE", "out"), help=store_help)
        return p

    p = add("run", "run all stages for one profile")
    p.add_argument("--generator", choices=["template", "llm"], default=os.environ.get("PIPELINE_GENERATOR", "template"))
    p.add_argument("--top", type=int, default=3, help="number of exploit briefs (one explore brief is added)")
    add("demo", "full loop for both profiles: run, scripted review, import results, run again", profile=False)
    p = add("review", "list variants, or approve / reject them")
    p.add_argument("--list", action="store_true", help="only list variants")
    p.add_argument("--approve", metavar="VARIANT_ID")
    p.add_argument("--reject", metavar="VARIANT_ID")
    p.add_argument("--note", default="")
    p.add_argument("--reviewer", default=os.environ.get("USER", "reviewer"))
    p = add("results", "import results for approved variants into memory")
    p.add_argument("--file", help="JSON file with results (default: the bundled demo file)")
    sub.add_parser("fixtures", help="regenerate the bundled synthetic data")

    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            for name in PROFILES:
                print(f"wrote {fixtures.write(name)}")
        elif args.command == "demo":
            run.demo(args.out)
        elif args.command == "run":
            run.run_profile(args.profile, open_store(args.out, args.profile), args.generator, args.top)
        elif args.command == "results":
            run.import_results(args.profile, open_store(args.out, args.profile), args.file)
        elif args.command == "review":
            store = open_store(args.out, args.profile)
            if args.list or (not sys.stdin.isatty() and not (args.approve or args.reject)):
                print("\n\n".join(review.describe(v) for v in review.load_variants(store)) or "No variants. Run the pipeline first.")
                return 0
            if args.approve or args.reject:
                decision = "approved" if args.approve else "rejected"
                print(review.describe(review.decide(store, args.approve or args.reject, decision, args.note, args.reviewer)))
            else:
                print(f"{review.interactive(store, reviewer=args.reviewer)} variants decided")
            run.write_gallery(store, load_profile(args.profile))  # the gallery shows the new status
    except (review.ReviewError, SourceUnavailable, StorageUnavailable, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
