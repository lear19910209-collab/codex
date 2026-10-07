import errno
import hashlib
import json
import shutil
import threading
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from organizer.core import (
    ImageEntry, Options, UserError, create_output_folder, detect_duplicates,
    friendly_error, inspect_image, process_batch, read_image, scan_paths,
    transform, validate_prefix,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(tmp_path, sources, options):
    folder = create_output_folder(tmp_path)
    result = process_batch([inspect_image(path) for path in sources], options, folder)
    return result, [folder / name for name in result.outputs]


@pytest.mark.parametrize("count", [1, 10, 100, 500])
def test_batch_sizes_and_source_integrity(tmp_path, product, count):
    source = tmp_path / "原始图片"
    source.mkdir()
    paths = []
    for index in range(count):
        path = source / f"商品 English space {index:03}.jpg"
        product.save(path, quality=98)
        paths.append(path)
    originals = {path: sha(path) for path in paths}
    progress = []
    folder = create_output_folder(tmp_path)
    result = process_batch([inspect_image(path) for path in paths],
                           Options(rename=True, prefix="女包", resize=True, width=160, height=160),
                           folder, progress=lambda *args: progress.append(args))
    assert result.success == count and not result.failures
    assert len(progress) == count and progress[-1][:2] == (count, count)
    assert result.output_bytes < result.input_bytes
    assert (folder / f"女包_{count:03}.jpg").exists()
    assert all(sha(path) == value for path, value in originals.items())
    assert all(Image.open(folder / name).size == (160, 160) for name in result.outputs)
    assert json.loads((folder / "整理报告.json").read_text("utf-8"))["结果"]["success"] == count


@pytest.mark.parametrize("source_format", ["JPEG", "PNG", "WEBP"])
@pytest.mark.parametrize("output_format", ["JPEG", "PNG", "WEBP"])
def test_all_format_conversions(tmp_path, product, source_format, output_format):
    path = tmp_path / ("中文 名称" + {"JPEG": ".jpeg", "PNG": ".png", "WEBP": ".webp"}[source_format])
    product.save(path, source_format)
    before = sha(path)
    result, outputs = run(tmp_path, [path], Options(output_format=output_format))
    assert result.success == 1
    with Image.open(outputs[0]) as image:
        assert image.format == output_format and image.size == product.size
    assert sha(path) == before


@pytest.mark.parametrize("size", [(400, 200), (200, 400), (300, 300)])
@pytest.mark.parametrize("mode", ["pad", "crop"])
def test_resize_without_distortion(size, mode):
    original = Image.new("RGB", size, "red")
    options = Options(resize=True, width=200, height=200, resize_mode=mode)
    output = transform(original, options, "PNG")
    assert output.size == (200, 200)
    assert output.getpixel((100, 100)) == (255, 0, 0)
    if mode == "pad" and size[0] > size[1]:
        assert output.getpixel((100, 0)) == (255, 255, 255)
        assert output.getpixel((100, 49)) == (255, 255, 255)
        assert output.getpixel((100, 50)) == (255, 0, 0)
    elif mode == "pad" and size[0] < size[1]:
        assert output.getpixel((0, 100)) == (255, 255, 255)
        assert output.getpixel((49, 100)) == (255, 255, 255)
        assert output.getpixel((50, 100)) == (255, 0, 0)
    else:
        assert output.getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize("mode", ["pad", "crop"])
def test_circle_keeps_geometry(mode):
    from PIL import ImageDraw
    image = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(image).ellipse((150, 50, 250, 150), fill="black")
    output = transform(image, Options(resize=True, width=200, height=200, resize_mode=mode), "PNG")
    points = [(x, y) for y in range(200) for x in range(200) if output.getpixel((x, y))[0] < 100]
    xs, ys = zip(*points)
    assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) <= 1


