"""Build a replaceable-library directory bundle; no one-file executable."""
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from organizer import APP_NAME, VERSION


def main():
    sources = ROOT / "build" / "open-source"
    if not (sources / "sources.json").exists():
        raise SystemExit("请先运行 python scripts/fetch_open_source.py，准备随包提供的开源源码和许可。")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_assets.py")], check=True, cwd=ROOT)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--name", APP_NAME, "--icon", str(ROOT / "assets" / "app.ico"),
               "--add-data", f"{ROOT / 'assets'}:assets", "--add-data", f"{ROOT / 'docs' / 'THIRD_PARTY.md'}:开源许可",
               "--add-data", f"{ROOT / 'build' / 'licenses'}:开源许可", "--add-data", f"{sources}:开源源码",
               "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
               "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
               "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtPdf",
               "--exclude-module", "PySide6.QtOpenGLWidgets", "--distpath", str(ROOT / "dist"),
               "--workpath", str(ROOT / "build" / "pyinstaller"), "--specpath", str(ROOT / "build"),
               str(ROOT / "main.py")]
    if sys.platform == "win32":
        command[command.index("--distpath"):command.index("--distpath")] = ["--version-file", str(ROOT / "packaging" / "version_info.txt")]
    subprocess.run(command, check=True, cwd=ROOT)
    bundle = ROOT / "dist" / APP_NAME
    notices = bundle / "_internal" / "开源许可"
    notices.mkdir(parents=True, exist_ok=True)
    for package in ("Pillow", "PyInstaller", "shiboken6", "PySide6-Essentials"):
        distribution = importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if Path(file).name.lower().startswith(("license", "copying", "notice")):
                target = notices / package / Path(file).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(file), target)
    for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if path.exists():
            shutil.copy2(path, notices / "Python-LICENSE.txt")
            break
    shutil.copy2(ROOT / "docs" / "买家使用说明.txt", bundle / "使用说明.txt")
    shutil.copy2(ROOT / "LICENSE", bundle / "软件许可.txt")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    shutil.make_archive(str(release / f"ProductImageOrganizer-{VERSION}-Portable"), "zip", ROOT / "dist", APP_NAME)
    print(f"便携包已生成：{release}")


if __name__ == "__main__":
    main()
