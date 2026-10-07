"""Build verification only; exercise codecs from the actual frozen application."""
import hashlib
import json
import tempfile
from pathlib import Path

from PIL import Image

from .core import Options, create_output_folder, detect_duplicates, inspect_image, process_batch


def verify_package(parent: Path) -> int:
    parent.mkdir(parents=True, exist_ok=True)
    checks = []
    try:
        with tempfile.TemporaryDirectory(prefix="商品图打包校验_", dir=parent) as temporary:
            root = Path(temporary)
            paths = []
            for fmt, extension in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
                path = root / f"中文 space.{extension}"
                image = Image.new("RGBA" if fmt == "PNG" else "RGB", (120, 80), (180, 90, 40, 180) if fmt == "PNG" else (180, 90, 40))
                image.save(path, fmt)
                paths.append(path)
            source_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
            entries = [inspect_image(path) for path in paths]
            if any(entry.error for entry in entries):
                raise RuntimeError("打包后的编解码器未能读取全部格式")
            for fmt in ("JPEG", "PNG", "WEBP"):
                options = Options(rename=True, prefix="女包", resize=True, width=100, height=100, output_format=fmt)
                result = process_batch(entries, options, create_output_folder(root))
                if result.success != 3 or result.failures:
                    raise RuntimeError(f"打包后的 {fmt} 编解码器未通过转换")
                for name in result.outputs:
                    with Image.open(Path(result.output_dir) / name) as output:
                        output.load()
                        if output.format != fmt or output.size != (100, 100):
                            raise RuntimeError("打包后输出图片校验失败")
                checks.append(f"{fmt} 输出通过")
            groups, failures = detect_duplicates([entries[0], entries[0]], True)
            if len(groups) != 1 or failures:
                raise RuntimeError("打包后的重复检测未通过")
            if [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] != source_hashes:
                raise RuntimeError("原图保护校验失败")
            checks.extend(["重复检测通过", "原图哈希未变"])
        result = {"passed": True, "checks": checks}
    except Exception as exc:
        result = {"passed": False, "checks": checks, "reason": str(exc)}
    with (parent / "package-check.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return 0 if result["passed"] else 1