def test_alpha_white_and_lossless_png(tmp_path):
    path = tmp_path / "透明.png"
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 0))
    image.putpixel((50, 50), (0, 0, 255, 255))
    image.save(path)
    result, outputs = run(tmp_path, [path], Options(output_format="JPEG", quality="high"))
    assert result.success == 1
    with Image.open(outputs[0]) as output:
        assert all(value >= 250 for value in output.getpixel((0, 0)))
    result, outputs = run(tmp_path, [path], Options(output_format="PNG"))
    with Image.open(outputs[0]) as output:
        assert output.convert("RGBA").tobytes() == image.tobytes()


def test_compression_sizes_and_quality(tmp_path, product):
    path = tmp_path / "high.jpg"
    product.save(path, quality=100, subsampling=0)
    sizes = []
    for quality in ("high", "balanced", "small"):
        result, outputs = run(tmp_path, [path], Options(quality=quality))
        assert result.success == 1 and result.saved_bytes > 0
        sizes.append(result.output_bytes)
        with Image.open(outputs[0]) as output:
            difference = ImageChops.difference(output.convert("RGB"), product)
            assert max(ImageStat.Stat(difference).mean) < 5  # No severe loss on the fixture.
    assert sizes[0] > sizes[1] > sizes[2]


def test_no_operations_copies_exact_bytes(tmp_path, product):
    path = tmp_path / "Original JPEG.JPG"
    product.save(path)
    result, outputs = run(tmp_path, [path], Options(compress=False, rename=True, prefix="女包", digits=4))
    assert outputs[0].name == "女包_0001.JPG"
    assert outputs[0].read_bytes() == path.read_bytes()


def test_duplicates_exact_and_resized(tmp_path, product):
    original = tmp_path / "商品.jpg"
    exact = tmp_path / "改名字.jpg"
    resized = tmp_path / "缩小.webp"
    other = tmp_path / "另一张.png"
    product.save(original, quality=98)
    shutil.copyfile(original, exact)
    product.resize((320, 200)).save(resized, quality=80)
    Image.new("RGB", (640, 400), "blue").save(other)
    paths = [original, exact, resized, other]
    entries = [inspect_image(path) for path in paths]
    groups, failures = detect_duplicates(entries, False)
    assert not failures and len(groups) == 1 and groups[0].exact
    assert set(groups[0].paths) == {original, exact}
    groups, failures = detect_duplicates(entries, True)
    assert not failures and len(groups) == 1 and not groups[0].exact
    assert set(groups[0].paths) == {original, exact, resized}
    assert len(list(tmp_path.glob("*"))) == 4  # Detection never creates/removes source files.


def test_plain_different_colors_not_similar(tmp_path):
    paths = []
    for index, color in enumerate(("red", "blue", "white", "black")):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (100, 100), color).save(path)
        paths.append(path)
    groups, _ = detect_duplicates([inspect_image(path) for path in paths])
    assert not groups


def test_corrupt_file_and_continue(tmp_path, product):
    corrupt = tmp_path / "损坏.jpg"
    corrupt.write_bytes(b"not a jpeg")
    good = tmp_path / "正常.png"
    product.save(good)
    result, outputs = run(tmp_path, [corrupt, good], Options())
    assert result.success == 1 and len(result.failures) == 1
    assert "损坏" in result.failures[0].reason
    assert not (Path(result.output_dir) / "损坏.jpg").exists()
    assert corrupt.read_bytes() == b"not a jpeg"


