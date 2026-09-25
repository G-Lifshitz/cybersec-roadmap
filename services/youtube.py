import os
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Curated channel IDs worth prioritising in results
TRUSTED_CHANNELS = {
    "UCVeW9qkBjo3zosnqUbG7CFw",  # TCM Security
    "UC0ZTPkdxlAKf-V33tqXwi3Q",  # HackerSploit
    "UCa6eh7gCkpPo5XXUDfygmfw",  # IppSec
    "UCUB9vOGEUpw7IKJRoR4PkIA",  # John Hammond
    "UCgTNupxATBfWmfehv21ym-g",  # NetworkChuck
}


def search_videos(query, max_results=5):
    """Search YouTube for cybersecurity learning videos matching query."""
    if not YOUTUBE_API_KEY:
        return []

    try:
        resp = requests.get(
            SEARCH_URL,
            params={
                "part": "snippet",
                "q": f"cybersecurity {query} tutorial",
                "type": "video",
                "maxResults": max_results * 2,  # fetch extra, filter below
                "relevanceLanguage": "en",
                "key": YOUTUBE_API_KEY,
            },
            timeout=5,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except requests.RequestException:
        return []

    videos = []
    for item in items:
        snippet = item.get("snippet", {})
        videos.append({
            "video_id": item["id"]["videoId"],
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
            "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            "trusted": snippet.get("channelId", "") in TRUSTED_CHANNELS,
        })

    # Trusted channels float to the top
    videos.sort(key=lambda v: not v["trusted"])
    return videos[:max_results]


def recommend_for_skills(skill_tags):
    """
    Given a list of skill tags (e.g. ['web', 'network']),
    return a dict of tag -> video list.
    """
    recommendations = {}
    for tag in skill_tags[:3]:  # cap at 3 tags to stay within API quota
        recommendations[tag] = search_videos(tag)
    return recommendations


SUBSCRIPTIONS = [
    {
        "name": "TryHackMe Premium",
        "url": "https://tryhackme.com/subscriptions",
        "price": "$14/mo",
        "best_for": ["beginner", "intermediate"],
        "why": "Structured learning paths, guided rooms, certificates of completion.",
    },
    {
        "name": "HackTheBox VIP",
        "url": "https://www.hackthebox.com/billing",
        "price": "$14/mo",
        "best_for": ["intermediate", "advanced"],
        "why": "Retired machines with IppSec walkthroughs, Pro Labs for OSCP prep.",
    },
    {
        "name": "TCM Security Academy",
        "url": "https://academy.tcm-sec.com",
        "price": "$30/mo or pay-per-course",
        "best_for": ["beginner", "intermediate"],
        "why": "Practical Ethical Hacking course is one of the best OSCP primers.",
    },
    {
        "name": "OffSec Learn (OSCP)",
        "url": "https://www.offsec.com/courses/pen-200/",
        "price": "$1499 exam bundle",
        "best_for": ["advanced"],
        "why": "OSCP is the industry-standard pentest cert. Expensive but worth it.",
    },
]


def get_subscriptions(difficulty_level=None):
    if not difficulty_level:
        return SUBSCRIPTIONS
    return [s for s in SUBSCRIPTIONS if difficulty_level in s["best_for"]]


class RecommendationService:
    """
    Facade over the YouTube video search and subscription subsystems.

    Pattern: Facade (Structural)
    Provides a single, simplified interface that routes callers use instead of
    calling search_videos(), recommend_for_skills(), and get_subscriptions()
    directly.  Implementation details (API key handling, trusted-channel
    sorting, quota cap) are hidden inside the methods below.
    """

    def for_weak_skills(self, weak_tags):
        """Return (videos_dict, subscriptions_list) for the recommendations page.

        Args:
            weak_tags: list of skill tags flagged as weak by weak_skills()
        Returns:
            (dict[tag -> list[video]], list[subscription])
        """
        videos = recommend_for_skills(weak_tags) if weak_tags else {}
        subs = get_subscriptions()
        return videos, subs

    def for_item(self, skill_tags, max_tags=2):
        """Return video recommendations for a single roadmap item.

        Args:
            skill_tags: list of strings already split from the item's skill_tags field
            max_tags:   how many tags to search (default 2, keeps quota low)
        Returns:
            dict[tag -> list[video]]
        """
        tags = [t.strip() for t in skill_tags if t.strip()][:max_tags]
        return recommend_for_skills(tags) if tags else {}
