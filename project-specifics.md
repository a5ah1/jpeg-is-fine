# Project Specifications

## Node Inputs

### Required Inputs

| Input | Type | Default | Range/Options | Description |
|-------|------|---------|---------------|-------------|
| `images` | IMAGE | (required) | — | Input images from upstream node |
| `filename_prefix` | STRING | `"image"` | — | Base name for output files (cleaned, see below) |
| `directory` | STRING | `""` | — | Subdirectory under ComfyUI output folder; empty = output root |
| `delimiter` | STRING | `"-"` | — | Character(s) between prefix and counter (cleaned, see below) |
| `counter_digits` | INT | `4` | 1–8 | Zero-padding width (4 → `0001`) |
| `quality` | INT | `92` | 1–100 | JPEG quality setting |
| `save_workflow_json` | COMBO | `"Subdirectory"` | `Disabled`, `Sidecar`, `Subdirectory` | JSON export mode |

### Hidden Inputs

| Input | Type | Description |
|-------|------|-------------|
| `prompt` | PROMPT | Node execution data from ComfyUI |
| `extra_pnginfo` | EXTRA_PNGINFO | Workflow metadata from ComfyUI |

These hidden inputs are automatically provided by ComfyUI and contain the workflow data for embedding.

## Node Output

| Output | Type | Description |
|--------|------|-------------|
| `images` | IMAGE | The input images, unchanged (pass-through) |

The node is still an output node (`OUTPUT_NODE = True`), so it runs whether or not the output is connected. The pass-through only lets it sit mid-chain. Users who need to preview can chain a Preview Image node from this output or from the same source feeding this node.

## File Naming

### Pattern
```
{filename_prefix}{delimiter}{counter:0{counter_digits}d}.jpeg
```

### Examples
| Settings | Output |
|----------|--------|
| prefix=`render`, delimiter=`_`, digits=4 | `render_0001.jpeg` |
| prefix=`photo`, delimiter=`-`, digits=3 | `photo-001.jpeg` |
| prefix=`out`, delimiter=`_`, digits=6 | `out_000001.jpeg` |

### Filename Cleaning
`filename_prefix` and `delimiter` are plain names, never paths. Before they are used anywhere (filenames, counter scan, workflow JSON names), every character Windows forbids in filenames is replaced with `_`:

```
/ \ : * ? " < > |   and control characters (0x00–0x1F)
```

| Input | Saved as (default delimiter) |
|-------|------------------------------|
| `a/b` or `a\b` | `a_b-0001.jpeg` |
| `12:30` | `12_30-0001.jpeg` |
| `what?` | `what_-0001.jpeg` |

