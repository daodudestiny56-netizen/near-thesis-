"""Command line: python -m census <command>

  collect     draw the block sample from the FastNEAR API (slow; resumable)
  classify    score every account and tag every sampled transaction
  validate    measure the classifier against the hand-labelled set
  analyze     compute shares over time, fee payers and the forecast
  thesis      evaluate every claim and write THESIS.md
  report      write RESULTS.md
  dashboard   write docs/index.html
  submission  draft the form text and X posts into submission/ (git-ignored)
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
    for name in ("classify", "validate", "analyze", "thesis", "report", "dashboard", "submission", "reproduce", "merge"):
        sub.add_parser(name)
    args = p.parse_args()

    if args.cmd == "collect":
        from .collect import run
        run(args.first, args.last, args.blocks)
    elif args.cmd == "merge":
        from .collect import merge
        merge()
    elif args.cmd == "classify":
        from .classify import run
        run()
    elif args.cmd == "validate":
        from .validate import run
        run()
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
