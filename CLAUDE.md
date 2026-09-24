# CLAUDE.md

## Project Overview

This is a ComfyUI custom node called **JPEG is Fine** — a focused, minimal JPEG-saving node optimized for high-quality output with proper chroma handling.

The node is inspired by [save-image-extended-comfyui](https://github.com/audioscavenger/save-image-extended-comfyui) but deliberately simpler: JPEG-only, no format switching, no complex filename templating. It does one thing well.

## Goals

1. **High-quality JPEG output** with 4:4:4 chroma subsampling (no chroma subsampling loss)
2. **Predictable file naming** with counter-based collision avoidance
3. **Workflow preservation** via embedded EXIF metadata and optional JSON export
4. **Windows compatibility** as the primary development platform
5. **Minimal, clean interface** — only the controls that matter

## Technical Requirements

- Python 3.10+
- Pillow (PIL) for image saving — already available in ComfyUI
- No additional dependencies beyond what ComfyUI provides
- Uses `pathlib.Path` for cross-platform path handling

## Development Environment

- Developed on Windows
- Node folder lives in `ComfyUI/custom_nodes/jpeg-is-fine/` (any folder name works — imports are relative)
- For development, link the repo into `custom_nodes` (a directory junction on Windows) instead of copying it. Remove the link before installing the published node from the registry, or two `JPEGIsFine` nodes will clash
- Testing: restart ComfyUI after code changes, refresh browser
- Check terminal output for Python errors on startup

## Project Structure

```
jpeg-is-fine/
├── __init__.py              # Node registration (NODE_CLASS_MAPPINGS)
├── jpeg_is_fine.py          # Main node implementation
├── pyproject.toml           # Package metadata for ComfyUI registry
├── requirements.txt         # Dependencies (empty - uses ComfyUI builtins)
├── LICENSE                  # MIT
├── .gitignore
├── .comfyignore             # Tracked files left out of the registry download
├── .github/workflows/
│   └── publish_action.yml   # Publishes to the Comfy Registry when pyproject.toml changes on main
├── CLAUDE.md                # This file
├── project-specifics.md     # Detailed specifications
└── README.md                # User-facing documentation
```

## Publishing

- GitHub repo and Comfy Registry node ID are both `jpeg-is-fine`. The registry ID is permanent — never rename `name` in `pyproject.toml`
- Release = bump `version` in `pyproject.toml` and push to `main`; the GitHub Action publishes it (needs the `REGISTRY_ACCESS_TOKEN` secret)
- Everything in the repo is public. Keep out anything identifying the author or their machine: local paths, computer name, real name, personal email. `__pycache__/` is ignored because `.pyc` files embed absolute local paths
- Commit metadata is public too: the repo-local git identity is the GitHub noreply address, and commits are made with `TZ=UTC0 git commit` (Git Bash) so timestamps don't reveal the author's timezone

## Key Implementation Notes

### JPEG Save Call

```python
pil_image.save(
    filepath,
    "JPEG",
    quality=quality,      # User-specified, default 92
    subsampling=0,        # Hardcoded: 4:4:4, no chroma subsampling
    optimize=True,        # Hardcoded: optimized Huffman tables
    exif=exif_data,       # Workflow JSON in tag 270
)
```

Do NOT specify `progressive=True` — we want baseline JPEG (Pillow's default) so every decoder can read it, including baseline-only hardware decoders. `optimize=True` gets part of progressive's size gain without leaving baseline: on real renders at quality 92 it saves ~2% (progressive ~4%), with pixel-identical output.

### Hidden Inputs

The node receives workflow data via ComfyUI's hidden input mechanism:

```python
"hidden": {
    "prompt": "PROMPT",
    "extra_pnginfo": "EXTRA_PNGINFO",
}
```

Both are combined into a single JSON object for EXIF embedding. The JSON export uses only `extra_pnginfo["workflow"]`, the format ComfyUI can load (see project-specifics.md).

### Output

The node passes `images` through unchanged (`RETURN_TYPES = ("IMAGE",)`) so it can sit mid-chain, but stays `OUTPUT_NODE = True`, so it runs even when the output is unconnected.

### Path Handling

Always use `pathlib.Path` for path operations:

```python
from pathlib import Path
output_path = Path(base_dir) / subdirectory / filename
```

Never manually concatenate paths with string operations or worry about slash direction.

`filename_prefix` and `delimiter` are plain names, never paths: characters invalid in Windows filenames (`/ \ : * ? " < > |`, control chars) are replaced with `_` before anything else uses them (counter scan, JSON names). Subfolders come only from `directory`, which must stay inside the output folder: absolute paths, drive letters and `..` raise `ValueError`.

### EXIF Metadata

- Use EXIF tag 270 (ImageDescription) for workflow JSON
- Keep it under ~60KB to stay within JPEG EXIF limits: if too large, drop the `workflow` key (then everything) and log a warning. Never truncate — truncated JSON can't be parsed
- Pillow's `Image.Exif()` class handles encoding
- ComfyUI's frontend can't load workflows from JPEGs: it reads PNG, WebP, AVIF, audio, video, SVG, GLB and JSON, and a dropped JPEG becomes a Load Image node. The embedded JSON is for archiving and other tools. The JSON export is how users reopen a workflow in ComfyUI
- Decided against (2026-09): a frontend extension that loads workflows from dropped JPEGs, because it would replace that drop-to-Load-Image default. Also decided against ComfyUI's WebP EXIF layout (`workflow:`/`prompt:` in the Make/Model tags), because photo apps would show the JSON as camera maker and model. Revisit only if ComfyUI adds native JPEG workflow loading, and then match the layout it reads

### Counter Logic

- Scan target directory for existing files matching the prefix pattern
- Extract highest counter value
- Start new saves at max + 1
- Handle batches by incrementing counter for each image

## What This Node Does NOT Do

- No format selection (JPEG only, always `.jpeg` extension)
- No preview display (users chain a Preview Image node)
- No filename key templating (just prefix + delimiter + counter)
- No progressive JPEG option
- No chroma subsampling options (always 4:4:4)

## References

- [Pillow JPEG documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg)
- [Pillow ExifTags module](https://pillow.readthedocs.io/en/stable/reference/ExifTags.html)
- [save-image-extended-comfyui](https://github.com/audioscavenger/save-image-extended-comfyui) for reference implementation patterns
