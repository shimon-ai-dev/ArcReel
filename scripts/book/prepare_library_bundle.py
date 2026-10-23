"""Preview an existing local library, or prepare a portable bundle outside it.

Run: uv run python -m scripts.book.prepare_library_bundle LIBRARY_ROOT --output NEW_DIRECTORY
This command performs no network operations and never modifies the selected root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.library_bundle.converter import prepare_library
from lib.library_bundle.safe_io import LibraryReadError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library_root", type=Path, help="Existing root containing 成品 and its source archives")
    parser.add_argument("--output", type=Path, help="New directory outside the library; omit for preview only")
    parser.add_argument("--library-id", help="Stable library identity; defaults to the selected directory name")
    parser.add_argument(
        "--entry", action="append", help="Include only this existing product-entry ID; repeat to select more"
    )
    args = parser.parse_args(argv)
    try:
        preview = prepare_library(
            args.library_root,
            library_id=args.library_id,
            output=args.output,
            entries=set(args.entry) if args.entry else None,
        )
    except (LibraryReadError, OSError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(preview.report(), ensure_ascii=False, indent=2))
    return 0 if preview.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
