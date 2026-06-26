"""Allow `python -m ocr_client` as an alternative to the `ocr-client` console script."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
