"""Generate original app icon and synthetic product images for repeatable previews."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def make_icon():
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 252, 252), radius=56, fill="#3977ee")
    draw.rounded_rectangle((46, 50, 197, 209), radius=18, fill="#91b8ff")
    draw.rounded_rectangle((63, 33, 218, 190), radius=18, fill="white")
    draw.ellipse((155, 54, 184, 83), fill="#b2ccff")
    draw.polygon([(80, 161), (119, 108), (148, 143), (169, 119), (201, 161)], fill="#3977ee")
    image.save(ROOT / "assets" / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(ROOT / "assets" / "app.png")


def make_samples(folder):
    folder.mkdir(parents=True, exist_ok=True)
    colors = ["#9a633f", "#272f37", "#c29b76", "#b3835c", "#464343", "#a68162", "#ccac89", "#714a37", "#dbc9b6", "#57635d"]
    paths = []
    for index, color in enumerate(colors):
        width, height = [(900, 650), (650, 900), (800, 800)][index % 3]
        image = Image.new("RGB", (width, height), "#f1ede6")
        draw = ImageDraw.Draw(image)
        sx, sy = width / 800, height / 800
        def box(values):
            return tuple(int(value * (sx if i % 2 == 0 else sy)) for i, value in enumerate(values))
        draw.ellipse(box((140, 632, 660, 710)), fill="#ddd6ce")
        draw.rounded_rectangle(box((180, 280, 625, 650)), radius=40, fill=color)
        draw.arc(box((270, 120, 535, 430)), 180, 360, fill="#634734", width=max(8, int(20*sx)))
        draw.line(box((230, 500, 575, 500)), fill="#674c3a", width=max(3, int(5*sx)))
        draw.rounded_rectangle(box((355, 330, 455, 370)), radius=7, fill="#d4b273")
        draw.line(box((210, 330, 210, 610)), fill="#e7cfb4", width=2)
        extension = ["jpg", "png", "webp"][index % 3]
        path = folder / f"女包 商品图_{index+1:02}.{extension}"
        image.save(path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    make_icon()
