"""End-to-end evaluation harness.

Runs the full pipeline over a ticket file and writes a metrics report.
Must accept --input and --output paths because the hidden evaluation set
is pointed at a file we've never seen.

TODO: implement in Week 2.
"""
import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run evaluation over a ticket set.")
    parser.add_argument("--input", required=True, help="Path to input tickets JSON")
    parser.add_argument("--output", required=True, help="Directory for results")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[harness] input:  {input_path}")
    print(f"[harness] output: {output_dir}")
    print("[harness] not yet implemented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
