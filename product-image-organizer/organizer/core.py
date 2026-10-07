"""Offline image operations. Source files are only ever opened for reading."""
from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import shutil
import threading
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MAX_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
Progress = Callable[[int, int, str], None]


class UserError(Exception):
    """A message safe to present to a nontechnical user."""


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, UserError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "没有权限读取图片或写入文件夹，请选择您有权限的文件夹。"
    if isinstance(exc, FileNotFoundError):
        return "找不到文件，图片可能已被移动或移除。"
    if isinstance(exc, (Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError)):
        return "图片分辨率过大，当前版本支持最多 8000 万像素，请先缩小图片。"
    if isinstance(exc, UnidentifiedImageError):
        return "图片已损坏，或实际格式不是 JPG、PNG、WebP。"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112:
            return "磁盘空间不足，请清理磁盘或选择其他输出位置。"
        if exc.errno in (errno.EACCES, errno.EROFS) or getattr(exc, "winerror", None) == 5:
            return "没有权限写入该文件夹，请选择其他输出位置。"
        return "无法读取图片或保存结果，文件可能损坏、被占用，或文件路径过长。"
    return "处理未完成，请重试或换一张图片。原图不会被修改。"


@dataclass
class ImageEntry:
    path: Path
    size: int = 0
    width: int = 0
    height: int = 0
    format: str = ""
    thumbnail: bytes = b""
    error: str = ""
    included: bool = True


@dataclass
class Options:
    rename: bool = False
    prefix: str = "商品"
    digits: int = 3
    resize: bool = False
    width: int = 800
    height: int = 800
    resize_mode: str = "pad"
    compress: bool = True
    quality: str = "balanced"
    output_format: str = "original"

    def validate(self):
        if self.rename:
            validate_prefix(self.prefix)
        if self.digits not in (3, 4):
            raise UserError("请选择 001 或 0001 编号方式。")
        if self.resize and (not 1 <= self.width <= 10000 or not 1 <= self.height <= 10000
                            or self.width * self.height > MAX_PIXELS):
            raise UserError("宽高需在 1～10000 之间，总像素不能超过 8000 万。")
        if self.resize_mode not in ("pad", "crop"):
            raise UserError("请选择完整显示或居中裁切。")
        if self.quality not in ("high", "balanced", "small"):
            raise UserError("请选择有效的压缩质量。")
        if self.output_format not in ("original", *FORMATS):
            raise UserError("请选择 JPG、PNG、WebP 或保持原格式。")


def validate_prefix(prefix: str):
    if not prefix.strip() or prefix != prefix.strip() or len(prefix) > 80:
        raise UserError("名称请填写 1～80 个字符，首尾不要留空格。")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', prefix) or prefix.endswith("."):
        raise UserError('名称不能包含以下字符：< > : " / \\ | ? *，也不能以句点结尾。')
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", prefix, re.I):
        raise UserError("这个名称是 Windows 保留名称，请换一个名称。")


def read_image(path: Path) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.format not in FORMATS:
                raise UserError("实际图片格式不支持，请添加 JPG、PNG 或 WebP。")
            if source.width * source.height > MAX_PIXELS:
                raise UserError("图片分辨率过大，当前版本支持最多 8000 万像素。")
            if getattr(source, "n_frames", 1) > 1:
                raise UserError("暂不支持动态或多帧图片，请使用静态图片。")
            source.load()  # Validate complete decoding, including truncated files.
            image = ImageOps.exif_transpose(source)
            image.format = source.format
            return image


