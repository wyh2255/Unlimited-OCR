"""
PDF → OCR → Markdown (单文件输出)

将 PDF 文档通过 Unlimited-OCR 转换为单个 Markdown 文件，
输出可直接用于翻译工作流。

用法:
    python ocp pdf <pdf文件> [-o ./output] [--model_dir ./model]
    python ocr_pdf.py <pdf文件> --no-page-split     # 去掉 <PAGE> 分隔符
"""

import argparse
import os
import re
import shutil
import sys

import torch
from transformers import AutoModel, AutoTokenizer

from model.pdf_render import pdf_to_images


def load_model(model_dir: str = "baidu/Unlimited-OCR"):
    """加载 Unlimited-OCR 模型。

    Args:
        model_dir: 本地模型目录路径，或 HuggingFace 模型 ID
    """
    # 本地路径则拼接，否则作为 HF model ID
    local_path = os.path.abspath(model_dir) if os.path.isdir(model_dir) else model_dir

    print(f"Loading tokenizer from: {local_path}")
    tokenizer = AutoTokenizer.from_pretrained(local_path, trust_remote_code=True)

    print(f"Loading model from: {local_path}")
    model = AutoModel.from_pretrained(
        local_path,
        trust_remote_code=True,
        use_safetensors=True,
        torch_dtype=torch.bfloat16,
    )
    model = model.eval().cuda()
    print(f"Model loaded, device: {model.device}\n")
    return tokenizer, model


def run_ocr(pdf_path: str, output_dir: str, model_dir: str,
            strip_page_split: bool = False):
    """对 PDF 执行 OCR 识别，输出单个 result.md 文件。"""
    if not os.path.isfile(pdf_path):
        print(f"Error: 文件不存在: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_dir = output_dir or f"./ocr_output_{pdf_name}"
    os.makedirs(output_dir, exist_ok=True)

    # 1. PDF 转图片
    print(f"Converting PDF: {pdf_path}")
    images, tmp_dir = pdf_to_images(pdf_path)
    print(f"  → {len(images)} pages converted\n")

    # 2. 加载模型
    tokenizer, model = load_model(model_dir)

    # 3. OCR 推理（save_results=True 会自动在 output_dir 生成 result.md）
    print("Running OCR...")
    model.infer_multi(
        tokenizer,
        prompt="<image>Multi page parsing.",
        image_files=images,
        output_path=output_dir,
        image_size=1024,
        max_length=32768,
        no_repeat_ngram_size=35,
        ngram_window=1024,
        save_results=True,
    )

    result_file = os.path.join(output_dir, "result.md")

    # 4. 可选：去掉 <PAGE> 分隔符，合成连续 markdown
    if strip_page_split and os.path.exists(result_file):
        with open(result_file, encoding="utf-8") as f:
            content = f.read()
        content = content.replace("<PAGE>", "")
        # 合并连续空行为单个空行
        content = re.sub(r"\n{3,}", "\n\n", content)
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(content)

    # 5. 清理临时图片
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n✅ Done! 输出文件: {result_file}")
    if not strip_page_split:
        print("   (页面之间包含 <PAGE> 分隔符，可用 --no-page-split 去掉)")


def main():
    parser = argparse.ArgumentParser(
        description="PDF → OCR → Markdown (Unlimited-OCR)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("pdf", help="PDF 文件路径")
    parser.add_argument(
        "--output_dir", "-o",
        default="",
        help="输出目录（默认 ./ocr_output_<pdf文件名>）",
    )
    parser.add_argument(
        "--model_dir", "-m",
        default="baidu/Unlimited-OCR",
        help="本地模型路径 或 HuggingFace 模型 ID",
    )
    parser.add_argument(
        "--no-page-split",
        action="store_true",
        help="去掉 <PAGE> 分隔符，合并为连续 markdown",
    )
    args = parser.parse_args()
    run_ocr(args.pdf, args.output_dir, args.model_dir,
            strip_page_split=args.no_page_split)


if __name__ == "__main__":
    main()
