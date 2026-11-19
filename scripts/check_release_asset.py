"""Assert the README names the wheel the release actually carries.

The quickstart's install command is part of the pre-registered claim, so the
document and the artifact have to agree. This compares the URL in the README
against the published asset URL with the tag substituted, which catches a
renamed wheel, a moved repository and a stale tag while still allowing a
rehearsal release under a different tag.

    python scripts/check_release_asset.py README.md <tag> <asset-url>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WHEEL_URL = re.compile(
    r"https://github\.com/([\w.-]+/[\w.-]+)/releases/download/([\w.-]+)/(custos_core-[\w.-]+\.whl)"
)


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    readme, tag, asset_url = sys.argv[1], sys.argv[2], sys.argv[3]
    urls = set(WHEEL_URL.findall(Path(readme).read_text(encoding="utf-8")))
    if not urls:
        print(f"{readme} carries no custos_core wheel URL", file=sys.stderr)
        return 1
    if len(urls) > 1:
        print(f"{readme} carries {len(urls)} different wheel URLs; expected one", file=sys.stderr)
        return 1
    repo, readme_tag, filename = urls.pop()
    expected = f"https://github.com/{repo}/releases/download/{tag}/{filename}"
    if asset_url != expected:
        print(f"the README expects {expected}", file=sys.stderr)
        print(f"the release carries {asset_url}", file=sys.stderr)
        return 1
    if readme_tag != tag:
        print(f"note: the README names tag {readme_tag}; this release is {tag}")
    print(f"the README names the published asset: {asset_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
