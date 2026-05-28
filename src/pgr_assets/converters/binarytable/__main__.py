import argparse
import io
import sys

from .table import BinaryTable


def main():
    parser = argparse.ArgumentParser(
        prog="python -m pgr_assets.converters.binarytable",
        description="Parse a raw .tab.bytes file and emit CSV using the latest (3.6+) parser settings.",
    )
    parser.add_argument("input", help="Path to a raw .tab.bytes file")
    parser.add_argument(
        "-o", "--output",
        help="Path to write CSV (defaults to stdout)",
        default=None,
    )
    args = parser.parse_args()

    with open(args.input, "rb") as f:
        data = f.read()

    table = BinaryTable(io.BytesIO(data), (99, 99))

    if args.output is None:
        table.to_csv(sys.stdout)
    else:
        with open(args.output, "w", newline="") as out:
            table.to_csv(out)


if __name__ == "__main__":
    main()
