from types import SimpleNamespace

import pytest

from pretix_furbadge.badge_renderer import BadgeRenderer


class DummyBadgeType:
    def __init__(self):
        self.background_pdf = None
        self.font = None
        self.font_size_max = 48.0
        self.text_max_width = 50.0
        self.image_width = 10.0
        self.image_height = 10.0
        self.image_pos_x = 0.0
        self.image_pos_y = 0.0
        self.avatar_shape = "rect"
        self.font_color = "#000000"
        self.text_pos_x = 0.0
        self.text_pos_y = 0.0
        self.text_justify = "center"
        self.foreground_pdf = None


def test_render_requires_background_pdf():
    renderer = BadgeRenderer(DummyBadgeType())
    badge_data = SimpleNamespace(badge_link=SimpleNamespace(event=SimpleNamespace(settings=SimpleNamespace(get=lambda *args, **kwargs: None))))

    with pytest.raises(ValueError):
        renderer.render(badge_data)
