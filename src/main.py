"""Module defines the main entry point for the Apify Actor.

Feel free to modify this file to suit your specific needs.

To build Apify Actors, utilize the Apify SDK toolkit, read more at the official documentation:
https://docs.apify.com/sdk/python
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

from apify import Actor
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext


def _load_callable_from_code(raw_code: str, fallback_name: str) -> Optional[Callable[[Dict[str, Any]], Dict[str, Any]]]:
    """Safely convert a Python function definition string into a callable.

    The function must define a callable (e.g. ``def extend(record): ...`` or ``extend = lambda record: {...}``).
    JavaScript-style snippets are not supported; when evaluation fails the function returns ``None`` and the
    scraper continues without user-defined transformation.
    """

    if not raw_code or not raw_code.strip():
        return None

    namespace: Dict[str, Any] = {}
    try:
        exec(raw_code, namespace)  # noqa: S102 - trusted local execution by actor owners
    except Exception as exc:  # pragma: no cover - defensive logging
        Actor.log.warning(
            "Unable to evaluate %s. Provide a valid Python function that accepts a record dictionary. Error: %s",
            fallback_name,
            exc,
        )
        return None

    for value in namespace.values():
        if callable(value):
            return value  # type: ignore[return-value]

    Actor.log.warning("No callable found in provided %s code.", fallback_name)
    return None


def _extract_json_payload(soup) -> Dict[str, Any]:
    """Return decoded Pinterest JSON payload when available."""

    script_tag = soup.find("script", id="__PWS_DATA__")
    if not script_tag:
        return {}

    payload = script_tag.string or script_tag.get_text()
    if not payload:
        return {}

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        Actor.log.warning("Failed to decode Pinterest payload from __PWS_DATA__ script block.")
        return {}


def _gather_pin_nodes(raw_state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Traverse Redux state-like structure and collect pin dictionaries keyed by id."""

    pins: Dict[str, Dict[str, Any]] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            # Pins often live under ``state['pins']`` or nested inside resource responses.
            if node.get("type") == "pin" and node.get("id"):
                pins.setdefault(str(node["id"]), node)
            # Direct pin dictionaries keyed by id
            if set(node.keys()) and all(isinstance(k, str) for k in node.keys()):
                if all(isinstance(v, dict) and "id" in v for v in node.values()):
                    for value in node.values():
                        pins.setdefault(str(value.get("id")), value)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(raw_state)
    return pins


def _extract_hashtags(*texts: Optional[str]) -> List[str]:
    combined = " ".join(part or "" for part in texts)
    return sorted({match.lower() for match in re.findall(r"#(\w[\w-]*)", combined)})


