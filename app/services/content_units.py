from __future__ import annotations


def compose_text_content(*, unit_type: str, text_content: str, caption: str) -> str:
    text = (text_content or "").strip()
    cap = (caption or "").strip()

    if unit_type == "section":
        return text
    if cap and text:
        return f"{cap}\n\n{text}"
    if cap:
        return cap
    if text:
        return text
    raise ValueError(f"{unit_type} content must include text_content or caption.")
