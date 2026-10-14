"""Download and run the Tailwind CSS standalone CLI (no Node.js needed).

Usage:
    python scripts/tailwind.py install   # download the pinned binary into bin/
    python scripts/tailwind.py build     # compile assets/css/input.css -> static/css/app.css
    python scripts/tailwind.py watch     # rebuild on every template change (development)

The binary is checked against the SHA256 published by the Tailwind release, so a
corrupted or tampered download is rejected. To upgrade Tailwind, change VERSION and
copy the new hashes from the release's sha256sums.txt.
"""

import hashlib
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION = "v4.3.3"
SHA256 = {
    "tailwindcss-linux-arm64": "55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195",
    "tailwindcss-linux-x64": "dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a",
    "tailwindcss-macos-arm64": "cdf646702987a743464dff4d9c60fd4480d1c1e73dd819a9a67f1078815dce9d",
    "tailwindcss-macos-x64": "7922e0953f2110c05976e3bf58f14e643d90427575e766b7d433f5f80cbee7e1",
    "tailwindcss-windows-x64.exe": "e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955",
}

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"
INPUT_CSS = ROOT / "assets" / "css" / "input.css"
OUTPUT_CSS = ROOT / "static" / "css" / "app.css"


def asset_name():
    system = platform.system()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "Windows":
        return "tailwindcss-windows-x64.exe"
    if system == "Darwin":
        return f"tailwindcss-macos-{arch}"
    if system == "Linux":
        return f"tailwindcss-linux-{arch}"
    sys.exit(f"Unsupported platform: {system} {machine}")


def binary_path():
    return BIN_DIR / asset_name()


def install():
    name = asset_name()
    target = BIN_DIR / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256[name]:
        print(f"Tailwind {VERSION} already installed at {target}")
        return
    url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{VERSION}/{name}"
    print(f"Downloading {url}")
    data = urllib.request.urlopen(url, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256[name]:
        sys.exit(f"Checksum mismatch for {name}: got {digest}, expected {SHA256[name]}")
    BIN_DIR.mkdir(exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o755)
    print(f"Installed Tailwind {VERSION} at {target}")


def run(*extra):
    if not binary_path().exists():
        install()
    cmd = [str(binary_path()), "-i", str(INPUT_CSS), "-o", str(OUTPUT_CSS), *extra]
    sys.exit(subprocess.call(cmd, cwd=ROOT))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "build"
    if command == "install":
        install()
    elif command == "build":
        run("--minify")
    elif command == "watch":
        run("--watch")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
