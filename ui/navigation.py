"""Sidebar navigation, defined as data rather than hard-coded in base.html."""
from dataclasses import dataclass


@dataclass(frozen=True)
class NavLink:
    endpoint: str      # Flask endpoint the link points to
    label: str
    icon: str          # key in ui.icons
    active_on: tuple   # endpoints that highlight this link


MAIN_LINKS = (
    NavLink("index", "Roadmap", "book", ("index", "choose_path")),
    NavLink("progress", "Progress", "chart", ("progress", "item_detail", "edit_item", "add_item")),
    NavLink("assessment", "Assessment", "compass", ("assessment", "take_assessment", "assessment_result")),
    NavLink("recommendations", "Resources", "file", ("recommendations",)),
    NavLink("settings", "Profile", "user", ("settings", "change_password", "delete_account")),
)
ADMIN_LINKS = (
    NavLink("admin", "Admin", "shield", ("admin",)),
)


def links_for(user):
    """The links a given user sees: everyone gets the main pages, admins also get Admin."""
    if user and user["is_admin"]:
        return MAIN_LINKS + ADMIN_LINKS
    return MAIN_LINKS
