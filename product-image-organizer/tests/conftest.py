import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image, ImageDraw


@pytest.fixture
def product():
    image = Image.new("RGB", (640, 400), "#f3ebe1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((210, 100, 440, 345), radius=30, fill="#bf6d40", outline="#704125", width=6)
    draw.arc((250, 35, 400, 205), 180, 360, fill="#704125", width=14)
    draw.rectangle((275, 150, 380, 190), fill="#e1ad74")
    draw.line((230, 250, 420, 250), fill="#704125", width=6)
    return image


@pytest.fixture
def app():
    from organizer.ui import create_application
    application = create_application()
    yield application
    application.processEvents()
