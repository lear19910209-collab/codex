import threading
import time
from dataclasses import asdict

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog

from organizer.core import DuplicateGroup, Options, create_output_folder, inspect_image, process_batch
from organizer.settings import Preferences, load_preferences, save_preferences
from organizer.ui import DuplicatesDialog, MainWindow, ResultDialog, SettingsDialog, Worker


def pump(app, predicate, timeout=30):
    start = time.monotonic()
    while not predicate():
        app.processEvents()
        if time.monotonic() - start > timeout:
            raise AssertionError("后台任务超时")
        time.sleep(0.001)
    app.processEvents()


def test_preferences_roundtrip_and_no_remember(tmp_path):
    path = tmp_path / "settings.json"
    prefs = Preferences(theme="dark", last_options=asdict(Options(rename=True)), last_output_parent="C:/Photos")
    save_preferences(path, prefs)
    assert load_preferences(path) == prefs
    prefs.remember = False
    save_preferences(path, prefs)
    loaded = load_preferences(path)
    assert loaded.last_options is None and loaded.last_output_parent == "" and loaded.theme == "dark"


def test_corrupt_preferences_reset(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"width": "oops", "remember": "false"}', "utf-8")
    assert load_preferences(path) == Preferences()
    path.write_text("bad JSON", "utf-8")
    assert load_preferences(path) == Preferences()


def test_ui_options_and_import(app, tmp_path, product):
    window = MainWindow(tmp_path / "settings.json")
    window.show()
    default = window.current_options()
    assert default == Options()
    options = Options(rename=True, prefix="女包", digits=4, resize=True, width=1000, height=700,
                      resize_mode="crop", quality="high", output_format="WEBP")
    window.apply_options(options)
    assert window.current_options() == options
    path = tmp_path / "中文 名称.png"
    product.save(path)
    window.import_paths([path, path])
    pump(app, lambda: window.worker is None)
    assert len(window.entries) == window.image_list.count() == 1
    assert "已添加 1" in window.stats.text()
    assert not window.empty_note.isVisible()
    window.remove_item(window.image_list.item(0))
    assert not window.entries
    window.close()


def test_500_batch_keeps_gui_event_loop_alive(app, tmp_path, product):
    path = tmp_path / "原图.jpg"
    product.save(path)
    # Same read-only input repeated exercises 500 real encodes and collision creation.
    entry = inspect_image(path)
    entries = [entry] * 500
    output = create_output_folder(tmp_path)
    worker = Worker(lambda w: process_batch(entries, Options(rename=True, resize=True, width=200, height=200), output, w.cancel, w.progress.emit))
    outcomes = []
    updates = []
    ticks = []
    worker.outcome.connect(outcomes.append)
    worker.progress.connect(lambda *args: updates.append(args))
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    worker.start()
    pump(app, lambda: not worker.isRunning(), timeout=90)
    timer.stop()
    assert outcomes[0][0] and outcomes[0][1].success == 500
    assert len(updates) == 500 and len(ticks) >= 10
    # Largest timer gap catches freezes, while allowing CI runners occasional scheduling delay.
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 2.0
    worker.wait()


def test_duplicate_confirmation_and_exclusion(app, tmp_path, product, monkeypatch):
    import organizer.ui as ui
    paths = [tmp_path / f"{i}.png" for i in range(3)]
    for path in paths:
        product.save(path)
    entries = [inspect_image(path) for path in paths]
    dialog = DuplicatesDialog([DuplicateGroup(paths, True)], entries, None)
    confirmations = []
    def accepted(*args):
        confirmations.append(args)
        return True
    monkeypatch.setattr(ui, "ask", accepted)
    dialog.keep_one()
    assert sum(item.checkState(0) == Qt.Checked for item, _ in dialog.items[0]) == 1
    dialog.apply()
    assert len(confirmations) == 2 and sum(entry.included for entry in entries) == 1
    assert all(path.exists() for path in paths)


def test_duplicate_cancel_does_not_change_selection(app, tmp_path, product, monkeypatch):
    import organizer.ui as ui
    paths = [tmp_path / f"{i}.png" for i in range(2)]
    for path in paths:
        product.save(path)
    entries = [inspect_image(path) for path in paths]
    dialog = DuplicatesDialog([DuplicateGroup(paths, True)], entries, None)
    monkeypatch.setattr(ui, "ask", lambda *args: False)
    dialog.keep_one()
    assert all(item.checkState(0) == Qt.Checked for item, _ in dialog.items[0])
    dialog.items[0][0][0].setCheckState(0, Qt.Unchecked)
    dialog.apply()
    assert all(entry.included for entry in entries) and dialog.result() != QDialog.Accepted


def test_settings_and_result_dialogs(app, tmp_path, product):
    parent = MainWindow(tmp_path / "settings.json")
    for theme in ("light", "dark", "system"):
        parent.prefs.theme = theme
        parent.apply_theme()
        settings = SettingsDialog(parent.prefs, parent)
        settings.show()
        app.processEvents()
        settings.close()
    path = tmp_path / "商品.png"
    product.save(path)
    result = process_batch([inspect_image(path)], Options(), create_output_folder(tmp_path))
    dialog = ResultDialog(result, parent)
    dialog.show()
    app.processEvents()
    assert dialog.isVisible()
    dialog.close()
    parent.close()
