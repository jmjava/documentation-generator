"""GitHub Pages asset generator: index.html, pages.yml, .gitattributes, .gitignore."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class PagesGenerator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.pages_cfg = config.pages_config

    def generate_all(self, force: bool = False) -> None:
        self.generate_index_html(force)
        self.generate_pages_workflow(force)
        self.generate_gitattributes()
        self.generate_gitignore()

    # -- index.html ------------------------------------------------------------

    def generate_index_html(self, force: bool = False) -> None:
        repo_root = self.config.repo_root
        docs_dir = self.pages_cfg.get("docs_dir", "docs")
        out = repo_root / docs_dir / "index.html"

        if out.exists() and not force:
            print(f"[pages] {out} exists; use --force to overwrite")
            return

        title = self.pages_cfg.get("title", "Demo Videos")
        subtitle = self.pages_cfg.get("subtitle", "")
        repo_url = self.pages_cfg.get("repo_url", "")
        demos_sub = self.pages_cfg.get("demos_subdir", "demos")
        extra_links = self.pages_cfg.get("extra_links", [])
        segments_cfg = self.pages_cfg.get("segments", {})
        concat_map = self.config.concat_map

        # Probe durations
        seg_cards = []
        for seg_id, meta in sorted(segments_cfg.items()):
            duration = self._probe_duration(seg_id)
            seg_cards.append(
                f'            <div class="video-card" id="seg-{seg_id}">\n'
                f'                <p class="seg-id">#seg-{seg_id}</p>\n'
                f'                <h2>{seg_id} — {_esc(meta.get("title", seg_id))}</h2>\n'
                f'                <span class="duration">{duration}</span>\n'
                f'                <p>{_esc(meta.get("description", ""))}</p>\n'
                f'                <video controls preload="metadata">\n'
                f'                    <source src="{demos_sub}/recordings/{self._find_recording_name(seg_id)}" type="video/mp4">\n'
                f'                </video>\n'
                f'            </div>'
            )

        concat_cards = []
        for cname in sorted(concat_map.keys()):
            fname = cname if cname.endswith(".mp4") else f"{cname}.mp4"
            anchor = cname.replace(".mp4", "").replace("_", "-")
            duration = self._probe_concat_duration(cname)
            concat_cards.append(
                f'            <div class="video-card" id="{anchor}">\n'
                f'                <p class="seg-id">#{anchor}</p>\n'
                f'                <h2>{cname}</h2>\n'
                f'                <span class="duration">{duration}</span>\n'
                f'                <video controls preload="metadata">\n'
                f'                    <source src="{demos_sub}/recordings/{fname}" type="video/mp4">\n'
                f'                </video>\n'
                f'            </div>'
            )

        footer_links = ""
        for lnk in extra_links:
            footer_links += f' | <a href="{lnk["href"]}">{_esc(lnk["label"])}</a>'

        html = _INDEX_TEMPLATE.format(
            title=_esc(title),
            subtitle=_esc(subtitle),
            segment_cards="\n\n".join(seg_cards),
            concat_cards="\n\n".join(concat_cards),
            repo_url=repo_url,
            footer_links=footer_links,
        )

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"[pages] Wrote {out}")

    # -- pages.yml -------------------------------------------------------------

    def generate_pages_workflow(self, force: bool = False) -> None:
        repo_root = self.config.repo_root
        out = repo_root / ".github" / "workflows" / "pages.yml"

        if out.exists() and not force:
            print(f"[pages] {out} exists; use --force to overwrite")
            return

        docs_dir = self.pages_cfg.get("docs_dir", "docs")
        demos_sub = self.pages_cfg.get("demos_subdir", "demos")

        workflow = _WORKFLOW_TEMPLATE.format(docs_dir=docs_dir, demos_sub=demos_sub)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(workflow, encoding="utf-8")
        print(f"[pages] Wrote {out}")

    # -- .gitattributes --------------------------------------------------------

    def generate_gitattributes(self) -> None:
        repo_root = self.config.repo_root
        out = repo_root / ".gitattributes"
        docs_dir = self.pages_cfg.get("docs_dir", "docs")
        demos_sub = self.pages_cfg.get("demos_subdir", "demos")
        prefix = f"{docs_dir}/{demos_sub}"

        lfs_rules = [
            f"{prefix}/recordings/*.mp4 filter=lfs diff=lfs merge=lfs -text",
            f"{prefix}/audio/*.mp3 filter=lfs diff=lfs merge=lfs -text",
        ]

        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        added = []
        for rule in lfs_rules:
            if rule not in existing:
                added.append(rule)

        if added:
            with open(out, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(added) + "\n")
            print(f"[pages] Updated {out} with {len(added)} LFS rules")
        else:
            print("[pages] .gitattributes already has LFS rules")

    # -- .gitignore ------------------------------------------------------------

    def generate_gitignore(self) -> None:
        base = self.config.base_dir
        out = base / ".gitignore"

        rules = [
            "# docgen: intermediate objects (regenerable)",
            ".venv/",
            "slides/node_modules/",
            "slides/dist/",
            "animations/media/partial_movie_files/",
            "animations/media/videos/",
            "terminal/rendered/.tmp/",
            "terminal/rendered/*.mp4",
            "audio/*.mp3",
            "__pycache__/",
            "*.pyc",
            ".docgen-state.json",
            "",
            "# recordings/*.mp4 — COMMITTED (tracked via LFS for README/Pages links)",
        ]

        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        if "docgen: intermediate objects" in existing:
            print(f"[pages] {out} already has docgen rules")
            return

        with open(out, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n".join(rules) + "\n")
        print(f"[pages] Updated {out}")

    # -- Helpers ---------------------------------------------------------------

    def _probe_duration(self, seg_id: str) -> str:
        rec = self._find_recording(seg_id)
        if not rec:
            return "varies"
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(rec)],
                capture_output=True, text=True, timeout=10,
            )
            dur = float(json.loads(out.stdout).get("format", {}).get("duration", 0))
            if dur > 0:
                m, s = divmod(int(dur), 60)
                return f"~{m}m {s}s"
        except Exception:
            pass
        return "varies"

    def _find_recording(self, seg_id: str) -> Path | None:
        d = self.config.recordings_dir
        if not d.exists():
            return None
        for mp4 in d.glob(f"*{seg_id}*.mp4"):
            return mp4
        return None

    def _find_recording_name(self, seg_id: str) -> str:
        rec = self._find_recording(seg_id)
        return rec.name if rec else f"{seg_id}.mp4"

    def _probe_concat_duration(self, cname: str) -> str:
        fname = cname if cname.endswith(".mp4") else f"{cname}.mp4"
        rec = self.config.recordings_dir / fname
        if not rec.exists():
            return "concat"
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(rec)],
                capture_output=True, text=True, timeout=10,
            )
            dur = float(json.loads(out.stdout).get("format", {}).get("duration", 0))
            if dur > 0:
                m, s = divmod(int(dur), 60)
                return f"~{m}m {s}s"
        except Exception:
            pass
        return "concat"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;padding:2rem;color:#333}}
        .container{{max-width:1200px;margin:0 auto}}
        header{{text-align:center;color:#fff;margin-bottom:3rem}}
        h1{{font-size:2.5rem;margin-bottom:.5rem;text-shadow:2px 2px 4px rgba(0,0,0,.2)}}
        .subtitle{{font-size:1.1rem;opacity:.9}}
        .section-title{{color:#fff;font-size:1.35rem;margin:2rem 0 1rem;text-shadow:1px 1px 2px rgba(0,0,0,.15)}}
        .videos-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:2rem;margin-bottom:2rem}}
        .video-card{{background:#fff;border-radius:12px;padding:1.5rem;box-shadow:0 10px 30px rgba(0,0,0,.2);transition:transform .3s,box-shadow .3s;scroll-margin-top:1.5rem}}
        .video-card:hover{{transform:translateY(-5px);box-shadow:0 15px 40px rgba(0,0,0,.3)}}
        .video-card h2{{font-size:1.35rem;margin-bottom:.5rem;color:#667eea}}
        .video-card .seg-id{{font-size:.8rem;color:#999;font-family:ui-monospace,monospace;margin-bottom:.35rem}}
        .video-card p{{color:#666;margin-bottom:1rem;line-height:1.6}}
        .video-card .duration{{display:inline-block;background:#667eea;color:#fff;padding:.25rem .75rem;border-radius:20px;font-size:.9rem;margin-bottom:1rem}}
        video{{width:100%;border-radius:8px;background:#000;margin-top:1rem}}
        .footer{{text-align:center;color:#fff;margin-top:3rem;padding-top:2rem;border-top:1px solid rgba(255,255,255,.2)}}
        .footer a{{color:#fff;text-decoration:underline}}
        @media(max-width:768px){{h1{{font-size:2rem}}}}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{title}</h1>
            <p class="subtitle">{subtitle}</p>
        </header>

        <h2 class="section-title">Segments</h2>
        <div class="videos-grid">
{segment_cards}
        </div>

        <h2 class="section-title">Full demos</h2>
        <div class="videos-grid">
{concat_cards}
        </div>

        <div class="footer">
            <p>All videos are generated programmatically.</p>
            <p><a href="{repo_url}">View on GitHub</a>{footer_links}</p>
        </div>
    </div>
</body>
</html>
"""

_WORKFLOW_TEMPLATE = """name: Deploy to GitHub Pages

on:
  push:
    branches:
      - main
    paths:
      - '{docs_dir}/**'
      - '.github/workflows/pages.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          lfs: true
      - name: Cache-bust video URLs
        env:
          GITHUB_SHA: ${{{{ github.sha }}}}
        run: |
          python3 <<'PY'
          import os, pathlib, re
          sha = os.environ["GITHUB_SHA"][:12]
          path = pathlib.Path("{docs_dir}/index.html")
          if not path.exists():
              exit(0)
          text = path.read_text(encoding="utf-8")
          new = re.sub(
              r'src="({demos_sub}/recordings/[^"?]+\\.mp4)(?:\\?[^"]*)?"',
              lambda m: f'src="{{m.group(1)}}?v={{sha}}"',
              text,
          )
          path.write_text(new, encoding="utf-8")
          PY
      - name: Setup Pages
        uses: actions/configure-pages@v5
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: {docs_dir}
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""
