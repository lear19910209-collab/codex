"""Take screenshots of the real Qt interface, using synthetic local product fixtures."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from organizer.core import DuplicateGroup, Options, create_output_folder, inspect_image, process_batch
from organizer.ui import DuplicatesDialog, MainWindow, ResultDialog, create_application
from scripts.make_assets import make_samples


def main():
    app = create_application()
    folder = ROOT / "test-artifacts" / "preview"
    paths = make_samples(folder / "图片")
    docs = ROOT / "docs"
    window = MainWindow(folder / "preview-settings.json")
    window.prefs.theme = "light"
    window.apply_theme()
    window.apply_options(Options(rename=True, prefix="女包", resize=True, output_format="JPEG"))
    for path in paths:
        window.add_entry(inspect_image(path))
    window.show()
    app.processEvents()
    window.grab().save(str(docs / "screenshot-home.png"))
    window.prefs.theme = "dark"
    window.apply_theme()
    app.processEvents()
    window.grab().save(str(docs / "screenshot-dark.png"))
    window.prefs.theme = "light"
    window.apply_theme()
    result = process_batch(window.entries, window.current_options(), create_output_folder(folder))
    dialog = ResultDialog(result, window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(docs / "screenshot-result.png"))
    dialog.close()
    duplicates = DuplicatesDialog([DuplicateGroup(paths[:3], False)], window.entries, window)
    duplicates.show()
    app.processEvents()
    duplicates.grab().save(str(docs / "screenshot-duplicates.png"))
    duplicates.close()
    window.close()
    print(f"真实桌面界面截图：{docs}")


if __name__ == "__main__":
    main()
