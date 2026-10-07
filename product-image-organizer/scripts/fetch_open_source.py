"""Build-time only: ship exact upstream Qt/PySide sources and their notices.

This script is never imported by the installed application. HTTPS is used only
by the developer/build service, never for processing user images.
"""
import hashlib
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "qtbase": "https://github.com/qt/qtbase/archive/refs/tags/v6.8.3.tar.gz",
    "qtsvg": "https://github.com/qt/qtsvg/archive/refs/tags/v6.8.3.tar.gz",
    "qtimageformats": "https://github.com/qt/qtimageformats/archive/refs/tags/v6.8.3.tar.gz",
    "pyside-setup": "https://github.com/qtproject/pyside-pyside-setup/archive/refs/tags/v6.8.3.tar.gz",
}


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    folder = ROOT / "build" / "open-source"
    licenses = ROOT / "build" / "licenses"
    folder.mkdir(parents=True, exist_ok=True)
    licenses.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, url in SOURCES.items():
        destination = folder / f"{name}-6.8.3.tar.gz"
        if not destination.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "ProductImageOrganizer-build/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response, destination.with_suffix(".tmp").open("wb") as out:
                while data := response.read(1024 * 1024):
                    out.write(data)
            destination.with_suffix(".tmp").replace(destination)
        with tarfile.open(destination, "r:gz") as archive:
            for member in archive:
                base = Path(member.name).name.lower()
                if not member.isfile() or not (base.startswith(("license", "copying", "notice")) or base == "qt_attribution.json"):
                    continue
                parts = Path(member.name).parts[1:]
                if ".." in parts or not parts:
                    continue
                output = licenses / name / Path(*parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    output.write_bytes(source.read())
        manifest[name] = {"version": "6.8.3", "url": url, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
        print(f"准备开源源码：{name} ({destination.stat().st_size // 1024 // 1024} MB)")
    (folder / "sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
