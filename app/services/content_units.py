from __future__ import annotations


def display_text_for_unit(
    *,
    unit_type: str,
    text_content: str,
    caption: str,
    section_name: str,
) -> str:
    text = (text_content or "").strip()
    cap = (caption or "").strip()
    section = (section_name or "").strip()

    if unit_type == "section":
        return text
    if cap and text:
        return f"{cap}\n\n{text}"
    if cap:
        return cap
    if text:
        return text
    if unit_type == "figure" and section:
        return f"Figure in {section}"
    if unit_type == "table" and section:
        return f"Table in {section}"
    if unit_type == "figure":
        return "Figure"
    if unit_type == "table":
        return "Table"
    return text
