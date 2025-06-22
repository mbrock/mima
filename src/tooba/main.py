from __future__ import annotations

"""A small FastAPI app that serves a local TV-show library.

• Targets **Python 3.13** (pattern-matching, `|` in type hints, slots etc.)
• Uses Tagflow’s **nested Tailwind lists** everywhere – no long strings.
• Provides a **uniform sticky header bar** on **every route** (Home → Show → Episode).
"""

from collections.abc import Generator
import hashlib
import unicodedata
import urllib.parse as ulp
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache, partial
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from tagflow import DocumentMiddleware, TagResponse, html, tag, text

# ───────────────────────────── constants ─────────────────────────────

BASE_PATH: Path = Path("/Volumes/Lootbox/tv")
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".webm", ".mkv", ".avi"})
THUMB_EXTENSION: str = ".tbn"

app = FastAPI(default_response_class=TagResponse)
app.add_middleware(DocumentMiddleware)

# ────────────────────────────── models ───────────────────────────────


@dataclass(slots=True)
class Episode:
    showtitle: str
    title: str
    season: str
    episode: str
    plot: str
    aired: Optional[str] = None
    video_file: Optional[str] = None
    thumbnail: Optional[str] = None

    def slug(self) -> str:  # noqa: D401 – one-liner OK
        raw = f"{self.showtitle}-s{self.season}e{self.episode}-{self.title}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:8]


@dataclass(slots=True)
class Show:
    title: str
    plot: str
    thumb: Optional[str] = None
    episodes: list[Episode] = field(default_factory=list)


# ──────────────────────────── utilities ──────────────────────────────


def _get(el: ET.Element, tagname: str) -> Optional[str]:
    if (node := el.find(tagname)) is not None:
        return node.text
    return None


# --- XML parsing helpers -------------------------------------------------------


def parse_nfo_file(nfo: Path) -> dict[str, str]:
    """Parse Kodi-style .nfo → *flat* meta mapping."""
    try:
        root = ET.parse(nfo).getroot()
    except ET.ParseError:  # malformed files are ignored
        return {}

    match root.tag:
        case "tvshow":
            return {
                "type": "show",
                "title": _get(root, "title") or "",
                "plot": _get(root, "plot") or "",
                "thumb": _get(root, "thumb") or "",
            }
        case "episodedetails":
            return {
                "type": "episode",
                "showtitle": _get(root, "showtitle") or "",
                "title": _get(root, "title") or "",
                "season": _get(root, "season") or "",
                "episode": _get(root, "episode") or "",
                "plot": _get(root, "plot") or "",
                "aired": _get(root, "aired") or "",
            }
        case _:
            return {}


# --- text normalisation --------------------------------------------------------


def normalize(txt: str) -> str:
    base = unicodedata.normalize("NFD", txt)
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    rm_punct = str.maketrans("", "", ",?!")
    return base.lower().replace(" ", ".").translate(rm_punct)


# --- file-matching -------------------------------------------------------------


def _match_file(nfo: Path, meta: dict[str, str], exts: frozenset[str]) -> Optional[str]:
    """Return first file path as *str* or *None*."""

    def _candidates() -> Generator[Path, None, None]:
        # 1) neighbour with same stem
        yield from (nfo.with_suffix(ext) for ext in exts)
        # 2) same stem anywhere under BASE_PATH
        yield from (
            p for p in BASE_PATH.rglob(f"{nfo.stem}*") if p.suffix.lower() in exts
        )

    for path in _candidates():
        if path.exists():
            return str(path)

    # 3) fuzzy – only for episodes
    if meta.get("type") != "episode":
        return None

    show, title = normalize(meta["showtitle"]), normalize(meta["title"])
    season, ep = meta["season"], meta["episode"]
    patterns = {f"s{season}e{ep}", f"s{season.zfill(2)}e{ep.zfill(2)}"}

    for p in BASE_PATH.rglob("*"):
        if p.suffix.lower() not in exts:
            continue
        stem = normalize(p.stem)
        if show in stem and (title in stem or any(tok in stem for tok in patterns)):
            return str(p)
    return None


