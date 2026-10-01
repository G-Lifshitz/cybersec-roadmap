"""Inline SVG icons for the templates (24x24 grid, drawn with strokes).

Icons are data: adding one is a new entry in _PATHS, with no change to the
templates or to icon() itself (open/closed principle).
"""
from markupsafe import Markup

_PATHS = {
    "book": '<path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5c-3.5-.5-6.5 0-8.5 1.5zM12 6.5v13"/>',
    "chart": '<path d="M5 19v-5M10 19V9M15 19v-7M20 19V6"/>',
    "file": '<path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h4"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>',
    "shield": '<path d="M12 3l7 3v5.5c0 4.3-3 7.8-7 9.5-4-1.7-7-5.2-7-9.5V6z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "lock": '<rect x="6" y="10.5" width="12" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
}


def icon(name):
    """Return the named icon as safe HTML.

    The markup comes only from the constants above, never from user input,
    so marking it safe can't introduce XSS. An unknown name raises KeyError,
    so a typo in a template fails loudly instead of rendering nothing.
    """
    return Markup(
        '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f"{_PATHS[name]}</svg>"
    )
