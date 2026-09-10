"""Allow `python -m remeta` as an alternative to the `remeta` command."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