find_video = partial(_match_file, exts=VIDEO_EXTENSIONS)
find_thumbnail = partial(_match_file, exts=frozenset({THUMB_EXTENSION}))


def show_key(title: str) -> str:
    return hashlib.md5(title.encode(), usedforsecurity=False).hexdigest()[:8]


# ─────────────── collection index   (cached, single item) ─────────────


@lru_cache(maxsize=1)
def scan() -> dict[str, Show]:
    shows: dict[str, Show] = {}
    for nfo in BASE_PATH.rglob("*.nfo"):
        if not nfo.is_file():
            continue
        meta = parse_nfo_file(nfo)
        match meta.get("type"):
            case "show":
                shows[show_key(meta["title"])] = Show(
                    title=meta["title"], plot=meta["plot"], thumb=meta["thumb"]
                )
            case "episode":
                ep = Episode(
                    showtitle=meta["showtitle"],
                    title=meta["title"],
                    season=meta["season"],
                    episode=meta["episode"],
                    plot=meta["plot"],
                    aired=meta.get("aired"),
                    video_file=find_video(nfo, meta),
                    thumbnail=find_thumbnail(nfo, meta),
                )
                shows.setdefault(
                    show_key(meta["showtitle"]), Show(title=meta["showtitle"], plot="")
                ).episodes.append(ep)
            case _:
                continue
    return shows


# ─────────────────────────── layout helpers ──────────────────────────


@contextmanager
def header(*, back_href: str | None = None):
    """Uniform sticky header context manager for flexible markup rendering."""
    classes = [
        "grid",
        "grid-cols-[auto_1fr]",
        "items-center",
        "gap-4",
        "px-6",
        "py-4",
        "bg-black/80",
        "backdrop-blur",
        "sticky",
        "top-0",
        "z-10",
    ]
    with tag.div(classes):
        # left cell – back arrow or logo
        if back_href:
            with tag.a(
                href=back_href,
                classes=[
                    "text-stone-400",
                    "hover:text-gray-300",
                    "text-2xl",
                    "p-2",
                    "rounded",
                    "hover:bg-white/10",
                    "transition-all",
                ],
            ):
                text("←")
        else:
            with tag.span("text-2xl", "p-2"):
                text("📺")

        # right cell – flexible content area
        with tag.div(["flex", "flex-col", "min-w-0"]):
            yield


@contextmanager
def document(*, title: str, back_href: str | None = None):
    with tag.html(lang="en"):
        with tag.head():
            tag.title(title)
            tag.meta(charset="utf-8")
            tag.meta(name="viewport", content="width=device-width, initial-scale=1")
            tag.script(src="https://cdn.tailwindcss.com")
            tag.link(rel="preconnect", href="https://fonts.googleapis.com")
            tag.link(
                rel="preconnect",
                href="https://fonts.gstatic.com",
                crossorigin="anonymous",
            )
            tag.link(
                href=(
                    "https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap"
                ),
                rel="stylesheet",
            )
        with tag.body(
            ["bg-black", "text-stone-400", "min-h-screen", "flex", "flex-col"]
        ):
            yield  # page-specific content with flexible header


# ─────────────────────────── components ──────────────────────────────


def card_grid(items, card_func):
    """Shared grid component for consistent card layouts."""
    with tag.div(
        [
            "grid",
            "grid-cols-1",
            "md:grid-cols-2",
            "lg:grid-cols-3",
            "gap-6",
            "p-6",
        ]
    ):
        for item in items:
            card_func(item)


def show_list(shows: dict[str, Show]):
    items = [(sid, show) for sid, show in shows.items()]
    card_grid(items, lambda item: show_card(item[1], f"/show/{item[0]}"))


