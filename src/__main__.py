"""Allow the installed package to be started with ``python -m src``."""

from src.ui.main import main


if __name__ == "__main__":
    raise SystemExit(main())
