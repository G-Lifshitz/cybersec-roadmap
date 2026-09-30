import pytest
from markupsafe import Markup

from ui.icons import icon
from ui.navigation import ADMIN_LINKS, MAIN_LINKS, links_for


def test_icon_returns_safe_svg_markup():
    svg = icon("book")
    assert isinstance(svg, Markup)          # Jinja won't escape it
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_unknown_icon_fails_loudly():
    with pytest.raises(KeyError):
        icon("no-such-icon")


def test_every_nav_link_points_at_a_real_icon():
    for link in MAIN_LINKS + ADMIN_LINKS:
        icon(link.icon)                     # raises KeyError if the name is wrong


def test_regular_user_does_not_see_admin_link():
    endpoints = [link.endpoint for link in links_for({"is_admin": 0})]
    assert "admin" not in endpoints


def test_admin_sees_admin_link():
    endpoints = [link.endpoint for link in links_for({"is_admin": 1})]
    assert endpoints[-1] == "admin"


def test_logged_out_visitor_gets_main_links_only():
    assert links_for(None) == MAIN_LINKS