def inspect_image(path: Path) -> ImageEntry:
    entry = ImageEntry(path=path)
    try:
        entry.size = path.stat().st_size
        with read_image(path) as image:
            entry.width, entry.height = image.size
            entry.format = image.format or ""
            thumb = image.convert("RGBA")
            thumb.thumbnail((160, 120), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            thumb.save(buf, "PNG")
            entry.thumbnail = buf.getvalue()
    except Exception as exc:
        entry.error = friendly_error(exc)
    return entry


def scan_paths(paths: Iterable[Path], cancel: threading.Event,
               on_entry: Callable[[ImageEntry], None],
               progress: Progress | None = None) -> list[str]:
    """Walk without following directory symlinks; deterministic, cancellable import."""
    seen: set[Path] = set()
    errors = []
    count = 0

    def accept(path: Path):
        nonlocal count
        if cancel.is_set() or path.suffix.lower() not in EXTENSIONS:
            return
        try:
            real = path.resolve(strict=True)
            if real in seen:
                return
            seen.add(real)
            on_entry(inspect_image(real))
            count += 1
            if progress:
                progress(count, 0, path.name)
        except Exception as exc:
            errors.append(f"{path.name}：{friendly_error(exc)}")

    def walk_error(exc):
        errors.append(f"部分文件夹无法读取：{friendly_error(exc)}")

    for raw in paths:
        if cancel.is_set():
            break
        path = Path(raw)
        if path.is_dir():
            for root, directories, names in os.walk(path, followlinks=False, onerror=walk_error):
                if cancel.is_set():
                    break
                directories[:] = sorted(d for d in directories if not Path(root, d).is_symlink())
                for name in sorted(names, key=str.casefold):
                    if cancel.is_set():
                        break
                    accept(Path(root, name))
        elif path.suffix.lower() in EXTENSIONS:
            accept(path)
        else:
            errors.append(f"{path.name}：只支持 JPG、PNG 和 WebP 图片。")
    return errors


def flatten_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    white.alpha_composite(rgba)
    return white.convert("RGB")


def transform(image: Image.Image, options: Options, fmt: str) -> Image.Image:
    profile = None
    if image.info.get("icc_profile"):
        try:
            target_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(image.info["icc_profile"])),
                                             target_profile, outputMode="RGBA" if "A" in image.getbands() else "RGB")
            profile = target_profile.tobytes()
        except (ImageCms.PyCMSError, ValueError, OSError):
            # Invalid profiles must not break an otherwise readable image, or be attached to a different mode.
            pass
    image = image.convert("RGBA") if "A" in image.getbands() or "transparency" in image.info else image.convert("RGB")
    if options.resize:
        size = (options.width, options.height)
        if options.resize_mode == "crop":
            image = ImageOps.fit(image, size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            resized = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", size, "white")
            pos = ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2)
            if resized.mode == "RGBA":
                canvas.paste(resized, pos, resized.getchannel("A"))
            else:
                canvas.paste(resized, pos)
            image = canvas
    if fmt == "JPEG":
        image = flatten_white(image) if image.mode == "RGBA" else image.convert("RGB")
    if profile:
        image.info["icc_profile"] = profile
    else:
        image.info.pop("icc_profile", None)
    return image


def reserve_file(folder: Path, stem: str, extension: str):
    """Exclusive creation protects existing files and symlinks, including concurrent writers."""
    index = 1
    while True:
        name = f"{stem}{'' if index == 1 else '_' + str(index)}{extension}"
        target = folder / name
        try:
            return target, target.open("xb")
        except FileExistsError:
            index += 1


