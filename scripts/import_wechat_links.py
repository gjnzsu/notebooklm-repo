import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_NOTEBOOK_TITLE = "微信优秀文章"
FETCH_SCRIPT = Path(r"C:\Users\gjnzsu\.codex\skills\qiaomu-anything-to-notebooklm\scripts\fetch_url.sh")
BASH_EXE = Path(r"C:\Program Files\Git\bin\bash.exe")
FETCH_HELPER = Path(__file__).with_name("fetch_weixin_article.py")


def run_command(args, check=True, capture_output=True):
    result = subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def notebooklm_json(*args):
    result = run_command(["notebooklm", *args])
    return json.loads(result.stdout)


def get_prop(obj, *names):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
    return None


def test_invalid_article(content):
    if not content or len(content.strip()) < 500:
        return True
    lowered = content.lower()
    markers = [
        "环境异常",
        "去验证",
        "requiring captcha",
        "captcha",
        "验证你是否为人类",
    ]
    return any(marker in content or marker in lowered for marker in markers)


def test_garbled(text):
    if not text:
        return False
    return "\ufffd" in text or "锟" in text


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    match = re.match(r"(?s)^---\n(.*?)\n---\n(.*)$", text)
    if not match:
        return {}, text
    frontmatter = {}
    for line in match.group(1).splitlines():
        m = re.match(r"^\s*([^:]+):\s*(.*)\s*$", line)
        if not m:
            continue
        key = m.group(1).strip()
        value = m.group(2).strip().strip('"')
        frontmatter[key] = value
    return frontmatter, match.group(2)


def invoke_mcp_fetch(url):
    result = run_command([sys.executable, str(FETCH_HELPER), url], check=False)
    if not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not payload.get("success"):
        return None
    if test_garbled(payload.get("title", "")) or test_garbled(payload.get("content", "")):
        return None
    if test_invalid_article(payload.get("content", "")):
        return None
    return {
        "title": payload.get("title", ""),
        "author": payload.get("author", ""),
        "publish_time": payload.get("publish_time", ""),
        "cover_url": payload.get("cover_url", ""),
        "content": payload.get("content", ""),
        "url": url,
        "method": "mcp",
    }


def invoke_fallback_fetch(url, date_ymd):
    output = ""
    if BASH_EXE.exists() and FETCH_SCRIPT.exists():
        result = run_command([str(BASH_EXE), str(FETCH_SCRIPT), url], check=False)
        output = result.stdout
    if not output or test_invalid_article(output) or test_garbled(output):
        result = run_command(["curl.exe", "-sL", f"https://defuddle.md/{url}"], check=False)
        output = result.stdout
    if not output or test_invalid_article(output) or test_garbled(output):
        return None
    frontmatter, body = parse_frontmatter(output)
    title = frontmatter.get("title", "").strip()
    if not title:
        hash_value = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        title = f"微信文章-{date_ymd}-{hash_value}"
    article = {
        "title": title,
        "author": frontmatter.get("author", ""),
        "publish_time": frontmatter.get("publish_time", ""),
        "cover_url": frontmatter.get("cover_url", frontmatter.get("cover", "")),
        "content": body.strip(),
        "url": url,
        "method": "fallback",
    }
    if test_invalid_article(article["content"]):
        return None
    return article


def get_article(url, date_ymd):
    article = invoke_mcp_fetch(url)
    if article:
        return article
    return invoke_fallback_fetch(url, date_ymd)


def save_article_file(article, temp_dir):
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", article["title"]).strip() or "wechat-article"
    target = temp_dir / f"{safe_title}.txt"
    text = "\n".join(
        [
            f"title: {article['title']}",
            f"author: {article.get('author', '')}",
            f"publish_time: {article.get('publish_time', '')}",
            f"source_url: {article['url']}",
            f"cover_url: {article.get('cover_url', '')}",
            "",
            article["content"],
        ]
    )
    target.write_text(text, encoding="utf-8")
    return target


