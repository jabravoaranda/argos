from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"
    failures: list[str] = []
    for markdown in sorted(docs.rglob("*.md")) + [root / "README.md"]:
        text = markdown.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            candidate = (markdown.parent / unquote(path_part)).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                failures.append(f"{markdown.relative_to(root)}: link escapes repo: {target}")
                continue
            if not candidate.exists():
                failures.append(f"{markdown.relative_to(root)}: missing link target: {target}")
    if failures:
        print("\n".join(failures))
        return 1
    print("OK markdown internal links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
