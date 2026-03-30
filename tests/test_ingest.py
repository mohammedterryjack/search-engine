from __future__ import annotations

from types import SimpleNamespace

from app.services.ingest import extract_structured_units


class FakeLabel:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeProv:
    def __init__(self, page_no: int, bbox: object | None = None) -> None:
        self.page_no = page_no
        self.bbox = bbox


class FakeTableData:
    def to_markdown(self, index: bool = False) -> str:
        return "| a | b |\n|---|---|\n| 1 | 2 |"


class FakeItem:
    def __init__(
        self,
        *,
        label: str,
        text: str = "",
        ref: str,
        page_no: int,
        caption: str = "",
        markdown: str = "",
        table: bool = False,
    ) -> None:
        self.label = FakeLabel(label)
        self.text = text
        self.self_ref = ref
        self.prov = [FakeProv(page_no, bbox=SimpleNamespace(l=1, t=2, r=3, b=4))]
        self._caption = caption
        self._markdown = markdown
        self._table = table

    def caption_text(self, _doc: object) -> str:
        return self._caption

    def export_to_markdown(self, _doc: object) -> str:
        return self._markdown

    def export_to_dataframe(self, _doc: object) -> FakeTableData:
        if not self._table:
            raise RuntimeError("not a table")
        return FakeTableData()


class FakeDoc:
    def __init__(self, items: list[FakeItem]) -> None:
        self._items = items
        self.body = object()

    def iterate_items(self, **_kwargs: object):
        for item in self._items:
            yield item, 0


def test_extract_structured_units_handles_sections_figures_and_tables() -> None:
    doc = FakeDoc(
        [
            FakeItem(label="section_header", text="Intro", ref="ref-1", page_no=1),
            FakeItem(label="paragraph", text="Chaos text", ref="ref-2", page_no=1),
            FakeItem(
                label="picture",
                ref="ref-3",
                page_no=2,
                caption="Figure caption",
                markdown="figure body",
            ),
            FakeItem(label="table", ref="ref-4", page_no=3, caption="Table caption", table=True),
        ]
    )

    units = extract_structured_units(doc)
    unit_types = [unit.unit_type for unit in units]
    assert "section" in unit_types
    assert "figure" in unit_types
    assert "table" in unit_types
    assert any(unit.page_number == 2 and "Figure caption" in unit.display_text for unit in units)
    assert any(unit.page_number == 3 and "Table caption" in unit.display_text for unit in units)
