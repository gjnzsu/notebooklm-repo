import argparse
import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_SKILL_ROOT = Path(
    r"C:\Users\gjnzsu\.codex\skills\qiaomu-anything-to-notebooklm\wexin-read-mcp\src"
)


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--skill-root", default=str(DEFAULT_SKILL_ROOT))
    args = parser.parse_args()

    skill_root = Path(args.skill_root)
    if not skill_root.exists():
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"skill root not found: {skill_root}",
                },
                ensure_ascii=False,
            )
        )
        return 1

    sys.path.insert(0, str(skill_root))

    try:
        from scraper import WeixinScraper
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"failed to import scraper: {type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            )
        )
        return 1

    scraper = WeixinScraper()
    try:
        result = await scraper.fetch_article(args.url)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("success") else 1
    finally:
        await scraper.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
