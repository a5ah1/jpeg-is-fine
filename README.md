# JPEG is Fine

A focused, minimal JPEG-saving node for ComfyUI optimized for high-quality output with proper chroma handling.

## Features

- **4:4:4 chroma subsampling** — no color quality loss from chroma downsampling
- **Counter-based file naming** — automatic collision avoidance, no overwrites
- **Workflow preservation** — embedded in EXIF metadata and optional JSON export
- **Baseline JPEG** — maximum compatibility, with optimized encoding for smaller files at no quality cost

## Installation

**ComfyUI Manager (recommended):** open the Custom Nodes Manager, search for **JPEG is Fine** and click Install. Restart ComfyUI when prompted.

**Manual:** clone the repository into your `custom_nodes` folder:

```
cd ComfyUI/custom_nodes
git clone https://github.com/a5ah1/jpeg-is-fine
```

Restart ComfyUI and refresh your browser. The folder name doesn't matter, and no extra Python packages are needed.

## Usage

Find the node under **image** category as **"JPEG is Fine"**.

### Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `images` | — | Input images from upstream node |
| `filename_prefix` | `image` | Base name for output files |
| `directory` | `""` | Subdirectory under ComfyUI output folder (use `/` for nesting) |
| `delimiter` | `-` | Character(s) between prefix and counter |
| `counter_digits` | `4` | Zero-padding width (4 = `0001`) |
| `quality` | `92` | JPEG quality (1-100) |
| `save_workflow_json` | `Subdirectory` | JSON export mode |

### Output

| Output | Description |
|--------|-------------|
| `images` | The input images, unchanged. Optional: leave it unconnected, or use it to chain further nodes after saving |

### File Naming

Files are named `{prefix}{delimiter}{counter}.jpeg`:

- `render-0001.jpeg`
- `photo_001.jpeg`
- `out-000001.jpeg`

The counter automatically increments based on existing files in the directory.

Characters that aren't allowed in filenames (`/ \ : * ? " < > |`) are replaced with `_` in the prefix and delimiter, so `SDXL\model` or `12:30` become `SDXL_model` and `12_30`. The node logs a warning in the console when this happens. To save into subfolders, use `directory`.

`directory` is always inside the ComfyUI output folder. Absolute paths, drive letters and `..` are rejected with an error.

### Workflow JSON Export

- **Disabled** — No JSON export
- **Sidecar** — JSON saved alongside the image (`render-0001.json`)
- **Subdirectory** — JSON saved to `{prefix}_workflows/` subfolder

Workflow data is always embedded in the JPEG's EXIF metadata (tag 270: ImageDescription), regardless of JSON export setting. EXIF has a ~64KB limit, so if the workflow is too large, only the prompt is embedded (a warning is logged). Enable JSON export if you work with very large workflows.

## Why "JPEG is Fine"?

JPEG gets a bad reputation, but with proper settings it's excellent for AI-generated images:

- **4:4:4 subsampling** preserves color detail that 4:2:0 (the default) destroys
- **Quality 92** is visually lossless for most content
- **Baseline JPEG** works everywhere
- File sizes are typically 5-10x smaller than PNG with no visible quality loss

## What This Node Doesn't Do

- No format switching (JPEG only)
- No preview (chain a Preview Image node)
- No filename templating (just prefix + counter)
- No progressive JPEG option
- No chroma subsampling options (always 4:4:4)

## License

MIT — see [LICENSE](LICENSE).
