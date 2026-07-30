#!/usr/bin/env python3
"""Batch web scraper built on the local `defuddle` CLI.

Zero tokens, no API keys. Writes one file per URL and prints a summary.

    python scripts/scrape/scrape.py <url> [<url> ...]
    python scripts/scrape/scrape.py --file urls.txt --out-dir archives/scrapes
    python scripts/scrape/scrape.py <url> --format json

Notes for anyone editing this:
  - FORCE_COLOR=0 is mandatory; the CLI otherwise colorizes its own JSON.
  - The CLI's `-o` flag writes ANSI codes into the file, so we capture stdout.
  - The CLI exits 0 even on 404/blocked, so success is judged on content.
"""

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_OUT_DIR = Path("archives/scrapes")
DEFAULT_TIMEOUT = 90
DEFAULT_WORKERS = 5


def slugify(url: str) -> str:
    """Filesystem-safe stem derived from the URL."""
    parsed = urlparse(url)
    raw = f"{parsed.netloc}{parsed.path}".rstrip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return (slug[:120] or "page")


def find_cli() -> str:
    cli = shutil.which("defuddle")
    if not cli:
        sys.exit(
            "defuddle CLI not found. Install it with:\n"
            "    npm install -g defuddle-cli"
        )
    return cli


def fetch(cli: str, url: str, as_json: bool, timeout: int) -> dict:
    """Run defuddle on one URL. Returns {url, ok, content, meta, error}."""
    cmd = [cli, "parse", url, "--markdown"]
    if as_json:
        cmd.append("--json")

    env = {**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1"}

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"url": url, "ok": False, "error": f"timed out after {timeout}s"}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    # Exit code is unreliable — the CLI returns 0 on 404 and on blocks.
    if not stdout:
        return {"url": url, "ok": False, "error": stderr or "no output"}

    if as_json:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return {"url": url, "ok": False, "error": f"bad JSON: {exc}"}
        content = (data.get("content") or "").strip()
        meta = {k: v for k, v in data.items() if k != "content"}
    else:
        content = stdout
        meta = {}

    if not content:
        return {"url": url, "ok": False, "error": stderr or "empty content"}

    return {"url": url, "ok": True, "content": content, "meta": meta}


def write_result(result: dict, out_dir: Path, as_json: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = slugify(result["url"])

    if as_json:
        path = out_dir / f"{stem}.json"
        payload = {"url": result["url"], **result["meta"], "content": result["content"]}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path = out_dir / f"{stem}.md"
        path.write_text(f"<!-- source: {result['url']} -->\n\n{result['content']}\n", encoding="utf-8")

    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Scrape pages to clean markdown via defuddle.")
    ap.add_argument("urls", nargs="*", help="URLs to scrape")
    ap.add_argument("--file", help="file containing one URL per line")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help=f"output dir (default: {DEFAULT_OUT_DIR})")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown",
                    help="markdown body only, or json with metadata + schemaOrgData")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"per-URL seconds (default: {DEFAULT_TIMEOUT})")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"parallel fetches (default: {DEFAULT_WORKERS})")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        urls += [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    # de-dupe, preserve order
    urls = list(dict.fromkeys(urls))
    if not urls:
        ap.error("no URLs given (pass them as arguments or via --file)")

    cli = find_cli()
    as_json = args.format == "json"
    out_dir = Path(args.out_dir)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, cli, u, as_json, args.timeout): u for u in urls}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    # keep input order for a readable report
    order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: order[r["url"]])

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    for r in ok:
        path = write_result(r, out_dir, as_json)
        words = r["meta"].get("wordCount") or len(r["content"].split())
        print(f"  ok    {words:>6} words  {path}")

    for r in failed:
        print(f"  FAIL                 {r['url']}  ->  {r['error']}", file=sys.stderr)

    print(f"\n{len(ok)}/{len(urls)} scraped into {out_dir}")
    if failed:
        print(f"{len(failed)} failed. For those, fall back to WebFetch, or the browser MCP if it is an auth wall.",
              file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
