# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Mima** is a FastAPI-based web application that serves a local TV show library. It reads Kodi-style `.nfo` metadata files to index shows and episodes, then provides a web interface to browse and stream video content.

### Key Architecture

- **FastAPI** with Tagflow for HTML generation - class lists can be nested arbitrarily and get concatenated with spaces, text content must be added using `text(...)` within tag contexts
- **Python 3.13** features used throughout (pattern matching, modern type hints, slots)
- **Uniform sticky header** across all routes (Home → Show → Episode)
- **Cached scanning** of filesystem using `@lru_cache` for performance
- **Video serving** via FastAPI FileResponse for direct streaming

### Core Components

- `Episode` and `Show` dataclasses represent the content model
- `scan()` function indexes `.nfo` files from `BASE_PATH` (/Volumes/Lootbox/tv)
- XML parsing handles both `<tvshow>` and `<episodedetails>` formats
- Fuzzy file matching connects metadata to actual video/thumbnail files
- Responsive card grids with thumbnail mosaics for visual browsing

## Development Commands

### Running the Application
```bash
# Run with auto-reload during development
python -m mima.main

# Or via uvicorn directly
uvicorn mima.main:app --host 0.0.0.0 --port 8000 --reload
```

### Package Management
```bash
# Install dependencies
uv sync

# Add new dependency
uv add package_name

# Run the CLI entry point
mima
```

## Configuration

- `BASE_PATH`: Directory containing TV show files (currently `/Volumes/Lootbox/tv`)
- `VIDEO_EXTENSIONS`: Supported video formats (.mp4, .webm, .mkv, .avi)
- `THUMB_EXTENSION`: Thumbnail format (.tbn)

The application expects a specific directory structure with Kodi-compatible metadata files alongside video content.