def _normalize_image_sources(images: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if isinstance(images, dict):
        for label, meta in images.items():
            if isinstance(meta, dict):
                normalized.append(
                    {
                        "label": label,
                        "url": meta.get("url"),
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                    }
                )
    return normalized


def _normalize_video_sources(videos: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    video_list = None
    if isinstance(videos, dict):
        video_list = videos.get("video_list")
    if isinstance(video_list, dict):
        for label, meta in video_list.items():
            if isinstance(meta, dict):
                normalized.append(
                    {
                        "label": label,
                        "url": meta.get("url"),
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                        "duration": meta.get("duration"),
                        "bitrate": meta.get("bit_rate") or meta.get("bitrate"),
                    }
                )
    return normalized


def _resolve_user(pin: Dict[str, Any], users_by_id: Dict[str, Any]) -> Dict[str, Any]:
    candidate = pin.get("pinner") or pin.get("user")
    if isinstance(candidate, dict):
        user_id = str(candidate.get("id")) if candidate.get("id") else None
        enriched = users_by_id.get(user_id or "", {}) if users_by_id else {}
        merged = {**candidate, **enriched}
        merged["profile_url"] = merged.get("username") and f"https://www.pinterest.com/{merged['username']}/"
        return merged

    if candidate and users_by_id:
        user_data = users_by_id.get(str(candidate)) or {}
        if user_data:
            user_data = dict(user_data)
            user_data["profile_url"] = user_data.get("username") and f"https://www.pinterest.com/{user_data['username']}/"
        return user_data

    return {}


def _select_price(pin: Dict[str, Any]) -> Optional[str]:
    if pin.get("price"):
        return str(pin["price"])
    buyable = pin.get("buyable_product") or {}
    if isinstance(buyable, dict):
        price_value = buyable.get("price_value") or {}
        if isinstance(price_value, dict):
            amount = price_value.get("amount")
            currency = price_value.get("currency_code") or price_value.get("currency")
            if amount is not None:
                return f"{amount} {currency}" if currency else str(amount)
    return None


def _extract_comments(pin_id: str, raw_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    comments_state = raw_state.get("comments")
    collected: List[Dict[str, Any]] = []
    if isinstance(comments_state, dict):
        for comment in comments_state.values():
            if not isinstance(comment, dict):
                continue
            if str(comment.get("pin_id")) != pin_id:
                continue
            collected.append(
                {
                    "id": comment.get("id"),
                    "text": comment.get("text"),
                    "created_at": comment.get("created_at") or comment.get("created_at_iso") or comment.get("created_at_ms"),
                    "user": _resolve_user(comment, raw_state.get("users", {})),
                }
            )
    return collected


def _build_pin_record(
    pin: Dict[str, Any],
    users_by_id: Dict[str, Any],
    raw_state: Dict[str, Any],
    include_comments: bool,
    page_url: str,
    extend_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]],
    map_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]],
) -> Dict[str, Any]:
    pin_id = str(pin.get("id")) if pin.get("id") else None
    user = _resolve_user(pin, users_by_id)
    hashtags = _extract_hashtags(pin.get("description"), pin.get("title"), pin.get("grid_description"))
    price = _select_price(pin)
    images = _normalize_image_sources(pin.get("images"))
    videos = _normalize_video_sources(pin.get("videos"))
    base_record: Dict[str, Any] = {
        "type": "pin",
        "pin_id": pin_id,
        "pin_url": pin_id and f"https://www.pinterest.com/pin/{pin_id}/",
        "page_url": page_url,
        "title": pin.get("title") or pin.get("grid_title") or pin.get("description"),
        "description": pin.get("description") or pin.get("grid_description"),
        "alt_text": pin.get("alt_text"),
        "link": pin.get("link") or pin.get("source_link"),
        "created_at": pin.get("created_at") or pin.get("created_at_iso"),
        "language": pin.get("locale") or pin.get("language"),
        "hashtags": hashtags,
        "images": images,
        "videos": videos,
        "is_video": bool(videos),
        "price": price,
        "board_id": pin.get("board_id") or (pin.get("board") or {}).get("id"),
        "board_url": pin.get("board_id") and f"https://www.pinterest.com/pin/{pin.get('board_id')}/",
        "metrics": {
            "comment_count": pin.get("comment_count"),
            "save_count": pin.get("save_count") or pin.get("repin_count"),
            "reaction_counts": pin.get("reaction_counts"),
        },
        "dominant_color": pin.get("dominant_color"),
        "rich_metadata": pin.get("rich_metadata"),
        "section": pin.get("section"),
        "tags": pin.get("tags") or pin.get("keywords"),
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "full_name": user.get("full_name") or user.get("fullName"),
            "about": user.get("about") or user.get("bio"),
            "follower_count": user.get("follower_count"),
            "following_count": user.get("following_count"),
            "profile_url": user.get("profile_url"),
            "locale": user.get("locale"),
            "country": user.get("country"),
            "verified": user.get("verified") or user.get("is_verified"),
        },
        "user_language": user.get("language") or user.get("locale"),
        "user_locale": user.get("locale"),
    }

    if include_comments and pin_id:
        base_record["comments"] = _extract_comments(pin_id, raw_state)

    if extend_fn:
        try:
            extended = extend_fn(dict(base_record))
            if isinstance(extended, dict):
                base_record.update(extended)
        except Exception as exc:  # pragma: no cover - defensive logging
            Actor.log.warning("extendOutputFunction failed for pin %s: %s", pin_id, exc)

    if map_fn:
        try:
            mapped = map_fn(dict(base_record))
            if isinstance(mapped, dict):
                base_record = mapped
        except Exception as exc:  # pragma: no cover - defensive logging
            Actor.log.warning("customMapFunction failed for pin %s: %s", pin_id, exc)

    return base_record