def show_card(show: Show, href: str):
    with tag.a(
        [
            "block",
            "relative",
            "rounded-lg",
            "overflow-hidden",
            "hover:scale-[1.02]",
            "transition-transform",
            "duration-200",
        ],
        href=href,
    ):
        thumbs = [e.thumbnail for e in show.episodes if e.thumbnail][:4]
        if thumbs:
            with tag.div(["relative", "aspect-video", "bg-gray-900"]):
                if len(thumbs) == 1:
                    tag.img(
                        src=f"/thumbnail/{ulp.quote(thumbs[0][1:])}",
                        alt=f"{show.title} still",
                        classes=["w-full", "h-full", "object-cover"],
                        style="filter: blur(1px) brightness(0.4);",
                    )
                else:
                    # 2x2 grid of thumbnails
                    with tag.div(
                        ["grid", "grid-cols-2", "grid-rows-2", "h-full", "gap-0.5"]
                    ):
                        for idx, tbn in enumerate(thumbs):
                            tag.img(
                                src=f"/thumbnail/{ulp.quote(tbn[1:])}",
                                alt=f"{show.title} still {idx + 1}",
                                classes=[
                                    "w-full",
                                    "h-full",
                                    "object-cover",
                                ],
                                style="filter: blur(1px) brightness(0.4);",
                            )
                        # Fill remaining slots if less than 4 thumbnails
                        for _ in range(4 - len(thumbs)):
                            with tag.div(["bg-gray-800", "w-full", "h-full"]):
                                pass

                # Centered title overlay
                with tag.div(
                    [
                        "absolute",
                        "inset-0",
                        "flex",
                        "flex-col",
                        "items-center",
                        "justify-center",
                        "p-6",
                    ]
                ):
                    # Split title on colon for better hierarchy
                    if ":" in show.title:
                        main_title, subtitle = show.title.split(":", 1)
                        with tag.h2(
                            "text-3xl",
                            "text-white",
                            "font-bold",
                            "text-center",
                            "leading-tight",
                            "mb-1",
                            style="text-shadow: 0 0 12px rgba(0,0,0,0.8);",
                        ):
                            text(main_title.strip())
                        with tag.div(
                            "text-2xl",
                            "text-stone-200",
                            "font-medium",
                            "text-center",
                            "leading-tight",
                            "mb-2",
                            style="text-shadow: 0 0 8px rgba(0,0,0,0.8);",
                        ):
                            text(subtitle.strip())
                    else:
                        with tag.h2(
                            "text-3xl",
                            "text-white",
                            "font-semibold",
                            "text-center",
                            "leading-tight",
                            "mb-2",
                            style="text-shadow: 0 0 12px rgba(0,0,0,0.8);",
                        ):
                            text(show.title)


def episode_card(ep: Episode):
    with tag.a(
        "block",
        "rounded-lg",
        "overflow-hidden",
        "hover:scale-105",
        "transition-transform",
        "duration-200",
        href=f"/episode/{ep.slug()}",
    ):
        if ep.thumbnail:
            with tag.div(["relative", "aspect-video", "bg-gray-900"]):
                tag.img(
                    src=f"/thumbnail/{ulp.quote(ep.thumbnail[1:])}",
                    alt=f"{ep.title} thumb",
                    classes=["w-full", "h-full", "object-cover"],
                    style="filter: blur(1px) brightness(0.5);",
                )
                with tag.div(
                    [
                        "absolute",
                        "inset-0",
                        "flex",
                        "flex-row",
                        "gap-4",
                        "items-center",
                        "justify-center",
                        "p-4",
                    ]
                ):
                    if ep.season and ep.episode:
                        with tag.div(
                            "text-2xl",
                            "text-stone-400",
                            "font-medium",
                            "flex",
                            "flex-row",
                            style="text-shadow: 0 0 8px rgba(0,0,0,0.8);",
                        ):
                            # 1 is A, 2 is B, etc.
                            season_letter = chr(ord("A") + int(ep.season) - 1)
                            with tag.span("text-stone-500"):
                                text(f"{season_letter}")
                            with tag.span(
                                "font-medium",
                            ):
                                text(f"{ep.episode}")
                    with tag.h2(
                        "text-3xl",
                        "text-white",
                        "font-semibold",
                        "text-center",
                        "leading-tight",
                        style="text-shadow: 0 0 12px rgba(0,0,0,0.8);",
                    ):
                        text(ep.title)


# ────────────────────────────── routes ───────────────────────────────


@app.get("/")
def home():
    with document(title="Video Collection"):
        with header():
            with tag.h1("text-xl", "font-bold", "truncate"):
                text("Video Collection")
        show_list(scan())