def ensure_login(skip_login, login_browser):
    if skip_login:
        return
    result = run_command(["notebooklm", "login", "--browser", login_browser], check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "NotebookLM login failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def load_links(link_file):
    return [
        line.strip()
        for line in link_file.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("https://mp.weixin.qq.com/")
    ]


def resolve_notebook(notebook_title):
    notebooks = notebooklm_json("list", "--json", "--no-truncate")
    if isinstance(notebooks, dict):
        notebooks = notebooks.get("notebooks") or notebooks.get("items", [])
    for notebook in notebooks:
        if get_prop(notebook, "title", "name") == notebook_title:
            notebook_id = get_prop(notebook, "id", "notebook_id", "notebookId")
            if notebook_id:
                return notebook_id
    raise RuntimeError(f"Notebook '{notebook_title}' not found.")


def load_sources(notebook_id):
    sources = notebooklm_json("source", "list", "--json", "--no-truncate", "--notebook", notebook_id)
    if isinstance(sources, dict):
        sources = sources.get("sources") or sources.get("items", [])
    return sources


def build_existing_url_set(sources, notebook_id, temp_dir, links):
    known = set()
    for source in sources:
        source_id = get_prop(source, "id", "source_id", "sourceId")
        if not source_id:
            continue
        fulltext_path = temp_dir / f"source-{source_id}.md"
        result = run_command(
            [
                "notebooklm",
                "source",
                "fulltext",
                source_id,
                "--notebook",
                notebook_id,
                "--format",
                "markdown",
                "-o",
                str(fulltext_path),
            ],
            check=False,
        )
        if result.returncode != 0 or not fulltext_path.exists():
            continue
        text = fulltext_path.read_text(encoding="utf-8", errors="replace")
        for link in links:
            if link in text:
                known.add(link)
    return known


def add_source(notebook_id, file_path, title):
    payload = notebooklm_json("source", "add", "--json", "--notebook", notebook_id, str(file_path), "--title", title)
    source_id = get_prop(payload, "id", "source_id", "sourceId")
    if source_id:
        run_command(
            [
                "notebooklm",
                "source",
                "wait",
                source_id,
                "--notebook",
                notebook_id,
                "--timeout",
                "120",
                "--interval",
                "2",
            ],
            check=False,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook-title", default=DEFAULT_NOTEBOOK_TITLE)
    parser.add_argument("--notebook-title-b64")
    parser.add_argument("--date-ymd", default=time.strftime("%Y%m%d"))
    parser.add_argument("--link-dir", default=os.getcwd())
    parser.add_argument("--temp-dir", default=str(Path(tempfile.gettempdir()) / "notebooklm-wechat-import"))
    parser.add_argument("--login-browser", default="chrome", choices=["chromium", "chrome", "msedge"])
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--skip-auth-refresh", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.notebook_title_b64:
        import base64
        args.notebook_title = base64.b64decode(args.notebook_title_b64).decode("utf-8")

    ensure_login(args.skip_login or args.skip_auth_refresh, args.login_browser)

    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    link_file = Path(args.link_dir) / f"link_{args.date_ymd}.txt"
    if not link_file.exists():
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "missing link file",
                    "file": str(link_file),
                    "counts": {"processed": 0, "uploaded": 0, "skipped": 0, "failed": 0},
                    "entries": [],
                },
                ensure_ascii=False,
            )
        )
        return 0

    links = load_links(link_file)
    if not links:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "no weixin links",
                    "file": str(link_file),
                    "counts": {"processed": 0, "uploaded": 0, "skipped": 0, "failed": 0},
                    "entries": [],
                },
                ensure_ascii=False,
            )
        )
        return 0

    notebook_id = resolve_notebook(args.notebook_title)
    sources = load_sources(notebook_id)
    existing_titles = {
        get_prop(source, "title", "name")
        for source in sources
        if get_prop(source, "title", "name")
    }
    known_urls = build_existing_url_set(sources, notebook_id, temp_dir, links)

    entries = []
    uploaded = 0
    skipped = 0
    failed = 0

    for link in links:
        article = get_article(link, args.date_ymd)
        if not article:
            entries.append(
                {
                    "status": "failed_fetch",
                    "reason": "unable to fetch valid article",
                    "title": "",
                    "method": "fallback",
                    "url": link,
                }
            )
            failed += 1
            continue

        if article["title"] in existing_titles:
            entries.append(
                {
                    "status": "skipped",
                    "reason": "duplicate_title",
                    "title": article["title"],
                    "method": article["method"],
                    "url": link,
                }
            )
            skipped += 1
            continue

        if link in known_urls:
            entries.append(
                {
                    "status": "skipped",
                    "reason": "duplicate_url",
                    "title": article["title"],
                    "method": article["method"],
                    "url": link,
                }
            )
            skipped += 1
            continue

        file_path = save_article_file(article, temp_dir)
        add_source(notebook_id, file_path, article["title"])
        refreshed_sources = load_sources(notebook_id)
        matched = next(
            (source for source in refreshed_sources if get_prop(source, "title", "name") == article["title"]),
            None,
        )
        status = get_prop(matched or {}, "status", "state")
        if status != "ready":
            time.sleep(3)
            refreshed_sources = load_sources(notebook_id)
            matched = next(
                (source for source in refreshed_sources if get_prop(source, "title", "name") == article["title"]),
                None,
            )
            status = get_prop(matched or {}, "status", "state")

        if matched and status == "ready":
            existing_titles.add(article["title"])
            known_urls.add(link)
            entries.append(
                {
                    "status": "uploaded",
                    "reason": "",
                    "title": article["title"],
                    "method": article["method"],
                    "url": link,
                }
            )
            uploaded += 1
        else:
            entries.append(
                {
                    "status": "failed",
                    "reason": "source_not_ready",
                    "title": article["title"],
                    "method": article["method"],
                    "url": link,
                }
            )
            failed += 1

    print(
        json.dumps(
            {
                "status": "completed",
                "file": str(link_file),
                "notebook": {"title": args.notebook_title, "id": notebook_id},
                "counts": {
                    "processed": len(links),
                    "uploaded": uploaded,
                    "skipped": skipped,
                    "failed": failed,
                },
                "entries": entries,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
