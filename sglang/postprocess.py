"""
Post-process SGLang batch OCR output into clean markdown.

Usage:
    python -m sglang.postprocess --pdf <pdf_path> --input_dir <sglang_output_dir> [--output_dir <dir>]
    # or via the root shim:
    python postprocess_sglang.py --pdf <pdf_path> --input_dir <sglang_output_dir> [--output_dir <dir>]

Steps:
  1. Render PDF pages to images (for cropping referenced image regions)
  2. Read per-page SGLang output files
  3. Crop images from referenced bounding boxes, embed as ![](images/...)
  4. Strip <|det|>bbox tags, keep content text
  5. Merge into single result.md
"""

import argparse
import os
import re
import shutil
import sys

from PIL import Image

from model.pdf_render import pdf_to_images


def _open_pil_images(paths: list[str]) -> list[Image.Image]:
    return [Image.open(p).convert("RGB") for p in paths]


def crop_and_save_image(page_img: Image.Image, bbox_999: list[int],
                         output_images_dir: str, filename: str) -> str:
    """Crop a region from the page image using 0-999 normalized bbox.

    Returns the relative path for markdown embedding.
    """
    w, h = page_img.size
    x1 = int(bbox_999[0] / 999 * w)
    y1 = int(bbox_999[1] / 999 * h)
    x2 = int(bbox_999[2] / 999 * w)
    y2 = int(bbox_999[3] / 999 * h)
    cropped = page_img.crop((x1, y1, x2, y2))
    rel_path = f"images/{filename}"
    abs_path = os.path.join(output_images_dir, filename)
    cropped.save(abs_path, "JPEG", quality=92)
    return rel_path


def process_page(text: str, page_idx: int, page_img: Image.Image,
                 output_images_dir: str) -> str:
    """Process one page's raw model output into clean markdown."""
    os.makedirs(output_images_dir, exist_ok=True)

    # Find all det tags with their positions
    pattern = r"<\|det\|>\s*([A-Za-z_][\w-]*)\s*(\[[^\]]+\])\s*<\|/det\|>"
    tags = []
    for m in re.finditer(pattern, text, re.DOTALL):
        tags.append({
            "start": m.start(),
            "end": m.end(),
            "label": m.group(1).strip(),
            "bbox_999": eval(m.group(2)),
        })

    if not tags:
        return text

    # Build output by walking through tags
    result = []
    img_idx = 0

    for tag in tags:
        # Content after this tag = from tag end to next tag start (or end of text)
        next_start = len(text)
        for t2 in tags:
            if t2["start"] > tag["end"]:
                next_start = t2["start"]
                break

        content = text[tag["end"]:next_start].strip()
        label = tag["label"]

        if label == "image":
            # Crop image from page
            if len(tag["bbox_999"]) >= 4:
                fname = f"page_{page_idx:04d}_{img_idx}.jpg"
                rel = crop_and_save_image(page_img, tag["bbox_999"],
                                           output_images_dir, fname)
                result.append(f"![]({rel})")
                img_idx += 1
        elif label in ("image_caption", "page_number", "header", "footer"):
            # These can be kept as plain text or dropped
            if content:
                result.append(content)
        else:
            # text, title, table, equation, etc.
            if content:
                result.append(content)

    return "\n\n".join(result)


def collect_input_files(input_dir: str) -> list[str]:
    """Collect per-page markdown files sorted by page number."""
    files = [f for f in os.listdir(input_dir)
             if f.endswith(".md") and f != "result.md"]
    # Sort naturally by page number in filename
    def sort_key(f):
        nums = re.findall(r"(\d+)", f)
        return int(nums[-1]) if nums else 0
    files.sort(key=sort_key)
    return [os.path.join(input_dir, f) for f in files]


def main():
    parser = argparse.ArgumentParser(
        description="Post-process SGLang OCR output into clean markdown",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pdf", required=True, help="Original PDF file path")
    parser.add_argument("--input_dir", default="./outputs",
                        help="Directory with per-page SGLang .md files")
    parser.add_argument("--output_dir", default=None,
                        help="Output directory (default: same as input_dir)")
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    if not os.path.isfile(args.pdf):
        print(f"Error: PDF not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    # 1. Render PDF pages
    print(f"Rendering PDF: {args.pdf}")
    page_paths, tmp_dir = pdf_to_images(args.pdf, prefix="sglang_pp_")
    page_images = _open_pil_images(page_paths)
    print(f"  → {len(page_images)} pages")

    # 2. Collect per-page SGLang output files
    input_files = collect_input_files(input_dir)
    if not input_files:
        print(f"Error: No per-page .md files found in {input_dir}", file=sys.stderr)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)
    print(f"  → {len(input_files)} SGLang output files")

    # 3. Set up output directories
    os.makedirs(output_dir, exist_ok=True)
    output_images_dir = os.path.join(output_dir, "images")
    os.makedirs(output_images_dir, exist_ok=True)

    # 4. Process each page
    pages_clean = []
    for page_idx, (input_file, page_img) in enumerate(zip(input_files, page_images)):
        with open(input_file, encoding="utf-8") as f:
            raw = f.read()
        clean = process_page(raw, page_idx, page_img, output_images_dir)
        pages_clean.append(clean)
        print(f"  [{page_idx + 1}] {os.path.basename(input_file)}")

    # 5. Merge into single result.md
    merged = "<PAGE>\n" + "\n<PAGE>\n".join(pages_clean)
    result_path = os.path.join(output_dir, "result.md")
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(merged)

    # 6. Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n✅ Done! Output: {result_path}")
    print(f"   Images:  {output_images_dir}/")


if __name__ == "__main__":
    main()