def test_truncated_file_is_rejected(tmp_path, product):
    path = tmp_path / "truncated.jpg"
    product.save(path)
    content = path.read_bytes()
    path.write_bytes(content[:len(content)//2])
    assert inspect_image(path).error


def test_collision_never_overwrites_including_source(tmp_path, product):
    source = tmp_path / "女包_001.jpg"
    product.save(source)
    snapshot = sha(source)
    occupied = tmp_path / "女包_001_2.jpg"
    occupied.write_bytes(b"KEEP THIS FILE")
    result = process_batch([inspect_image(source)], Options(rename=True, prefix="女包"), tmp_path)
    assert result.outputs == ["女包_001_3.jpg"]
    assert sha(source) == snapshot and occupied.read_bytes() == b"KEEP THIS FILE"


def test_output_folder_always_new(tmp_path):
    time = datetime(2026, 10, 7, 15, 30)
    first = create_output_folder(tmp_path, time)
    second = create_output_folder(tmp_path, time)
    assert first != second and first.exists() and second.exists()


def test_excluded_files_not_output(tmp_path, product):
    path = tmp_path / "excluded.jpg"
    product.save(path)
    entry = inspect_image(path)
    entry.included = False
    folder = create_output_folder(tmp_path)
    result = process_batch([entry], Options(), folder)
    assert result.total == result.success == 0
    assert list(folder.glob("*.jpg")) == [] and path.exists()


def test_cancel_between_images(tmp_path, product):
    paths = []
    for i in range(10):
        path = tmp_path / f"{i}.jpg"
        product.save(path)
        paths.append(path)
    event = threading.Event()
    result = process_batch([inspect_image(path) for path in paths], Options(), create_output_folder(tmp_path), event,
                           lambda *_: event.set())
    assert result.cancelled and result.success == result.attempted == 1
    assert len(paths) == 10 and all(path.exists() for path in paths)


def test_import_recursion_and_dedup_paths(tmp_path, product):
    nested = tmp_path / "nested"
    nested.mkdir()
    path = nested / "hello 中文 space.PNG"
    product.save(path)
    (tmp_path / "ignore.txt").write_text("hello")
    entries = []
    errors = scan_paths([tmp_path, path], threading.Event(), entries.append)
    assert not errors and len(entries) == 1 and entries[0].path == path.resolve()


def test_exif_orientation(tmp_path):
    path = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (120, 60), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, exif=exif)
    assert (inspect_image(path).width, inspect_image(path).height) == (60, 120)
    result, outputs = run(tmp_path, [path], Options(output_format="PNG"))
    with Image.open(outputs[0]) as output:
        assert output.size == (60, 120) and output.getexif().get(274, 1) == 1


def test_large_resolution(tmp_path):
    path = tmp_path / "超大6000x4000.jpg"
    with Image.new("RGB", (6000, 4000), "#ecc49c") as image:
        image.save(path)
    result, outputs = run(tmp_path, [path], Options(resize=True))
    assert result.success == 1 and Image.open(outputs[0]).size == (800, 800)


@pytest.mark.parametrize("prefix", ["", " ", "商品/图", "a:b", "hello.", "CON", "NUL.txt", "a\n", "x" * 81])
def test_invalid_names(prefix):
    with pytest.raises(UserError):
        validate_prefix(prefix)


@pytest.mark.parametrize("prefix", ["女包", "English with spaces", "商品-图片", "女包_100"])
def test_valid_names(prefix):
    validate_prefix(prefix)


def test_disk_full_and_permission_cleanup(tmp_path, product, monkeypatch):
    path = tmp_path / "商品.jpg"
    product.save(path)
    original = sha(path)
    for number in (errno.ENOSPC, errno.EACCES):
        def broken_save(*args, **kwargs):
            raise OSError(number, "test error")
        with monkeypatch.context() as patch:
            patch.setattr(Image.Image, "save", broken_save)
            # Inspect before mocking encoder to ensure this tests output, not thumbnail creation.
            result = process_batch([ImageEntry(path)], Options(), create_output_folder(tmp_path))
        assert result.success == 0 and len(result.failures) == 1
        assert "空间不足" in result.failures[0].reason if number == errno.ENOSPC else "权限" in result.failures[0].reason
        assert not list(Path(result.output_dir).glob("*.jpg"))
        assert sha(path) == original


def test_animated_rejected(tmp_path):
    path = tmp_path / "animated.webp"
    a = Image.new("RGB", (40, 40), "red")
    b = Image.new("RGB", (40, 40), "blue")
    a.save(path, save_all=True, append_images=[b], duration=100, loop=0)
    assert "动态" in inspect_image(path).error


def test_actual_format_checked_not_extension(tmp_path):
    path = tmp_path / "pretend.jpg"
    Image.new("RGB", (40, 40), "red").save(path, "BMP")
    assert "格式不支持" in inspect_image(path).error
