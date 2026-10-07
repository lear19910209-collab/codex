import json

import pytest
from PIL import Image, ImageCms

from organizer.core import Options, create_output_folder, inspect_image, process_batch
from organizer.settings import Preferences, load_preferences


@pytest.mark.parametrize("invalid", [{"quality": "bad"}, {"output_format": "TIFF"}, {"width": -1}, {"width": 10000, "height": 10000}])
def test_invalid_settings_never_prevent_launch(tmp_path, invalid):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps(invalid))
    assert load_preferences(path) == Preferences()


def test_color_profile_conversion(tmp_path, product):
    path = tmp_path / "带色彩描述.jpg"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    product.save(path, icc_profile=profile)
    result = process_batch([inspect_image(path)], Options(resize=True, output_format="PNG"), create_output_folder(tmp_path))
    assert result.success == 1
    with Image.open(result.output_dir + "/" + result.outputs[0]) as image:
        assert image.info.get("icc_profile") and image.mode == "RGB"


def test_invalid_profile_ignored(tmp_path, product):
    path = tmp_path / "错误描述.jpg"
    product.save(path, icc_profile=b"invalid profile")
    result = process_batch([inspect_image(path)], Options(output_format="PNG"), create_output_folder(tmp_path))
    assert result.success == 1
    with Image.open(result.output_dir + "/" + result.outputs[0]) as image:
        assert not image.info.get("icc_profile")


def test_cmyk_jpeg_conversion(tmp_path, product):
    path = tmp_path / "印刷模式.jpg"
    product.convert("CMYK").save(path)
    result = process_batch([inspect_image(path)], Options(output_format="JPEG"), create_output_folder(tmp_path))
    assert result.success == 1
    with Image.open(result.output_dir + "/" + result.outputs[0]) as image:
        assert image.mode == "RGB"
