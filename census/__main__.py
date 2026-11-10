"""Command line: python -m census <command>

  collect     draw the block sample from the FastNEAR API (slow; resumable)
  classify    score every account and tag every sampled transaction
  validate    measure the classifier against the hand-labelled set
  analyze     compute shares, absolute levels, supply/issuance and breakpoints
  thesis      evaluate every claim and write THESIS.md
  report      write RESULTS.md
  dashboard   write docs/index.html
  submission  draft the form text and X posts into submission/ (git-ignored)
  predictions verify the frozen pre-registered predictions and show their status (--freeze creates them once)
  external    refresh the third-party snapshot in data/external/ (DefiLlama: Intents revenue, NEAR price); needs internet
  enrich      add total_supply / protocol_version to months collected before the collector stored them (from the cache)
  reproduce   classify -> validate -> analyze -> thesis -> report -> dashboard from the committed data (offline, ~1 min)
"""
import argparse

from . import config as C


def main() -> None:
    p = argparse.ArgumentParser(prog="census", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--first", default=C.FIRST_PERIOD, help="first month, YYYY-MM")
    c.add_argument("--last", default=None, help="last month, YYYY-MM")
    c.add_argument("--blocks", type=int, default=C.BLOCKS_PER_PERIOD, help="random blocks per month")
    pr = sub.add_parser("predictions")
    pr.add_argument("--freeze", action="store_true", help="freeze the pre-registered predictions (refuses to overwrite)")
    v = sub.add_parser("validate")
    v.add_argument("--dev-only", action="store_true", help="tuning mode: score and print the DEV split only")
    for name in ("classify", "analyze", "thesis", "report", "dashboard", "submission", "reproduce", "merge", "external", "enrich"):
        sub.add_parser(name)
    args = p.parse_args()

    if args.cmd == "collect":
        from .collect import run
        run(args.first, args.last, args.blocks)
    elif args.cmd == "merge":
        from .collect import merge
        merge()
    elif args.cmd == "predictions":
        from .predictions import run
        run(args.freeze)
    elif args.cmd == "external":
        from .external import run
        run()
    elif args.cmd == "enrich":
        from .enrich import run
        run()
    elif args.cmd == "classify":
        from .classify import run
        run()
    elif args.cmd == "validate":
        from .validate import run
        run(args.dev_only)
    elif args.cmd == "analyze":
        from .analyze import run
        run()
    elif args.cmd == "submission":
        from .submission import run
        run()
    elif args.cmd == "thesis":
        from .thesis import run
        run()
    elif args.cmd == "report":
        from .report import run
        run()
    elif args.cmd == "dashboard":
        from .dashboard import run
        run()
    elif args.cmd == "reproduce":
        from .classify import run as classify
        from .validate import run as validate
        from .analyze import run as analyze
        from .thesis import run as thesis
        from .report import run as report
        from .dashboard import run as dashboard
        classify(); validate(); analyze(); thesis(); report(); dashboard()


if __name__ == "__main__":
    main()
