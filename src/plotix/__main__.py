"""Allow ``python -m plotix`` as well as the ``plotix`` console script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