A warning is logged to the ComfyUI console when a value is changed, and the input tooltips state the rule. Cleaning (rather than rejecting) is deliberate: prefixes are often wired from other nodes (e.g. checkpoint names containing `\`), and those values can't be validated before the run.

Without cleaning, a slash made the save land in a subfolder while the counter scan (which only matches plain filenames) never found previous saves, so every run overwrote `..._0001.jpeg`.

### Counter Behavior
- One counter per directory (always)
- Counter position: always at end of filename
- On save: scan directory for existing `{prefix}{delimiter}*.jpeg` files, extract max counter, start at max + 1
- Empty directory: start at 1
- Gaps in numbering: ignored (always use max + 1)
- Batch images: increment counter for each image in batch

## Directory Handling

### Output Directory Resolution
```
{ComfyUI output folder} / {directory input}
```

- Empty `directory` input → save directly to ComfyUI output folder
- Relative path in `directory` → resolved relative to ComfyUI output folder; `/` (and `\` on Windows) create nested folders
- Absolute paths, drive letters (including drive-relative `C:foo`), UNC paths and any `..` component → `ValueError` (the node never writes outside the output folder, matching ComfyUI's built-in Save Image)
- Each folder name is cleaned with the same rule as filenames (e.g. `renders/12:30` → `renders/12_30`)
- Directory auto-created if it doesn't exist (`mkdir(parents=True)`)

### Workflow JSON Subdirectory
When `save_workflow_json` = `"Subdirectory"`:
```
{output directory} / {filename_prefix}_workflows / {filename_prefix}{delimiter}{counter}.json
```

Example: if saving `render-0001.jpeg` to `output/my_project/`:
```
output/my_project/render-0001.jpeg
output/my_project/render_workflows/render-0001.json
```

The prefix-based subdirectory name (`{prefix}_workflows`) prevents collisions when multiple save nodes target the same directory with different prefixes.

### Sidecar JSON
When `save_workflow_json` = `"Sidecar"`:
```
{output directory} / {filename_prefix}{delimiter}{counter}.json
```

Same location and base name as the image, just with `.json` extension.

## JPEG Settings

| Setting | Value | Notes |
|---------|-------|-------|
| Quality | User-specified (default 92) | Range 1–100 |
| Subsampling | `0` (4:4:4) | Hardcoded, no option |
| Progressive | Baseline (not progressive) | Pillow default, don't specify |
| Huffman tables | Optimized (`optimize=True`) | Hardcoded, no option. Lossless: same pixels, smaller file |
| Extension | `.jpeg` | Always, never `.jpg` |

### Pillow Save Call
```python
image.save(
    filepath,
    "JPEG",
    quality=quality,
    subsampling=0,
    optimize=True,
    exif=exif_data
)
```

### Why Baseline + Optimize, Not Progressive
Measured on 60 real ComfyUI renders (~1 MP, 4:4:4, Pillow 11 / libjpeg-turbo 3):

| Variant | Size at q92 | Size at q98 | Decode time |
|---------|-------------|-------------|-------------|
| Baseline | — | — | 1× |
| Baseline + `optimize=True` | −1.8% | −6.8% | 1× |
| Progressive | −4.1% | −10.1% | ~2.2× |

Decoded pixels are identical in all three: progressive and optimize only change how the same coefficients are stored, never image quality. Progressive's extra ~2% isn't worth giving up baseline, which every decoder reads (some hardware decoders are baseline-only).

## Metadata Handling

### Two Different JSON Formats

ComfyUI provides two hidden inputs: `prompt` (execution data) and `extra_pnginfo` (contains `workflow`). These are used differently:

| Purpose | Content | Why |
|---------|---------|-----|
| EXIF embedding | Full `prompt` + `extra_pnginfo` combined | Complete reproducibility data |
| JSON file export | Just `extra_pnginfo["workflow"]` | ComfyUI-compatible for drag-and-drop loading |

**Important:** ComfyUI's workflow loader expects the workflow JSON structure directly, with a `version` field at the root. If you wrap it in another object or include `prompt` at the top level, ComfyUI will reject it with a Zod validation error about missing `version`.

### Embedded EXIF

| Tag ID | Tag Name | Content |
|--------|----------|---------|
| 270 | ImageDescription | Full JSON (prompt + workflow), size-limited as below |

### Size Limit
- JPEG EXIF limit: ~64KB total for APP1 segment
- Embedded JSON must be ≤ 60,000 bytes to leave headroom (`json.dumps` escapes non-ASCII, so characters = bytes)
- If the full JSON is too large: embed it without the `workflow` key (prompt is kept) and log a warning
- If that's still too large: embed nothing and log a warning
- Never truncate: truncated JSON can't be parsed, so it's useless for restoring anything. The JSON export (if enabled) always has the full workflow

### Exported JSON Content
The exported workflow JSON (from `extra_pnginfo["workflow"]`) follows ComfyUI's workflow schema:
- `version`: Must be present (currently `1`)
- `nodes`: All node configurations
- `links`: Connections between nodes
- `groups`, `reroutes`, `extra`: Additional UI state

This structure allows users to drag the JSON file directly into ComfyUI to restore the workflow.

## Collision Handling

### File Collisions
Inherently avoided via counter system:
1. Scan for `{prefix}{delimiter}*.jpeg`
2. Parse counter values from matching files
3. New counter = max existing + 1

Files are never overwritten by normal operation.

### Directory Collisions
```python
def ensure_directory(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise ValueError(f"Path exists but is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
```

### JSON Overwriting
If a sidecar/subdirectory JSON already exists for a counter value, it will be overwritten. This should only happen if:
- User manually created a JSON file
- Counter somehow wrapped around

This is acceptable — the JSON is paired to the image.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid directory path (file exists at path) | Raise clear error |
| `directory` absolute, has a drive letter, or contains `..` | Raise `ValueError` |
| Invalid filename characters in prefix/delimiter/folder names | Replace with `_`, log a warning |
| Pixel values outside [0, 1] (upscaler/VAE overshoot) | Clip to [0, 255] before converting to uint8 (unclipped, 1.02 wraps to 4 = near-black) |
| Workflow JSON too large for EXIF | Embed without `workflow`, or skip EXIF; log a warning |
| Permission denied | Let OSError propagate with context |
| Disk full | Let OSError propagate |
| Counter overflow (e.g., 9999 → 10000 with 4 digits) | Allow — filename exceeds digit width but saves successfully |
| Empty batch (0 images) | Do nothing, return gracefully |

## ComfyUI Integration

### Node Registration (`__init__.py`)
```python
from .jpeg_is_fine import JPEGIsFine

NODE_CLASS_MAPPINGS = {
    "JPEGIsFine": JPEGIsFine
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "JPEGIsFine": "JPEG is Fine"
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
```

### Node Class Structure
```python
class JPEGIsFine:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "image"}),
                "directory": ("STRING", {"default": ""}),
                "delimiter": ("STRING", {"default": "-"}),
                "counter_digits": ("INT", {"default": 4, "min": 1, "max": 8}),
                "quality": ("INT", {"default": 92, "min": 1, "max": 100}),
                "save_workflow_json": (["Disabled", "Sidecar", "Subdirectory"], {"default": "Subdirectory"}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def save_images(self, images, filename_prefix, directory, delimiter,
                    counter_digits, quality, save_workflow_json,
                    prompt=None, extra_pnginfo=None):
        # Implementation
        return (images,)
```

### Output Folder Access
```python
import folder_paths
output_dir = folder_paths.get_output_directory()
```

## Testing Checklist

- [ ] Single image save
- [ ] Batch image save (multiple images)
- [ ] Counter increments correctly across saves
- [ ] Counter finds max in directory with gaps
- [ ] Empty directory starts at 1
- [ ] Subdirectory creation works
- [ ] Workflow subdirectory created with correct name
- [ ] Sidecar JSON saved alongside image
- [ ] EXIF metadata readable with exiftool or similar
- [ ] Large workflow: EXIF still parseable JSON, workflow dropped, warning logged
- [ ] Prefix with `/`, `\`, `:` or `?` is cleaned and the counter keeps advancing across runs
- [ ] `directory` with `..`, a drive letter or an absolute path is rejected
- [ ] Bright highlights (values > 1.0) stay white, not dark specks
- [ ] Quality setting affects file size appropriately
- [ ] Output passes the input images through unchanged, and the node still runs with the output unconnected
- [ ] Works on Windows paths
- [ ] Works on Linux/Mac paths (if possible to test)