def create_output_folder(parent: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    name = f"商品图整理完成_{now:%Y-%m-%d_%H%M%S}"
    i = 1
    while True:
        target = parent / f"{name}{'' if i == 1 else '_' + str(i)}"
        try:
            target.mkdir(exist_ok=False)
            return target
        except FileExistsError:
            i += 1
        except OSError as exc:
            raise UserError(friendly_error(exc)) from exc


@dataclass
class Failure:
    name: str
    reason: str


@dataclass
class BatchResult:
    output_dir: str
    total: int
    attempted: int = 0
    success: int = 0
    failures: list[Failure] = field(default_factory=list)
    input_bytes: int = 0
    output_bytes: int = 0
    cancelled: bool = False
    report_error: str = ""
    outputs: list[str] = field(default_factory=list)

    @property
    def saved_bytes(self):
        return self.input_bytes - self.output_bytes

    @property
    def saved_percent(self):
        return self.saved_bytes / self.input_bytes * 100 if self.input_bytes else 0


def process_batch(entries: list[ImageEntry], options: Options, output_dir: Path,
                  cancel: threading.Event | None = None,
                  progress: Progress | None = None) -> BatchResult:
    options.validate()
    cancel = cancel or threading.Event()
    selected = [entry for entry in entries if entry.included]
    result = BatchResult(str(output_dir), len(selected))
    if not output_dir.is_dir():
        raise UserError("输出文件夹不存在，请重新选择输出位置。")
    for number, entry in enumerate(selected, 1):
        if cancel.is_set():
            result.cancelled = True
            break
        target = None
        try:
            # Read again: files can change after import. No stale import errors are trusted.
            before_size = entry.path.stat().st_size
            with read_image(entry.path) as original:
                fmt = original.format if options.output_format == "original" else options.output_format
                extension = FORMATS[fmt]
                stem = f"{options.prefix}_{number:0{options.digits}d}" if options.rename else entry.path.stem
                copy_only = not options.resize and not options.compress and options.output_format == "original"
                if copy_only:
                    extension = entry.path.suffix
                target, stream = reserve_file(output_dir, stem, extension)
                with stream:
                    if copy_only:
                        with entry.path.open("rb") as source:
                            shutil.copyfileobj(source, stream, 1024 * 1024)
                    else:
                        output = transform(original, options, fmt)
                        quality = {"high": 92, "balanced": 82, "small": 68}[options.quality] if options.compress else 95
                        kwargs = {"quality": quality, "optimize": True, "subsampling": 0 if quality >= 92 else 2} if fmt == "JPEG" else (
                            {"compress_level": 9 if options.compress else 6, "optimize": options.compress} if fmt == "PNG" else
                            {"quality": quality, "method": 4, "lossless": not options.compress})
                        if output.info.get("icc_profile"):
                            kwargs["icc_profile"] = output.info["icc_profile"]
                        output.save(stream, fmt, **kwargs)
                        output.close()
                result.output_bytes += target.stat().st_size
                result.input_bytes += before_size
                result.success += 1
                result.outputs.append(target.name)
        except Exception as exc:
            if target is not None:
                # This path was exclusively created by this operation; never remove a preexisting path.
                try:
                    target.unlink()
                except OSError:
                    pass
            result.failures.append(Failure(entry.path.name, friendly_error(exc)))
        result.attempted += 1
        if progress:
            progress(result.attempted, result.total, entry.path.name)
    try:
        report_path, report_stream = reserve_file(output_dir, "整理报告", ".json")
        with report_stream:
            payload = {"软件": "商品图批量整理器 1.0.0", "时间": datetime.now().isoformat(timespec="seconds"),
                       "说明": "原图未修改。大小统计仅比较成功处理的图片。", "结果": asdict(result), "设置": asdict(options)}
            report_stream.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    except OSError as exc:
        result.report_error = friendly_error(exc)
    return result


@dataclass
class DuplicateGroup:
    paths: list[Path]
    exact: bool


def digest(path: Path, cancel: threading.Event) -> str | None:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel.is_set():
                return None
            sha.update(chunk)
    return sha.hexdigest()


def visual_signature(path: Path):
    with read_image(path) as original:
        image = flatten_white(original)
        small = image.resize((32, 32), Image.Resampling.LANCZOS)
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
        return bits, bytes(small.tobytes()), original.width / original.height


def similar(a, b) -> bool:
    if abs(a[2] - b[2]) / max(a[2], b[2]) > 0.05 or (a[0] ^ b[0]).bit_count() > 6:
        return False
    # Color distance avoids grouping plain backgrounds or different-colored products by hash alone.
    return sum(abs(x - y) for x, y in zip(a[1], b[1])) / len(a[1]) <= 10


def detect_duplicates(entries: list[ImageEntry], include_similar: bool = True,
                      cancel: threading.Event | None = None,
                      progress: Progress | None = None) -> tuple[list[DuplicateGroup], list[Failure]]:
    cancel = cancel or threading.Event()
    hashes: dict[str, list[Path]] = {}
    signatures = {}
    failures = []
    # Include excluded entries too, so reopening the dialog lets the user change their choice.
    for i, entry in enumerate(entries, 1):
        if cancel.is_set():
            return [], failures
        try:
            value = digest(entry.path, cancel)
            if value is not None:
                if value not in hashes and include_similar:
                    signatures[value] = visual_signature(entry.path)
                hashes.setdefault(value, []).append(entry.path)
        except Exception as exc:
            failures.append(Failure(entry.path.name, friendly_error(exc)))
        if progress:
            progress(i, len(entries), entry.path.name)
    keys = list(hashes)
    used = set()
    groups = []
    for i, key in enumerate(keys):
        if cancel.is_set():
            return [], failures
        if key in used:
            continue
        matching = [key]
        if include_similar:
            for other in keys[i + 1:]:
                if cancel.is_set():
                    return [], failures
                if other not in used and similar(signatures[key], signatures[other]):
                    matching.append(other)
        used.update(matching)
        paths = [path for item in matching for path in hashes[item]]
        if len(paths) > 1:
            groups.append(DuplicateGroup(paths, len(matching) == 1))
    return groups, failures
