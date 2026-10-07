from __future__ import annotations

import sys
import threading
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize, QStandardPaths, QUrl, QRect
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QStyle,
)

from . import APP_NAME, VERSION
from .core import (
    BatchResult, ImageEntry, Options, UserError, create_output_folder,
    detect_duplicates, friendly_error, process_batch, scan_paths,
)
from .settings import Preferences, load_preferences, save_preferences


def size_text(value: int) -> str:
    return f"{value / 1024 / 1024:.2f} MB" if value >= 1024 * 1024 else f"{value / 1024:.1f} KB"


def combo(items):
    widget = QComboBox()
    for text, data in items:
        widget.addItem(text, data)
    return widget


def select_combo(widget, value):
    index = widget.findData(value)
    widget.setCurrentIndex(max(0, index))


def button(text, callback, name=""):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


def ask(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Question)
    box.setText(message)
    confirm = box.addButton("确认", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() == confirm


def info(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.addButton("知道了", QMessageBox.AcceptRole)
    box.exec()


class Worker(QThread):
    entry = Signal(object)
    progress = Signal(int, int, str)
    outcome = Signal(object)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.task(self)
            self.outcome.emit((True, result))
        except Exception as exc:
            self.outcome.emit((False, friendly_error(exc)))


class DropZone(QFrame):
    files = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        title = QLabel("＋  拖入图片或文件夹")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel("支持 JPG / JPEG / PNG / WebP · 文件夹会包含子文件夹中的图片")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(hint)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files.emit(paths)
            event.acceptProposedAction()


class ThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        entry = index.data(Qt.UserRole)
        if entry is None:
            return
        painter.save()
        rect = option.rect.adjusted(3, 2, -3, -2)
        dark = option.palette.window().color().lightness() < 128
        if option.state & QStyle.State_Selected:
            painter.setBrush(QColor("#304868" if dark else "#e6efff"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
        pixmap = index.data(Qt.DecorationRole).pixmap(QSize(142, 102))
        painter.drawPixmap(rect.center().x() - pixmap.width() // 2, rect.top() + 7, pixmap)
        painter.setFont(option.font)
        text_color = QColor("#b54747") if entry.error else option.palette.text().color()
        painter.setPen(text_color)
        name = option.fontMetrics.elidedText(entry.path.name, Qt.ElideMiddle, rect.width() - 10)
        painter.drawText(QRect(rect.left()+5, rect.top()+112, rect.width()-10, 20), Qt.AlignCenter, name)
        detail = "无法读取" if entry.error else f"{entry.width} × {entry.height}"
        painter.drawText(QRect(rect.left()+5, rect.top()+132, rect.width()-10, 18), Qt.AlignCenter, detail)
        painter.setPen(QColor("#a5b2c6" if dark else "#6b7b91"))
        painter.setFont(QFont(option.font.family(), 9))
        painter.drawText(QRect(rect.left()+5, rect.top()+151, rect.width()-10, 18), Qt.AlignCenter,
                         size_text(entry.size) + (" · 不输出" if not entry.included else ""))
        painter.restore()
        rect = QRect(option.rect.right() - 25, option.rect.top() + 4, 20, 20)
        painter.save()
        painter.setPen(QColor("#8492a6"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(rect, Qt.AlignCenter, "×")
        painter.restore()


class ImageList(QListWidget):
    files = Signal(list)
    remove_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setIconSize(QSize(142, 102))
        self.setGridSize(QSize(180, 180))
        self.setSpacing(5)
        self.setWordWrap(False)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event):
        DropZone.dragEnterEvent(self, event)

    def dragMoveEvent(self, event):
        DropZone.dragEnterEvent(self, event)

    def dropEvent(self, event):
        DropZone.dropEvent(self, event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and event.button() == Qt.LeftButton:
            rect = self.visualItemRect(item)
            close = QRect(rect.right() - 25, rect.top() + 4, 20, 20)
            if close.contains(event.position().toPoint()):
                self.remove_requested.emit(item)
                return
        super().mouseReleaseEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, prefs, parent):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        title = QLabel("简单设置，按您的习惯来")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.format = combo([("保持原格式", "original"), ("JPG", "JPEG"), ("PNG", "PNG"), ("WebP", "WEBP")])
        select_combo(self.format, prefs.output_format)
        self.width, self.height = QSpinBox(), QSpinBox()
        for spin, value in ((self.width, prefs.width), (self.height, prefs.height)):
            spin.setRange(1, 10000)
            spin.setValue(value)
            spin.setSuffix(" 像素")
        self.quality = combo([("高质量", "high"), ("平衡（推荐）", "balanced"), ("更小体积", "small")])
        select_combo(self.quality, prefs.quality)
        self.theme = combo([("跟随系统", "system"), ("浅色", "light"), ("深色", "dark")])
        select_combo(self.theme, prefs.theme)
        self.remember = QCheckBox("记住上一次整理设置和输出位置")
        self.remember.setChecked(prefs.remember)
        form.addRow("默认输出格式", self.format)
        form.addRow("默认宽度", self.width)
        form.addRow("默认高度", self.height)
        form.addRow("默认压缩质量", self.quality)
        form.addRow("主题", self.theme)
        layout.addLayout(form)
        layout.addWidget(self.remember)
        hint = QLabel("保存后立即使用以上默认值。图片和文件列表不会被记录。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        buttons = QDialogButtonBox()
        buttons.addButton("保存", QDialogButtonBox.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            Options(resize=True, width=self.width.value(), height=self.height.value()).validate()
        except UserError as exc:
            info(self, "请检查尺寸", str(exc))
            return
        super().accept()


class DuplicatesDialog(QDialog):
    def __init__(self, groups, entries, parent):
        super().__init__(parent)
        self.setWindowTitle("检查重复 / 相似图片")
        self.resize(760, 560)
        self.items = []
        self.groups = groups
        lookup = {entry.path: entry for entry in entries}
        layout = QVBoxLayout(self)
        label = QLabel(f"发现 {len(groups)} 组重复 / 相似图片")
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        hint = QLabel("勾选需要输出的图片。疑似相似可能判断有误，请对照缩略图确认。\n取消勾选只影响本次输出，原始文件始终保留。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["输出 / 图片名称", "尺寸", "大小"])
        self.tree.setIconSize(QSize(90, 66))
        self.tree.setColumnWidth(0, 460)
        self.tree.setColumnWidth(1, 130)
        for number, group in enumerate(groups, 1):
            top = QTreeWidgetItem(self.tree, [f"第 {number} 组 · {'完全相同' if group.exact else '疑似相似'} · {len(group.paths)} 张"])
            children = []
            for path in group.paths:
                entry = lookup[path]
                item = QTreeWidgetItem(top, [path.name, f"{entry.width} × {entry.height}", size_text(entry.size)])
                item.setCheckState(0, Qt.Checked if entry.included else Qt.Unchecked)
                pixmap = QPixmap()
                pixmap.loadFromData(entry.thumbnail)
                item.setIcon(0, QIcon(pixmap))
                item.setToolTip(0, str(path))
                children.append((item, entry))
            top.setExpanded(True)
            self.items.append(children)
        layout.addWidget(self.tree)
        layout.addWidget(button("每组保留其中一张", self.keep_one))
        buttons = QDialogButtonBox()
        buttons.addButton("应用输出选择", QDialogButtonBox.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def keep_one(self):
        if not ask(self, "确认每组保留一张", "将每组只勾选分辨率最高的一张，其他图片不进入输出文件夹。\n请检查疑似相似组。原始文件不会被修改或删除。"):
            return
        for children in self.items:
            best = max(children, key=lambda pair: (pair[1].width * pair[1].height, pair[1].size))
            for item, entry in children:
                item.setCheckState(0, Qt.Checked if item is best[0] else Qt.Unchecked)

    def apply(self):
        excluded = sum(item.checkState(0) != Qt.Checked for children in self.items for item, _ in children)
        if excluded and not ask(self, "确认不输出所选图片", f"有 {excluded} 张图片不会进入最终输出文件夹。\n原始文件仍会保留。是否应用？"):
            return
        for children in self.items:
            for item, entry in children:
                entry.included = item.checkState(0) == Qt.Checked
        self.accept()


class ResultDialog(QDialog):
    def __init__(self, result: BatchResult, parent):
        super().__init__(parent)
        self.setWindowTitle("整理结果")
        self.resize(520, 490 if result.failures else 390)
        layout = QVBoxLayout(self)
        heading = "整理已取消" if result.cancelled else ("整理完成，部分图片未能处理" if result.failures else "✓  整理完成")
        title = QLabel(heading)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"共选择：{result.total} 张    成功：{result.success} 张    失败：{len(result.failures)} 张"))
        if result.cancelled:
            layout.addWidget(QLabel(f"未处理：{result.total - result.attempted} 张 · 已完成结果仍然保留"))
        form = QFormLayout()
        form.addRow("原始大小", QLabel(size_text(result.input_bytes)))
        form.addRow("整理后", QLabel(size_text(result.output_bytes)))
        if result.saved_bytes >= 0:
            form.addRow("节省", QLabel(f"{size_text(result.saved_bytes)}（{result.saved_percent:.1f}%）"))
        else:
            form.addRow("大小变化", QLabel(f"增加 {size_text(-result.saved_bytes)}（尺寸或格式变化可能增大文件）"))
        layout.addLayout(form)
        note = QLabel("大小统计仅比较成功处理的图片。原图安全保留。")
        note.setObjectName("muted")
        layout.addWidget(note)
        path = QLabel(result.output_dir)
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path)
        if result.failures:
            errors = QListWidget()
            for failure in result.failures:
                errors.addItem(f"{failure.name}：{failure.reason}")
                errors.item(errors.count() - 1).setToolTip(failure.reason)
            errors.setWordWrap(True)
            layout.addWidget(errors)
        if result.report_error:
            label = QLabel(f"整理报告未能保存：{result.report_error}")
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addWidget(button("打开输出文件夹", lambda: open_folder(self, result.output_dir), "primary"))
        layout.addWidget(button("完成", self.accept))


def open_folder(parent, path):
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        info(parent, "无法打开文件夹", f"请在文件资源管理器中打开：\n{path}")


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 780)
        self.setMinimumSize(1000, 650)
        self.settings_path = settings_path or Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)) / "preferences.json"
        self.prefs = load_preferences(self.settings_path)
        self.entries: list[ImageEntry] = []
        self.worker: Worker | None = None
        self.pending_outcome = None
        self.job_kind = ""
        self.last_result: BatchResult | None = None
        self._build()
        options = Options(width=self.prefs.width, height=self.prefs.height,
                          quality=self.prefs.quality, output_format=self.prefs.output_format)
        if self.prefs.remember and self.prefs.last_options:
            try:
                remembered = Options(**self.prefs.last_options)
                remembered.validate()
                options = remembered
            except (TypeError, ValueError, UserError):
                pass
        self.apply_options(options)
        self.apply_theme()
        QApplication.instance().styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 14)
        layout.setSpacing(12)
        header = QHBoxLayout()
        logo = QLabel("▧")
        logo.setObjectName("logo")
        header.addWidget(logo)
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("appTitle")
        subtitle = QLabel("一次拖进去，一键整理完")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.settings_button = button("设置", self.show_settings)
        header.addWidget(self.settings_button)
        header.addWidget(button("关于", self.about))
        layout.addLayout(header)
        self.body = QWidget()
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        left = QVBoxLayout()
        self.drop_zone = DropZone()
        self.drop_zone.files.connect(self.import_paths)
        left.addWidget(self.drop_zone)
        add_row = QHBoxLayout()
        add_row.addWidget(button("添加图片", self.pick_images))
        add_row.addWidget(button("添加文件夹", self.pick_folder))
        add_row.addStretch()
        self.duplicate_button = button("检测重复图片", self.check_duplicates)
        add_row.addWidget(self.duplicate_button)
        left.addLayout(add_row)
        self.similar_check = QCheckBox("同时检测视觉上高度相似的图片（结果需人工确认）")
        self.similar_check.setChecked(True)
        left.addWidget(self.similar_check)
        stats_row = QHBoxLayout()
        self.stats = QLabel("已添加 0 张图片 · 总大小 0 MB")
        self.stats.setObjectName("sectionTitle")
        stats_row.addWidget(self.stats)
        stats_row.addStretch()
        stats_row.addWidget(button("移除选中", self.remove_selected))
        stats_row.addWidget(button("清空", self.clear_all))
        left.addLayout(stats_row)
        self.image_list = ImageList()
        self.image_list.files.connect(self.import_paths)
        self.image_list.remove_requested.connect(self.remove_item)
        self.image_list.itemDoubleClicked.connect(self.inspect_item)
        self.image_list.setObjectName("imageList")
        left.addWidget(self.image_list, 1)
        self.empty_note = QLabel("还没有图片，点击「添加图片」或拖入文件夹即可开始。")
        self.empty_note.setObjectName("muted")
        self.empty_note.setAlignment(Qt.AlignCenter)
        left.addWidget(self.empty_note)
        self.selection_note = QLabel("点击图片右上角 × 可移除 · 双击查看完整名称和信息")
        self.selection_note.setObjectName("muted")
        left.addWidget(self.selection_note)
        body_layout.addLayout(left, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(340)
        scroll.setFrameShape(QFrame.NoFrame)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(2, 0, 6, 0)
        panel_layout.setSpacing(8)
        panel_title = QLabel("整理方式")
        panel_title.setObjectName("sectionTitle")
        panel_layout.addWidget(panel_title)
        self.rename_group = QGroupBox("批量重命名")
        self.rename_group.setCheckable(True)
        rename_layout = QVBoxLayout(self.rename_group)
        self.prefix = QLineEdit("商品")
        self.prefix.setPlaceholderText("输入商品名称，例如：女包")
        self.prefix.setMaxLength(80)
        rename_layout.addWidget(self.prefix)
        row = QHBoxLayout()
        row.addWidget(QLabel("编号方式"))
        self.digits = combo([("001（3 位）", 3), ("0001（4 位）", 4)])
        row.addWidget(self.digits)
        rename_layout.addLayout(row)
        self.name_preview = QLabel("预览：商品_001.jpg")
        self.name_preview.setObjectName("muted")
        rename_layout.addWidget(self.name_preview)
        self.prefix.textChanged.connect(self.update_preview)
        self.digits.currentIndexChanged.connect(self.update_preview)
        panel_layout.addWidget(self.rename_group)
        self.resize_group = QGroupBox("统一尺寸")
        self.resize_group.setCheckable(True)
        resize_layout = QVBoxLayout(self.resize_group)
        self.preset = combo([("800 × 800", 800), ("1080 × 1080", 1080), ("1200 × 1200", 1200), ("自定义尺寸", 0)])
        resize_layout.addWidget(self.preset)
        dimensions = QHBoxLayout()
        self.width, self.height = QSpinBox(), QSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(1, 10000)
            spin.setValue(800)
            spin.setSuffix(" px")
            dimensions.addWidget(spin)
            if spin is self.width:
                dimensions.addWidget(QLabel("×"))
        resize_layout.addLayout(dimensions)
        self.preset.currentIndexChanged.connect(self.preset_changed)
        self.resize_mode = combo([("完整显示 · 白底补齐（推荐）", "pad"), ("填满画面 · 居中裁切", "crop")])
        resize_layout.addWidget(self.resize_mode)
        note = QLabel("始终保持比例，图片不会被拉伸变形。")
        note.setObjectName("muted")
        resize_layout.addWidget(note)
        panel_layout.addWidget(self.resize_group)
        self.compress_group = QGroupBox("压缩图片")
        self.compress_group.setCheckable(True)
        compress_layout = QVBoxLayout(self.compress_group)
        self.quality = combo([("高质量 · 更多细节", "high"), ("平衡 · 推荐", "balanced"), ("更小体积", "small")])
        compress_layout.addWidget(self.quality)
        note = QLabel("PNG 无损压缩；实际节省取决于原图。")
        note.setObjectName("muted")
        compress_layout.addWidget(note)
        panel_layout.addWidget(self.compress_group)
        self.format_group = QGroupBox("转换格式")
        self.format_group.setCheckable(True)
        format_layout = QVBoxLayout(self.format_group)
        self.output_format = combo([("保持原格式", "original"), ("JPG", "JPEG"), ("PNG", "PNG"), ("WebP", "WEBP")])
        self.output_format.currentIndexChanged.connect(self.update_preview)
        format_layout.addWidget(self.output_format)
        note = QLabel("透明图片转 JPG 时，自动补白色背景。")
        note.setObjectName("muted")
        format_layout.addWidget(note)
        panel_layout.addWidget(self.format_group)
        panel_layout.addStretch()
        scroll.setWidget(panel)
        body_layout.addWidget(scroll)
        layout.addWidget(self.body, 1)
        self.progress_label = QLabel("准备就绪 · 原图始终保留，结果保存到新文件夹")
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        action_row = QHBoxLayout()
        privacy = QLabel("所有图片均在您的电脑本地处理，不会上传到服务器。")
        privacy.setObjectName("muted")
        action_row.addWidget(privacy)
        action_row.addStretch()
        self.open_button = button("打开输出文件夹", self.open_last_output)
        self.open_button.setVisible(False)
        action_row.addWidget(self.open_button)
        self.cancel_button = button("取消处理", self.cancel_work)
        self.cancel_button.setVisible(False)
        action_row.addWidget(self.cancel_button)
        self.start_button = button("开始整理", self.start_processing, "primary")
        self.start_button.setFixedSize(200, 48)
        action_row.addWidget(self.start_button)
        layout.addLayout(action_row)

    def update_preview(self, *_):
        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "original": "jpg"}.get(self.output_format.currentData(), "jpg") if hasattr(self, "output_format") else "jpg"
        digits = self.digits.currentData() or 3
        self.name_preview.setText(f"预览：{self.prefix.text() or '商品'}_{1:0{digits}d}.{extension}")

    def preset_changed(self, *_):
        value = self.preset.currentData()
        if value:
            self.width.setValue(value)
            self.height.setValue(value)
        self.width.setEnabled(not value)
        self.height.setEnabled(not value)

    def current_options(self):
        return Options(rename=self.rename_group.isChecked(), prefix=self.prefix.text(), digits=self.digits.currentData(),
                       resize=self.resize_group.isChecked(), width=self.width.value(), height=self.height.value(),
                       resize_mode=self.resize_mode.currentData(), compress=self.compress_group.isChecked(),
                       quality=self.quality.currentData(), output_format=self.output_format.currentData() if self.format_group.isChecked() else "original")

    def apply_options(self, options):
        self.rename_group.setChecked(options.rename)
        self.prefix.setText(options.prefix)
        select_combo(self.digits, options.digits)
        self.resize_group.setChecked(options.resize)
        self.width.setValue(options.width)
        self.height.setValue(options.height)
        select_combo(self.preset, options.width if options.width == options.height and options.width in (800, 1080, 1200) else 0)
        self.preset_changed()
        select_combo(self.resize_mode, options.resize_mode)
        self.compress_group.setChecked(options.compress)
        select_combo(self.quality, options.quality)
        select_combo(self.output_format, options.output_format)
        self.format_group.setChecked(options.output_format != "original")
        self.update_preview()

    def apply_theme(self):
        dark = self.prefs.theme == "dark" or (self.prefs.theme == "system" and QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark)
        bg, card, text, muted, line = ("#141b27", "#202a3b", "#edf2fa", "#a5b2c6", "#354259") if dark else ("#f6f8fc", "#ffffff", "#22324c", "#6b7b91", "#dce3ed")
        QApplication.instance().setStyleSheet(f"""
            QWidget {{ color: {text}; font-family: 'Microsoft YaHei UI', 'Noto Sans CJK SC', 'Segoe UI'; font-size: 13px; }}
            QMainWindow, QDialog {{ background: {bg}; }}
            QLabel {{ background: transparent; }}
            QLabel#appTitle {{ font-size: 23px; font-weight: 700; }}
            QLabel#sectionTitle {{ font-size: 14px; font-weight: 600; }}
            QLabel#muted {{ color: {muted}; font-size: 12px; }}
            QLabel#logo {{ color: #3977ee; font-size: 38px; padding-right: 6px; }}
            QFrame#dropZone {{ background: {card}; border: 2px dashed #9cb8e5; border-radius: 12px; }}
            QLabel#dropTitle {{ font-size: 20px; font-weight: 600; color: #5790ed; }}
            QPushButton {{ background: {card}; border: 1px solid {line}; border-radius: 7px; padding: 8px 13px; }}
            QPushButton:hover {{ border-color: #5790ed; color: #5790ed; }}
            QPushButton:disabled {{ color: {muted}; }}
            QPushButton#primary {{ background: #3977ee; color: white; border: none; font-size: 16px; font-weight: 600; }}
            QPushButton#primary:hover {{ background: #2864d7; }}
            QPushButton#primary:disabled {{ background: #7899d2; }}
            QGroupBox {{ background: {card}; border: 1px solid {line}; border-radius: 10px; margin-top: 9px; padding: 7px 8px 6px; font-weight: 600; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; }}
            QLineEdit, QSpinBox, QComboBox {{ background: {card}; border: 1px solid {line}; border-radius: 5px; padding: 6px; min-height: 19px; selection-background-color: #3977ee; }}
            QComboBox QAbstractItemView {{ background: {card}; selection-background-color: #3977ee; }}
            QCheckBox {{ spacing: 7px; }}
            QCheckBox::indicator, QGroupBox::indicator {{ width: 16px; height: 16px; }}
            QListWidget, QTreeWidget {{ background: {card}; border: 1px solid {line}; border-radius: 10px; padding: 5px; outline: 0; }}
            QListWidget::item {{ border-radius: 8px; padding: 5px; }}
            QListWidget::item:selected {{ background: {'#304868' if dark else '#e6efff'}; color: {text}; }}
            QTreeWidget::item:selected {{ background: #3977ee; color: white; }}
            QHeaderView::section {{ background: {card}; border: none; padding: 8px; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: {bg}; }}
            QProgressBar {{ background: {line}; border: none; border-radius: 5px; }}
            QProgressBar::chunk {{ background: #3977ee; border-radius: 5px; }}
            QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {line}; border-radius: 5px; min-height: 25px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QToolTip {{ background: {card}; color: {text}; border: 1px solid {line}; padding: 5px; }}
        """)

    def pick_images(self):
        names, _ = QFileDialog.getOpenFileNames(self, "选择商品图片", "", "图片 (*.jpg *.jpeg *.png *.webp *.JPG *.JPEG *.PNG *.WEBP)")
        if names:
            self.import_paths([Path(name) for name in names])

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if path:
            self.import_paths([Path(path)])

    def import_paths(self, paths):
        if self.worker:
            return
        self.run_worker("import", lambda worker: scan_paths(paths, worker.cancel, worker.entry.emit, worker.progress.emit))

    def add_entry(self, entry):
        if any(old.path == entry.path for old in self.entries):
            return
        self.entries.append(entry)
        item = QListWidgetItem()
        item.setSizeHint(QSize(174, 176))
        item.setData(Qt.UserRole, entry)
        self.image_list.addItem(item)
        self.update_item(item)
        self.refresh_stats()

    def update_item(self, item):
        entry = item.data(Qt.UserRole)
        pixmap = QPixmap()
        if entry.thumbnail:
            pixmap.loadFromData(entry.thumbnail)
        else:
            pixmap = QPixmap(142, 102)
            pixmap.fill(QColor("#f5e7e7"))
            painter = QPainter(pixmap)
            painter.setPen(QColor("#b54747"))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "图片无法读取")
            painter.end()
        item.setIcon(QIcon(pixmap))
        name = entry.path.name
        short = name[:15] + "…" if len(name) > 16 else name
        state = " · 不输出" if not entry.included else ""
        detail = "无法读取" if entry.error else f"{entry.width} × {entry.height}"
        item.setText(f"{short}\n{detail}\n{size_text(entry.size)}{state}")
        item.setToolTip(f"{entry.path}\n{detail} · {size_text(entry.size)}\n{entry.error or '原图安全保留'}{state}")
        item.setForeground(QColor("#b54747") if entry.error else QApplication.palette().text())

    def refresh_stats(self):
        count = len(self.entries)
        excluded = sum(not entry.included for entry in self.entries)
        self.stats.setText(f"已添加 {count} 张 · {size_text(sum(entry.size for entry in self.entries))}" + (f" · {excluded} 张不输出" if excluded else ""))
        self.empty_note.setVisible(not count)

    def remove_item(self, item):
        if self.worker:
            return
        entry = item.data(Qt.UserRole)
        self.entries.remove(entry)
        self.image_list.takeItem(self.image_list.row(item))
        self.refresh_stats()

    def remove_selected(self):
        for item in self.image_list.selectedItems():
            self.remove_item(item)

    def clear_all(self):
        if self.entries and ask(self, "清空图片列表", "清空软件中的图片列表？原始文件仍然保留。"):
            self.entries.clear()
            self.image_list.clear()
            self.refresh_stats()

    def inspect_item(self, item):
        entry = item.data(Qt.UserRole)
        info(self, "图片信息", f"{entry.path.name}\n\n尺寸：{entry.width} × {entry.height}\n大小：{size_text(entry.size)}\n路径：{entry.path}\n\n{entry.error or '原图安全保留。'}")

    def run_worker(self, kind, task):
        if self.worker:
            return
        self.job_kind = kind
        self.pending_outcome = None
        self.worker = Worker(task, self)
        self.worker.entry.connect(self.add_entry)
        self.worker.progress.connect(self.on_progress)
        self.worker.outcome.connect(self.store_outcome)
        self.worker.finished.connect(self.worker_finished)
        self.body.setEnabled(False)
        self.start_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("取消处理")
        self.cancel_button.setVisible(True)
        self.open_button.setVisible(False)
        self.progress_label.setText({"import": "正在读取图片…", "duplicates": "正在检测重复 / 相似图片…", "process": "正在准备整理…"}[kind])
        self.progress_bar.setRange(0, 0)
        self.worker.start()

    def store_outcome(self, value):
        self.pending_outcome = value

    def on_progress(self, done, total, name):
        verb = {"import": "已读取", "duplicates": "正在检测", "process": "正在处理"}[self.job_kind]
        if total:
            percent = int(done / total * 100)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)
            self.progress_label.setText(f"{verb} {done} / {total} · {percent}% · {name}")
        else:
            self.progress_label.setText(f"{verb} {done} 张图片 · {name}")

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("正在取消…")
            self.progress_label.setText("正在取消，请等待当前图片处理完毕。已完成结果会保留。")

    def worker_finished(self):
        cancelled = self.worker.cancel.is_set()
        self.worker.deleteLater()
        self.worker = None
        self.body.setEnabled(True)
        self.start_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0 if cancelled else 100)
        self.progress_label.setText("操作已取消 · 原图安全保留" if cancelled else "准备就绪 · 原图安全保留")
        success, payload = self.pending_outcome or (False, "操作未完成，请重试。")
        if not success:
            info(self, "操作未完成", payload)
        elif self.job_kind == "import":
            self.refresh_stats()
            if payload:
                info(self, "部分项目未能添加", "\n".join(payload[:10]) + (f"\n另有 {len(payload)-10} 个项目未添加。" if len(payload) > 10 else ""))
        elif self.job_kind == "duplicates":
            groups, failures = payload
            if cancelled:
                return
            if groups:
                DuplicatesDialog(groups, self.entries, self).exec()
                for i in range(self.image_list.count()):
                    self.update_item(self.image_list.item(i))
                self.refresh_stats()
            else:
                info(self, "检测完成", "未发现重复 / 高度相似图片。")
            if failures:
                info(self, "部分图片未能检测", "\n".join(f"{failure.name}：{failure.reason}" for failure in failures[:10]))
        else:
            self.last_result = payload
            self.open_button.setVisible(True)
            self.progress_label.setText(f"{'整理已取消' if payload.cancelled else '整理完成'} · 成功 {payload.success} 张 · 失败 {len(payload.failures)} 张 · 原图安全保留")
            ResultDialog(payload, self).exec()

    def check_duplicates(self):
        if len(self.entries) < 2:
            info(self, "先添加图片", "请至少添加两张图片，再检测重复。")
            return
        entries = list(self.entries)
        include_similar = self.similar_check.isChecked()
        self.run_worker("duplicates", lambda worker: detect_duplicates(entries, include_similar, worker.cancel, worker.progress.emit))

    def start_processing(self):
        if not any(entry.included for entry in self.entries):
            info(self, "先添加图片", "请添加图片，并至少保留一张需要输出的图片。")
            return
        options = self.current_options()
        try:
            options.validate()
        except UserError as exc:
            info(self, "请检查整理设置", str(exc))
            return
        parent = QFileDialog.getExistingDirectory(self, "选择保存位置（软件会自动创建新的结果文件夹）", self.prefs.last_output_parent)
        if not parent:
            return
        try:
            output = create_output_folder(Path(parent))
        except UserError as exc:
            info(self, "无法创建输出文件夹", str(exc))
            return
        self.prefs.last_options = asdict(options)
        self.prefs.last_output_parent = parent
        self.persist_settings()
        entries = list(self.entries)
        self.run_worker("process", lambda worker: process_batch(entries, options, output, worker.cancel, worker.progress.emit))

    def persist_settings(self):
        try:
            save_preferences(self.settings_path, self.prefs)
        except OSError:
            self.progress_label.setText("设置未能记住，本次整理仍可继续。")

    def show_settings(self):
        dialog = SettingsDialog(self.prefs, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.prefs.output_format = dialog.format.currentData()
        self.prefs.width, self.prefs.height = dialog.width.value(), dialog.height.value()
        self.prefs.quality = dialog.quality.currentData()
        self.prefs.theme = dialog.theme.currentData()
        self.prefs.remember = dialog.remember.isChecked()
        options = self.current_options()
        options.output_format = self.prefs.output_format
        options.width, options.height = self.prefs.width, self.prefs.height
        options.quality = self.prefs.quality
        self.apply_options(options)
        self.prefs.last_options = asdict(options) if self.prefs.remember else None
        self.persist_settings()
        self.apply_theme()

    def open_last_output(self):
        if self.last_result:
            open_folder(self, self.last_result.output_dir)

    def about(self):
        info(self, "关于", f"{APP_NAME}  {VERSION}\n\n批量重命名 · 尺寸整理 · 压缩 · 转换 · 重复检测\n\n所有图片均在您的电脑本地处理，不会上传到服务器。\n无需登录，无需联网。原图始终安全保留。\n\n开源依赖：PySide6 / Qt（LGPLv3），Pillow。\n完整许可文件随软件放在「开源许可」文件夹。")

    def closeEvent(self, event):
        if self.worker:
            info(self, "正在处理图片", "请先点击「取消处理」，等待当前图片处理完毕后再关闭软件。")
            event.ignore()
            return
        self.prefs.last_options = asdict(self.current_options())
        self.persist_settings()
        event.accept()


def create_application():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ProductImageOrganizer")
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("LocalImageTools")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC", 10))
    return app
