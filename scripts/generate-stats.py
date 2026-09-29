#!/usr/bin/env python3
"""Genera ``assets/stats.svg`` para el README de perfil de Dreftian.

El objetivo es no depender de servicios externos (``github-readme-stats`` y
amigos): si el servicio se cae, el README muestra una imagen rota. Aqui el
panel se genera desde la API de GitHub, se versiona en el repositorio y se
actualiza con un workflow semanal, asi que siempre es fiable.

Uso:
    GITHUB_TOKEN=... python scripts/generate-stats.py

Solo libreria estandar: no requiere ``pip install`` ni nada.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
LOGIN = os.environ.get("PROFILE_LOGIN", "Dreftian")
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "assets" / "stats.svg"

# Paleta pensada para fondo oscuro: cada lenguaje con un color propio y el
# resto agrupado en gris para que la barra no se vuelva un arcoiris.
LANG_COLORS = {
    "TypeScript": "#3b82f6",
    "MDX": "#a855f7",
    "CSS": "#ec4899",
    "HTML": "#f59e0b",
    "JavaScript": "#22d3ee",
    "Python": "#10b981",
}
OTHER_COLOR = "#4b5563"
TOP_LANGS = 6


def request_json(url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "dreftian-profile-stats")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_public_repos(token: str) -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        batch = request_json(
            f"{API}/users/{LOGIN}/repos?per_page=100&page={page}&type=owner&sort=updated", token
        )
        if not batch:
            return repos
        repos.extend(r for r in batch if not r.get("private"))
        if len(batch) < 100:
            return repos
        page += 1


def fetch_contributions(token: str) -> int:
    to = datetime.now(timezone.utc).replace(microsecond=0)
    from_ = to - timedelta(days=365)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    body = request_json(
        GRAPHQL,
        token,
        {"query": query, "variables": {"login": LOGIN, "from": from_.isoformat(), "to": to.isoformat()}},
    )
    return body["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]


def collect(token: str) -> dict:
    repos = fetch_public_repos(token)

    languages: dict[str, int] = defaultdict(int)
    releases = 0

    for repo in repos:
        try:
            repo_langs = request_json(f"{API}/repos/{LOGIN}/{repo['name']}/languages", token)
        except urllib.error.HTTPError:
            repo_langs = {}
        for name, size in repo_langs.items():
            languages[name] += size

        try:
            repo_releases = request_json(
                f"{API}/repos/{LOGIN}/{repo['name']}/releases?per_page=100", token
            )
        except urllib.error.HTTPError:
            repo_releases = []
        releases += len(repo_releases)

    return {
        "contributions": fetch_contributions(token),
        "repos": len(repos),
        "languages": len(languages),
        "releases": releases,
        "bytes": languages,
    }


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(n: int) -> str:
    return f"{n:,}"


def render(stats: dict) -> str:
    tiles = [
        (fmt(stats["contributions"]), "Contribuciones", "últimos 12 meses"),
        (fmt(stats["repos"]), "Repositorios", "públicos"),
        (fmt(stats["languages"]), "Lenguajes", "en código público"),
        (fmt(stats["releases"]), "Releases", "publicadas"),
    ]

    # --- barra de lenguajes -------------------------------------------------
    ordered = sorted(stats["bytes"].items(), key=lambda kv: kv[1], reverse=True)
    total_bytes = sum(stats["bytes"].values()) or 1
    top = ordered[:TOP_LANGS]
    rest = ordered[TOP_LANGS:]

    parts = []
    offset = 0.0
    segments = [(name, size) for name, size in top]
    if rest:
        segments.append((f"otros:{len(rest)}", sum(size for _, size in rest)))

    for name, size in segments:
        width = size / total_bytes * 1000
        color = OTHER_COLOR if name.startswith("otros:") else LANG_COLORS.get(name, OTHER_COLOR)
        parts.append(
            f'<rect x="{offset:.3f}" y="0" width="{width:.3f}" height="14" fill="{color}"/>'
        )
        offset += width

    legend_rows = []
    row_y = 0
    for index, (name, size) in enumerate(top):
        share = size / total_bytes * 100
        bar = max(share / (top[0][1] / total_bytes * 100) * 470, 1.5)
        legend_rows.append(
            f'<text x="0" y="{row_y + 12}" class="lang">{esc(name)}</text>'
            f'<rect x="150" y="{row_y + 3}" width="{bar:.1f}" height="11" rx="5.5" fill="{LANG_COLORS.get(name, OTHER_COLOR)}"/>'
            f'<text x="620" y="{row_y + 12}" class="pct">{share:.1f}%</text>'
        )
        row_y += 24
    if rest:
        rest_bytes = sum(size for _, size in rest)
        share = rest_bytes / total_bytes * 100
        bar = max(share / (top[0][1] / total_bytes * 100) * 470, 1.5)
        legend_rows.append(
            f'<text x="0" y="{row_y + 12}" class="lang">Otros ({len(rest)})</text>'
            f'<rect x="150" y="{row_y + 3}" width="{bar:.1f}" height="11" rx="5.5" fill="{OTHER_COLOR}"/>'
            f'<text x="620" y="{row_y + 12}" class="pct">{share:.1f}%</text>'
        )
        row_y += 24

    # --- medidas ------------------------------------------------------------
    tile_w, gap, pad = 226, 16, 24
    tiles_svg = []
    for index, (value, label, sub) in enumerate(tiles):
        x = pad + index * (tile_w + gap)
        tiles_svg.append(
            f'<g transform="translate({x},24)">'
            f'<rect width="{tile_w}" height="118" rx="14" fill="#12121c" stroke="#ffffff" stroke-opacity="0.08"/>'
            f'<rect width="3" height="118" rx="1.5" fill="url(#accent)" class="accent" style="animation-delay:{index * 0.7:.1f}s"/>'
            f'<text x="22" y="58" class="num">{esc(value)}</text>'
            f'<text x="22" y="82" class="label">{esc(label)}</text>'
            f'<text x="22" y="100" class="sub">{esc(sub)}</text>'
            f"</g>"
        )

    legend_height = row_y
    height = 228 + legend_height + 26

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-label="Estadísticas del perfil de {LOGIN}">
  <defs>
    <linearGradient id="accent" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#c084fc"/>
      <stop offset="100%" stop-color="#6366f1"/>
    </linearGradient>
    <linearGradient id="num" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#d8b4fe"/>
    </linearGradient>
    <style>
      text {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
      .num {{ font-size: 38px; font-weight: 700; fill: url(#num); }}
      .label {{ font-size: 13px; font-weight: 600; letter-spacing: 0.6px; fill: #b9a3f7; }}
      .sub {{ font-size: 11px; letter-spacing: 0.4px; fill: #6b6b85; }}
      .section {{ font-size: 12px; font-weight: 700; letter-spacing: 2px; fill: #8b8ba7; }}
      .lang {{ font-size: 13px; fill: #c9c9d6; }}
      .pct {{ font-size: 12px; fill: #8b8ba7; text-anchor: end; }}
      .accent {{ animation: breathe 6s ease-in-out infinite; }}
      @keyframes breathe {{ 0%, 100% {{ opacity: 0.5; }} 50% {{ opacity: 1; }} }}
      @media (prefers-reduced-motion: reduce) {{ .accent {{ animation: none; }} }}
    </style>
  </defs>

  <rect width="1000" height="{height}" rx="18" fill="#0a0a12"/>
  <rect x="0.5" y="0.5" width="999" height="{height - 1}" rx="18" fill="none" stroke="#ffffff" stroke-opacity="0.08"/>

  {"".join(tiles_svg)}

  <text x="{pad}" y="182" class="section">LENGUAJES · CÓDIGO PÚBLICO</text>
  <g transform="translate({pad},196)">{''.join(parts)}</g>

  <g transform="translate({pad},228)">
    {"".join(legend_rows)}
  </g>
</svg>
"""


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("Falta GITHUB_TOKEN en el entorno.", file=sys.stderr)
        return 1

    stats = collect(token)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(stats), encoding="utf-8")

    print(f"{OUTPUT.relative_to(REPO_ROOT)} generado")
    print(
        f"  contribuciones={stats['contributions']} repos={stats['repos']} "
        f"lenguajes={stats['languages']} releases={stats['releases']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