@app.get("/show/{show_hash}")
def show_detail(show_hash: str):
    show = scan().get(show_hash)
    if show is None:
        return _not_found("Show Not Found", f"id={show_hash}")

    with document(title=show.title, back_href="/"):
        with header(back_href="/"):
            if ":" in show.title:
                main_title, subtitle = show.title.split(":", 1)
                with tag.h1("text-xl", "font-bold", "truncate"):
                    text(main_title.strip())
                with tag.span("text-sm", "text-stone-300", "truncate"):
                    text(subtitle.strip())
            else:
                with tag.h1("text-xl", "font-bold", "truncate"):
                    text(show.title)
        if show.episodes:
            episodes = sorted(show.episodes, key=lambda e: (e.season, e.episode))
            card_grid(episodes, episode_card)
        else:
            tag.p("No episodes found.", classes=["text-stone-400", "p-4"])


@app.get("/episode/{episode_hash}")
def episode_detail(episode_hash: str):
    ep = next(
        (e for s in scan().values() for e in s.episodes if e.slug() == episode_hash),
        None,
    )
    if ep is None:
        return _not_found("Episode Not Found", episode_hash)

    with document(
        title=f"{ep.season}×{ep.episode} {ep.title}",
        back_href=f"/show/{show_key(ep.showtitle)}",
    ):
        with header(back_href=f"/show/{show_key(ep.showtitle)}"):
            with tag.div(["flex", "flex-row", "items-center", "gap-2", "min-w-0"]):
                if ep.season and ep.episode:
                    # A2 format like in episode cards
                    season_letter = chr(ord("A") + int(ep.season) - 1)
                    with tag.div(
                        "text-lg",
                        "text-stone-400",
                        "font-medium",
                        "flex",
                        "flex-row",
                        "flex-shrink-0",
                    ):
                        with tag.span("text-stone-500"):
                            text(f"{season_letter}")
                        with tag.span("font-medium"):
                            text(f"{ep.episode}")

                    with tag.h1("text-xl", "font-bold", "truncate"):
                        text(ep.title)

            with tag.span(
                "text-sm", "text-stone-300", "truncate", "flex", "flex-row", "gap-2"
            ):
                if ":" in ep.showtitle:
                    main_title, subtitle = ep.showtitle.split(":", 1)
                    with tag.span():
                        text(main_title.strip())
                    with tag.span("font-semibold"):
                        text(subtitle.strip())
                else:
                    text(ep.showtitle)

        with tag.div(["flex-1", "flex", "items-center", "justify-center", "p-4"]):
            if ep.video_file:
                with tag.video(
                    controls=True, autoplay=True, classes=["max-w-full", "max-h-full"]
                ):
                    tag.source(
                        src=f"/video-file/{ulp.quote(ep.video_file[1:])}",
                        type="video/mp4",
                    )
                    text("Your browser does not support the <video> tag.")
            else:
                tag.p("No video file found.", classes=["text-white"])


# ─────────────────────────── static files ────────────────────────────


@app.get("/video-file/{path:path}")
def serve_video(path: str):
    f = Path("/" + ulp.unquote(path))
    if not f.is_file():
        raise HTTPException(404, "Video not found")
    return FileResponse(f)


@app.get("/thumbnail/{path:path}")
def serve_thumb(path: str):
    f = Path("/" + ulp.unquote(path))
    if not f.is_file():
        raise HTTPException(404, "Thumbnail not found")
    return FileResponse(f)


# ───────────────────────────── helpers ───────────────────────────────


def _not_found(title: str, msg: str):
    with document(title=title, back_href="/"):
        with header(back_href="/"):
            with tag.h1("text-xl", "font-bold", "truncate"):
                text(title)
        with tag.div(
            [
                "flex",
                "flex-col",
                "items-center",
                "justify-center",
                "flex-1",
                "p-8",
                "text-center",
            ]
        ):
            tag.h2(title, classes=["text-2xl", "font-bold", "text-red-600"])
            tag.p(msg, classes=["text-gray-400", "mt-2"])


# ───────────────────────────── run local ─────────────────────────────


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tooba.main:app", host="0.0.0.0", port=8000, reload=True)
