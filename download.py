"""Discover the US stock universe and record daily closing market-cap rankings."""

import sys

from marketcap.cli import main

if __name__ == "__main__":
    sys.argv.insert(1, "collect")
    sys.exit(main())
