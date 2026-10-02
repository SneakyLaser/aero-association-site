"""Build the public, backend-free site used by GitHub Pages."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from aero_association_agent.article_loader import article_tree, load_articles
from aero_association_agent.content_loader import CONTENT_KINDS, load_public_content
from aero_association_agent.settings import FRONTEND_DIR, PROJECT_ROOT, PUBLIC_ASSETS_DIR
from aero_association_agent.site_copy import load_site_copy, render_index


OUTPUT_DIR = PROJECT_ROOT / "dist"
PUBLIC_URL = re.compile(r"/(knowledge/assets|aircraft-assets|news-assets|assets|fonts)/([^\"')<>\s]+)")
CLOUDFLARE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def article_payload(article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "section": article.section,
        "summary": article.summary,
        "tags": article.tags,
        "source_refs": article.source_refs,
        "media": article.media,
        "body": article.body,
    }


def analytics_beacon() -> str:
    token = os.environ.get("CLOUDFLARE_WEB_ANALYTICS_TOKEN", "").strip()
    if not token:
        return ""
    if not CLOUDFLARE_TOKEN.fullmatch(token):
        raise ValueError("CLOUDFLARE_WEB_ANALYTICS_TOKEN 格式不正确")
    return (
        '  <script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" '
        f'data-cf-beacon=\'{{"token":"{token}","spa":false}}\'></script>\n'
    )


def referenced_public_files(texts: list[str]) -> list[tuple[Path, Path]]:
    roots = {
        "news-assets": PUBLIC_ASSETS_DIR / "新闻配图",
        "aircraft-assets": PUBLIC_ASSETS_DIR / "机型目录配图",
        "assets": PUBLIC_ASSETS_DIR / "官网配图",
        "fonts": PUBLIC_ASSETS_DIR / "网页字体",
        "knowledge/assets": PUBLIC_ASSETS_DIR / "教程附件",
    }
    files: dict[Path, Path] = {}
    for text in texts:
        for area, encoded_name in PUBLIC_URL.findall(text):
            relative = Path(unquote(encoded_name.split("?", 1)[0]))
            source = (roots[area] / relative).resolve()
            if not source.is_relative_to(roots[area].resolve()) or not source.is_file():
                raise FileNotFoundError(f"发布资源不存在：/{area}/{relative.as_posix()}")
            destination = Path(area) / relative
            files[destination] = source
    return sorted(((source, destination) for destination, source in files.items()), key=lambda item: str(item[1]))


def build(*, preview: bool = False) -> None:
    output = OUTPUT_DIR.resolve()
    if output.parent != PROJECT_ROOT.resolve():
        raise RuntimeError("拒绝清理项目目录之外的构建目录")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    site_copy = load_site_copy()
    articles = load_articles()
    content = {kind: [item.as_dict() for item in load_public_content(kind, include_drafts=preview)] for kind in CONTENT_KINDS}

    write_json(output / "api/site-copy.json", site_copy)
    write_json(output / "api/articles/index.json", {"sections": article_tree()})
    for article in articles:
        write_json(output / f"api/articles/{article.id}.json", article_payload(article))
    for kind, items in content.items():
        write_json(output / f"api/content/{kind}/index.json", {"items": items})
        for item in items:
            write_json(output / f"api/content/{kind}/{item['id']}.json", item)

    app_bytes = (FRONTEND_DIR / "app.js").read_bytes()
    style_bytes = (FRONTEND_DIR / "styles.css").read_bytes()
    raw_index = render_index()
    index = raw_index
    index = index.replace('href="/assets/', 'href="assets/')
    index = index.replace('href="/"', 'href="./"').replace('href="/?', 'href="?').replace('href="/#', 'href="./#')
    index = index.replace('src="/assets/', 'src="assets/')
    index = index.replace("</body>", f"{analytics_beacon()}</body>")
    index = index.replace(
        "<script defer",
        "<script>globalThis.AERO_STATIC_SITE = true;</script>\n  <script defer",
        1,
    )
    index = index.replace(
        f'/styles.css?v={hashlib.sha256(style_bytes).hexdigest()[:12]}',
        f'styles.css?v={hashlib.sha256(style_bytes).hexdigest()[:12]}',
    ).replace(
        f'/app.js?v={hashlib.sha256(app_bytes).hexdigest()[:12]}',
        f'app.js?v={hashlib.sha256(app_bytes).hexdigest()[:12]}',
    )
    (output / "index.html").write_text(index, encoding="utf-8")
    (output / "404.html").write_text(index, encoding="utf-8")
    (output / "app.js").write_bytes(app_bytes)
    raw_styles = style_bytes.decode("utf-8")
    styles = raw_styles.replace("url('/fonts/", "url('fonts/").replace('url("/fonts/', 'url("fonts/')
    (output / "styles.css").write_text(styles, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")

    serialized = [raw_index, index, raw_styles, styles, json.dumps(site_copy, ensure_ascii=False)]
    serialized.extend(json.dumps(article_payload(article), ensure_ascii=False) for article in articles)
    serialized.extend(json.dumps(items, ensure_ascii=False) for items in content.values())
    copied = referenced_public_files(serialized)
    for source, relative in copied:
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    print(f"静态网站已生成：{output}")
    print(f"公开文章 {len(articles)} 篇，活动记录 {sum(map(len, content.values()))} 条，资源文件 {len(copied)} 个")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="本地预览公开范围内的航模草稿；正式发布不使用此选项")
    build(preview=parser.parse_args().preview)
