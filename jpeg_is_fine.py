import json
import logging
import re
from pathlib import Path

import numpy as np
from PIL import Image

import folder_paths

# Characters Windows forbids in filenames (a superset of Linux/macOS), plus control characters
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# ~60KB leaves headroom within the 64KB JPEG APP1 (EXIF) segment limit
MAX_EXIF_JSON_LENGTH = 60000


class JPEGIsFine:
    """ComfyUI node for saving high-quality JPEG images with 4:4:4 chroma subsampling."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {
                    "default": "image",
                    "tooltip": 'Base name for saved files. Characters not allowed in filenames (/ \\ : * ? " < > |) '
                               "are replaced with _. Use 'directory' for subfolders.",
                }),
                "directory": ("STRING", {
                    "default": "",
                    "tooltip": "Subfolder inside the ComfyUI output folder (use / for nested folders). "
                               "Leave empty to save to the output folder itself. Absolute paths and '..' are not allowed.",
                }),
                "delimiter": ("STRING", {
                    "default": "-",
                    "tooltip": 'Text between the prefix and the counter. Characters not allowed in filenames (/ \\ : * ? " < > |) '
                               "are replaced with _.",
                }),
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
    OUTPUT_TOOLTIPS = ("The input images, unchanged. Connect only if you need to chain further nodes.",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image"

    def save_images(
        self,
        images,
        filename_prefix: str,
        directory: str,
        delimiter: str,
        counter_digits: int,
        quality: int,
        save_workflow_json: str,
        prompt=None,
        extra_pnginfo=None,
    ):
        # Handle empty batch
        if images is None or len(images) == 0:
            return (images,)

        # Prefix and delimiter are plain names; subfolders come only from `directory`
        filename_prefix = self._clean_name(filename_prefix, "filename_prefix")
        delimiter = self._clean_name(delimiter, "delimiter")

        # Resolve output directory
        output_dir = self._resolve_output_dir(directory)
        self._ensure_directory(output_dir)

        # Build workflow JSON for embedding (full data) and export (ComfyUI-compatible)
        exif_json = self._build_exif_json(prompt, extra_pnginfo)
        workflow_json = self._build_workflow_json(extra_pnginfo)

        # Find starting counter
        counter = self._get_next_counter(output_dir, filename_prefix, delimiter)

        # Save each image in batch
        saved_files = []
        for image_tensor in images:
            # Convert from tensor to PIL Image
            # ComfyUI images are float32 tensors in range [0, 1] with shape (H, W, C)
            # Clip first: values slightly outside [0, 1] would otherwise wrap around (1.02 -> 4)
            image_array = np.clip(image_tensor.cpu().numpy() * 255, 0, 255).astype(np.uint8)
            pil_image = Image.fromarray(image_array, mode="RGB")

            # Build filename
            counter_str = str(counter).zfill(counter_digits)
            filename = f"{filename_prefix}{delimiter}{counter_str}.jpeg"
            filepath = output_dir / filename

            # Build EXIF data with full workflow + prompt data
            exif_data = self._build_exif(exif_json)

            # Save baseline JPEG with 4:4:4 chroma subsampling
            pil_image.save(
                filepath,
                "JPEG",
                quality=quality,
                subsampling=0,  # 4:4:4, no chroma subsampling
                optimize=True,  # optimized Huffman tables: ~2% smaller, identical pixels, still baseline
                exif=exif_data,
            )

            saved_files.append(filepath)

            # Save workflow JSON if enabled
            if save_workflow_json != "Disabled" and workflow_json:
                self._save_workflow_json(
                    output_dir,
                    filename_prefix,
                    delimiter,
                    counter_str,
                    workflow_json,
                    save_workflow_json,
                )

            counter += 1

        # Pass the images through unchanged so the node can sit mid-chain
        return (images,)

    def _clean_name(self, value: str, input_name: str) -> str:
        """Replace characters that aren't allowed in filenames with underscores."""
        cleaned = INVALID_FILENAME_CHARS.sub("_", value)
        if cleaned != value:
            logging.warning(f"[JPEG is Fine] {input_name} {value!r} contains characters not allowed in filenames; using {cleaned!r}")
        return cleaned

    def _resolve_output_dir(self, directory: str) -> Path:
        """Resolve `directory` inside the ComfyUI output folder, rejecting paths that would leave it."""
        output_base = Path(folder_paths.get_output_directory())
        if not directory:
            return output_base

        dir_path = Path(directory)
        # anchor catches absolute paths, drive letters (including drive-relative "C:foo") and UNC shares
        if dir_path.anchor or ".." in dir_path.parts:
            raise ValueError(
                f"directory must be a relative path inside the ComfyUI output folder "
                f"(no absolute paths, drive letters or '..'): {directory!r}"
            )

        return output_base.joinpath(*(self._clean_name(part, "directory") for part in dir_path.parts))

    def _ensure_directory(self, path: Path) -> None:
        """Create directory if it doesn't exist, error if path exists but isn't a directory."""
        if path.exists() and not path.is_dir():
            raise ValueError(f"Path exists but is not a directory: {path}")
        path.mkdir(parents=True, exist_ok=True)

    def _get_next_counter(self, output_dir: Path, prefix: str, delimiter: str) -> int:
        """Scan directory for existing files and return the next counter value."""
        # Escape special regex characters in prefix and delimiter
        escaped_prefix = re.escape(prefix)
        escaped_delimiter = re.escape(delimiter)
        pattern = re.compile(rf"^{escaped_prefix}{escaped_delimiter}(\d+)\.jpeg$", re.IGNORECASE)

        max_counter = 0
        if output_dir.exists():
            for filepath in output_dir.iterdir():
                if filepath.is_file():
                    match = pattern.match(filepath.name)
                    if match:
                        counter_val = int(match.group(1))
                        max_counter = max(max_counter, counter_val)

        return max_counter + 1

    def _build_exif_json(self, prompt, extra_pnginfo) -> str | None:
        """Build JSON string with full prompt + workflow data for EXIF embedding.

        If that's too large for EXIF, the workflow is dropped rather than truncated,
        since truncated JSON can't be parsed. The JSON export still has the full workflow.
        """
        if prompt is None and extra_pnginfo is None:
            return None

        workflow_data = {}
        if prompt is not None:
            workflow_data["prompt"] = prompt
        if extra_pnginfo is not None:
            workflow_data.update(extra_pnginfo)

        if not workflow_data:
            return None

        # json.dumps escapes non-ASCII by default, so length in characters equals length in bytes
        full_json = json.dumps(workflow_data, separators=(",", ":"))
        if len(full_json) <= MAX_EXIF_JSON_LENGTH:
            return full_json

        without_workflow = {key: value for key, value in workflow_data.items() if key != "workflow"}
        if without_workflow:
            reduced_json = json.dumps(without_workflow, separators=(",", ":"))
            if len(reduced_json) <= MAX_EXIF_JSON_LENGTH:
                logging.warning(
                    f"[JPEG is Fine] Workflow data too large for EXIF ({len(full_json)} bytes); "
                    f"embedding it without the workflow"
                )
                return reduced_json

        logging.warning(
            f"[JPEG is Fine] Workflow data too large for EXIF ({len(full_json)} bytes); not embedding it"
        )
        return None

    def _build_workflow_json(self, extra_pnginfo) -> str | None:
        """Extract the workflow JSON for ComfyUI-compatible export."""
        if extra_pnginfo is None:
            return None

        # extra_pnginfo contains a "workflow" key with the actual workflow structure
        workflow = extra_pnginfo.get("workflow")
        if workflow is None:
            return None

        return json.dumps(workflow, separators=(",", ":"))

    def _build_exif(self, workflow_json: str | None):
        """Build EXIF data with workflow JSON in ImageDescription tag."""
        exif = Image.Exif()

        if workflow_json:
            # Tag 270 is ImageDescription (size already limited by _build_exif_json)
            exif[270] = workflow_json

        return exif

    def _save_workflow_json(
        self,
        output_dir: Path,
        prefix: str,
        delimiter: str,
        counter_str: str,
        workflow_json: str,
        mode: str,
    ) -> None:
        """Save workflow JSON as a separate file."""
        json_filename = f"{prefix}{delimiter}{counter_str}.json"

        if mode == "Subdirectory":
            json_dir = output_dir / f"{prefix}_workflows"
            self._ensure_directory(json_dir)
            json_path = json_dir / json_filename
        else:  # Sidecar
            json_path = output_dir / json_filename

        json_path.write_text(workflow_json, encoding="utf-8")
