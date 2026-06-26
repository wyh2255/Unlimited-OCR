"""CLI for SGLang batch inference. Wraps `sglang.batch.run_inference`."""

import argparse

from .batch import run, run_inference, start_server, stop_server


def parse_args():
    parser = argparse.ArgumentParser(
        description="SGLang concurrent inference for image datasets or PDF pages.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--image_dir", default="", help="Directory of images for dataset concurrency mode")
    parser.add_argument("--pdf", default="", help="PDF file; each page is converted and sent as one concurrent request")
    parser.add_argument("--output_dir", default="./outputs")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--model_dir", default="baidu/Unlimited-OCR")
    parser.add_argument("--image_mode", choices=("gundam", "base"), default="gundam")
    parser.add_argument("--server_log", default="./log/sglang_server.log")
    return parser.parse_args()


def main():
    args = parse_args()
    server_process = start_server(args)
    try:
        run(args)
    finally:
        stop_server(server_process)


if __name__ == "__main__":
    main()
