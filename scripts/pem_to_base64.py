#!/usr/bin/env python3
"""Convert a PEM private key file to a single-line base64 string for use in environment variables."""

import base64
import sys


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-pem-file>")
        sys.exit(1)

    pem_path = sys.argv[1]

    with open(pem_path, "r") as f:
        pem_content = f.read().strip()

    if not pem_content.startswith("-----BEGIN"):
        print("Error: file does not look like a PEM key", file=sys.stderr)
        sys.exit(1)

    encoded = base64.b64encode(pem_content.encode("utf-8")).decode("utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