async def main() -> None:
    """Define a main entry point for the Apify Actor.

    This coroutine is executed using `asyncio.run()`, so it must remain an asynchronous function for proper execution.
    Asynchronous execution is required for communication with Apify platform, and it also enhances performance in
    the field of web scraping significantly.
    """
    # Enter the context of the Actor.
    async with Actor:
        actor_input = await Actor.get_input() or {}
        start_urls_source = actor_input.get("startUrls") or actor_input.get("start_urls") or []
        start_urls = [entry.get("url") for entry in start_urls_source if isinstance(entry, dict) and entry.get("url")]
        if not start_urls:
            start_urls = ["https://www.pinterest.com"]

        include_comments = bool(actor_input.get("includeComments", False))
        include_user_info_only = bool(actor_input.get("includeUserInfoOnly", False))
        max_items = int(actor_input.get("maxItems", 50))
        extend_fn = _load_callable_from_code(actor_input.get("extendOutputFunction", ""), "extendOutputFunction")
        map_fn = _load_callable_from_code(actor_input.get("customMapFunction", ""), "customMapFunction")

        # End page is kept for compatibility with the provided JSON config. The value is used as a soft cap on
        # crawled requests to avoid runaway pagination in the absence of an explicit request queue.
        end_page = max(int(actor_input.get("endPage", 1)), 1)

        crawler = BeautifulSoupCrawler(
            max_requests_per_crawl=end_page * max_items,
        )

        @crawler.router.default_handler
        async def handle_pinterest(context: BeautifulSoupCrawlingContext) -> None:
            url = context.request.url
            Actor.log.info("Scraping Pinterest source: %s", url)

            payload = _extract_json_payload(context.soup)
            raw_state = (
                payload.get("props", {})
                .get("initialReduxState", payload.get("props", {}).get("pageProps", {}).get("initialReduxState", {}))
                if isinstance(payload, dict)
                else {}
            )

            users_by_id = raw_state.get("users", {}) if isinstance(raw_state, dict) else {}
            pin_nodes = _gather_pin_nodes(raw_state)

            if include_user_info_only and users_by_id:
                for user_id, user in users_by_id.items():
                    record = {
                        "type": "user",
                        "user_id": user_id,
                        "username": user.get("username"),
                        "full_name": user.get("full_name") or user.get("fullName"),
                        "about": user.get("about") or user.get("bio"),
                        "profile_url": user.get("username") and f"https://www.pinterest.com/{user['username']}/",
                        "follower_count": user.get("follower_count"),
                        "following_count": user.get("following_count"),
                        "country": user.get("country"),
                        "locale": user.get("locale"),
                        "verified": user.get("verified") or user.get("is_verified"),
                        "language": user.get("language") or user.get("locale"),
                    }
                    if extend_fn:
                        try:
                            addition = extend_fn(dict(record))
                            if isinstance(addition, dict):
                                record.update(addition)
                        except Exception as exc:  # pragma: no cover - defensive logging
                            Actor.log.warning("extendOutputFunction failed for user %s: %s", user_id, exc)
                    if map_fn:
                        try:
                            mapped = map_fn(dict(record))
                            if isinstance(mapped, dict):
                                record = mapped
                        except Exception as exc:  # pragma: no cover - defensive logging
                            Actor.log.warning("customMapFunction failed for user %s: %s", user_id, exc)

                    await context.push_data(record)
                return

            if not pin_nodes:
                Actor.log.warning("No Pinterest pins detected on %s", url)
                return

            exported = 0
            for pin in pin_nodes.values():
                if exported >= max_items:
                    break
                record = _build_pin_record(
                    pin=pin,
                    users_by_id=users_by_id,
                    raw_state=raw_state,
                    include_comments=include_comments,
                    page_url=url,
                    extend_fn=extend_fn,
                    map_fn=map_fn,
                )
                await context.push_data(record)
                exported += 1

        await crawler.run(start_urls)
