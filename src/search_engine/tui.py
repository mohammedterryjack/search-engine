from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.widgets import Button, ContentSwitcher, Input, ListItem, ListView, Static

from .config import RootConfig
from .paging import load_page_number
from .runtime import build_runtime
from .search_backend import tokenize_terms


class SearchTUI(App[None]):
    PINK_THEME = Theme(
        name="search-engine-pink",
        primary="#c94f7c",
        secondary="#d66a91",
        accent="#ff8fb1",
        warning="#ff9fbc",
        error="#b43f69",
        success="#c94f7c",
        foreground="#4c3140",
        background="#ffb3c7",
        surface="#ffd6e3",
        panel="#ffc1d5",
        boost="#ffe5ee",
        dark=False,
        variables={
            "footer-key-foreground": "#8a2048",
            "input-selection-background": "#ff8fb1 40%",
            "border": "#c94f7c",
            "border-blurred": "#d66a91",
            "button-color-foreground": "#4c3140",
        },
    )

    CSS = """
    Screen {
        layout: vertical;
        background: #ffb3c7;
        color: #4c3140;
    }

    Static {
        color: #4c3140;
    }

    #titlebar {
        background: #ff8fb1;
        color: #4c3140;
        text-style: bold;
        padding: 0 2;
        height: 1;
    }

    #tabbar {
        background: #ffb3c7;
        height: 3;
        padding: 0 1;
    }

    .tab_button {
        background: #ffc1d5;
        color: #4c3140;
        border: round #d66a91;
        margin: 0 1 0 1;
        min-width: 10;
    }

    .tab_button.-active {
        background: #ffd6e3;
        color: #4c3140;
        border: round #c94f7c;
        text-style: bold;
    }

    ContentSwitcher {
        background: #ffb3c7;
        height: 1fr;
    }

    .pane {
        background: #ffb3c7;
        color: #4c3140;
    }

    #query {
        margin: 0;
        background: #ffe5ee;
        color: #4c3140;
        border: round #d66a91;
        width: 1fr;
    }

    #query:focus {
        background: #ffd6e3 !important;
        border: round #c94f7c !important;
    }

    #root_input {
        margin: 1 2 1 2;
        background: #ffe5ee;
        color: #4c3140;
        border: round #d66a91;
    }

    #root_input:focus {
        background: #ffd6e3 !important;
        border: round #c94f7c !important;
    }

    #status {
        margin: 0 2 1 2;
        color: #6d4458;
    }

    #body {
        height: 1fr;
        margin-top: 0;
    }

    #results {
        width: 42%;
        height: 1fr;
        min-height: 8;
        background: #ffd6e3;
        color: #4c3140;
        border: round #d66a91;
        margin: 0 1 1 2;
        padding: 1 0;
    }

    #related_terms {
        width: 1fr;
        margin: 0;
        color: #fff5f8;
        text-style: bold;
        height: auto;
    }

    #preview {
        width: 58%;
        height: 1fr;
        background: #ffd6e3;
        color: #4c3140;
        border: round #d66a91;
        margin: 0 2 1 1;
        scrollbar-gutter: stable;
    }

    #preview_content {
        padding: 1;
        color: #4c3140;
        width: 100%;
    }

    #search_controls {
        height: auto;
        margin: 1 2 1 2;
    }

    #search_controls > Button {
        margin: 0 0 0 1;
        min-width: 5;
    }

    #results_footer {
        height: auto;
        margin: 0 2 1 2;
    }

    #page_info {
        margin: 0 1 0 1;
        color: #6d4458;
        min-width: 10;
        content-align: center middle;
    }

    #root_list {
        background: #ffd6e3;
        color: #4c3140;
        border: round #d66a91;
        margin: 0 2 1 2;
    }

    #results:focus,
    #root_list:focus {
        background: #ffd6e3 !important;
        border: round #c94f7c !important;
    }

    #root_help {
        margin: 0 2 1 2;
        color: #6d4458;
    }

    #stats_panel {
        background: #ffd6e3;
        color: #4c3140;
        border: round #d66a91;
        margin: 1 2 1 2;
        padding: 1 2;
    }

    Button {
        background: #ffcade;
        color: #4c3140;
        border: round #d66a91;
        margin: 0 1 1 2;
    }

    Button:hover,
    Button:focus {
        background: #ffb7cb !important;
        color: #4c3140 !important;
        border: round #c94f7c !important;
    }

    #clear_index {
        background: #ff9fbc;
        border: round #c94f7c;
    }

    ListView > ListItem {
        background: #ffd6e3;
        color: #4c3140;
        margin: 0 1 1 1;
        padding: 1 2;
        border: tall #e28bab;
        link-style: underline;
        link-style-hover: bold underline;
    }

    ListView > ListItem.-highlight,
    ListView:focus > ListItem.-highlight {
        background: #ffb7cb;
        color: #4c3140;
        border: tall #c94f7c;
        text-style: bold;
    }

    .result_title {
        color: #5f6064;
        text-style: bold;
    }

    .result_meta {
        color: #8a8a90;
    }

    .preview_title {
        color: #5f6064;
        text-style: bold;
    }

    .preview_meta {
        color: #8a8a90;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("/", "focus_query", "Search"),
    ]

    DEFAULT_INCLUDE_GLOBS = ["**/*.txt", "**/*.md", "**/*.pdf"]
    DEFAULT_EXCLUDE_GLOBS = ["**/.git/**", "**/node_modules/**", "**/.DS_Store"]

    def __init__(self) -> None:
        super().__init__()
        self.settings, self.metadata, self.backend, self.indexer, self.sync_service = build_runtime()
        normalized_roots = [self._normalize_root_globs(root) for root in self.settings.roots]
        self.settings = self.settings.model_copy(update={"roots": normalized_roots})
        self.metadata.set_active_roots(normalized_roots)
        self.backend.update_roots(normalized_roots)
        self.sync_service.reload_roots(self.settings)
        self.sync_service.on_state_change = self._handle_index_state_change
        self.hits: list[dict[str, object]] = []
        self.related_terms: list[str] = []
        self.current_query: str = ""
        self.current_page: int = 1
        self.total_hits: int = 0
        self.page_size: int = 10
        self.current_query_terms: list[str] = []
        self.root_rows: list[RootConfig] = list(self.settings.roots)

    def compose(self) -> ComposeResult:
        yield Static("Local Search Engine", id="titlebar")
        yield Static("", id="status")
        with Horizontal(id="tabbar"):
            yield Button("🔎 Search", id="show_search", classes="tab_button -active")
            yield Button("📁 Whitelist", id="show_whitelist", classes="tab_button")
            yield Button("📊 Stats", id="show_stats", classes="tab_button")
        with ContentSwitcher(initial="search_pane"):
            with Vertical(id="search_pane", classes="pane"):
                with Horizontal(id="search_controls"):
                    yield Input(
                        placeholder="Search text, filenames, or paths.",
                        id="query",
                    )
                    yield Button("📋", id="copy_snippet")
                with Horizontal(id="body"):
                    yield ListView(id="results")
                    with VerticalScroll(id="preview"):
                        yield Static(
                            "No whitelist configured.\n\nOpen the Whitelist tab to add one or more directories.",
                            id="preview_content",
                        )
                with Horizontal(id="results_footer"):
                    yield Static("Related terms will appear here after a search.", id="related_terms")
                    yield Button("◀", id="prev_page")
                    yield Static("Page 0/0", id="page_info")
                    yield Button("▶", id="next_page")
            with Vertical(id="whitelist_pane", classes="pane"):
                yield Input(
                    placeholder="Add absolute host path, e.g. /Users/mohammed/Code/Thesis/articles",
                    id="root_input",
                )
                with Horizontal():
                    yield Button("Add To Whitelist", id="add_root")
                    yield Button("Remove Selected", id="remove_root")
                yield ListView(id="root_list")
                yield Static(
                    "Whitelist entries persist across sessions. Edit them here.",
                    id="root_help",
                )
            with Vertical(id="stats_pane", classes="pane"):
                yield Button("Clear Index", id="clear_index")
                yield Static("", id="stats_panel")

    async def on_mount(self) -> None:
        self.register_theme(self.PINK_THEME)
        self.theme = self.PINK_THEME.name
        await self.sync_service.start()
        self.refresh_root_list()
        self.refresh_status()
        self.refresh_stats()
        self.refresh_pagination()

    async def on_unmount(self) -> None:
        await self.sync_service.stop()

    def action_focus_query(self) -> None:
        self.query_one("#query", Input).focus()

    @staticmethod
    def _file_url(path: str, page_number: int | None = None) -> str:
        file_url = f"file://{quote(path, safe='/')}"
        if page_number is not None and Path(path).suffix.casefold() == ".pdf":
            return f"{file_url}#page={page_number}"
        return file_url

    def _normalize_root_globs(self, root: RootConfig) -> RootConfig:
        include_globs = list(root.include_globs)
        if "**/*.pdf" not in include_globs:
            include_globs.append("**/*.pdf")
        return root.model_copy(update={"include_globs": include_globs})

    def _handle_index_state_change(self) -> None:
        if self._thread_id == threading.get_ident():
            self._refresh_for_index_state_change()
        else:
            self.call_from_thread(self._refresh_for_index_state_change)

    def _refresh_for_index_state_change(self) -> None:
        self.refresh_status()
        self.refresh_stats()

    def _show_pane(self, pane_id: str) -> None:
        self.query_one(ContentSwitcher).current = pane_id
        for button_id, active in {
            "#show_search": pane_id == "search_pane",
            "#show_whitelist": pane_id == "whitelist_pane",
            "#show_stats": pane_id == "stats_pane",
        }.items():
            self.query_one(button_id, Button).set_class(active, "-active")

    @on(Button.Pressed, "#show_search")
    def show_search_tab(self) -> None:
        self._show_pane("search_pane")

    @on(Button.Pressed, "#show_whitelist")
    def show_whitelist_tab(self) -> None:
        self._show_pane("whitelist_pane")

    @on(Button.Pressed, "#show_stats")
    def show_stats_tab(self) -> None:
        self._show_pane("stats_pane")

    @on(Input.Submitted, "#query")
    async def run_search(self, event: Input.Submitted) -> None:
        self.current_query = event.value.strip()
        self.current_page = 1
        self.current_query_terms = tokenize_terms(self.current_query)
        if self.current_query:
            self.sync_service.trigger_refresh()
            self.refresh_status()
        self._run_current_search()

    @on(Button.Pressed, "#prev_page")
    def previous_page(self) -> None:
        if self.current_page <= 1 or not self.current_query:
            return
        self.current_page -= 1
        self._run_current_search()

    @on(Button.Pressed, "#next_page")
    def next_page(self) -> None:
        if not self.current_query:
            return
        max_page = max((self.total_hits + self.page_size - 1) // self.page_size, 1)
        if self.current_page >= max_page:
            return
        self.current_page += 1
        self._run_current_search()

    def _run_current_search(self) -> None:
        query = self.current_query
        search_result = (
            self.backend.search(query, per_page=self.page_size, page=self.current_page, hydrate=False)
            if query
            else {"hits": [], "related_terms": [], "total_hits": 0, "page": 1, "per_page": self.page_size}
        )
        self.hits = search_result.get("hits", [])
        self.related_terms = list(search_result.get("related_terms", []))
        self.total_hits = int(search_result.get("total_hits", 0))
        self.current_page = int(search_result.get("page", self.current_page))
        results = self.query_one("#results", ListView)
        results.clear()

        start_index = (self.current_page - 1) * self.page_size
        for offset, hit in enumerate(self.hits, start=1):
            index = start_index + offset
            file_url = self._file_url(str(hit["file_path"]), int(hit["page_number"]))
            label = (
                f'[bold][link={file_url}]{index}. {hit["relative_path"]}[/link][/bold]\n'
                f'[dim]page {hit["page_number"]}  |  ({float(hit["score"]):.2f})[/dim]'
            )
            results.append(ListItem(Static(Text.from_markup(label))))
        self.refresh_related_terms()
        self.refresh_pagination()

        if self.hits:
            results.index = 0
            self.show_hit(0)
        else:
            self.query_one("#preview_content", Static).update("No results.")
            self.query_one("#preview", VerticalScroll).scroll_home(animate=False)

    @on(Button.Pressed, "#add_root")
    def add_root(self) -> None:
        raw_path = self.query_one("#root_input", Input).value.strip()
        if not raw_path:
            return
        path = Path(raw_path)
        if not path.is_absolute():
            self.query_one("#root_help", Static).update("Whitelist path must be absolute.")
            return
        if not path.exists():
            self.query_one("#root_help", Static).update("Whitelist path does not exist.")
            return
        if not path.is_dir():
            self.query_one("#root_help", Static).update("Whitelist path must be a directory.")
            return
        if any(root.path == raw_path for root in self.root_rows):
            self.query_one("#root_help", Static).update("That path is already in the whitelist.")
            return
        name = path.name or f"root-{len(self.root_rows) + 1}"
        self.root_rows.append(
            RootConfig(
                name=name,
                path=raw_path,
                include_globs=self.DEFAULT_INCLUDE_GLOBS,
                exclude_globs=self.DEFAULT_EXCLUDE_GLOBS,
            )
        )
        self.query_one("#root_input", Input).value = ""
        self._reload_roots()

    @on(Button.Pressed, "#remove_root")
    def remove_root(self) -> None:
        root_list = self.query_one("#root_list", ListView)
        if root_list.index is None or not self.root_rows:
            self.query_one("#root_help", Static).update("Select a root to remove.")
            return
        del self.root_rows[root_list.index]
        self._reload_roots()

    def _reload_roots(self) -> None:
        self.settings = self.settings.model_copy(update={"roots": list(self.root_rows)})
        self.metadata.set_active_roots(self.settings.roots)
        self.backend.update_roots(self.settings.roots)
        self.sync_service.reload_roots(self.settings)
        if self.root_rows:
            self.sync_service.trigger_refresh()
            self.refresh_status()
        self.query_one("#results", ListView).clear()
        self.related_terms = []
        self.current_query = ""
        self.current_page = 1
        self.total_hits = 0
        self.refresh_related_terms()
        self.refresh_pagination()
        if self.root_rows:
            self.query_one("#preview_content", Static).update(
                "Configured whitelist:\n" + "\n".join(f"- {root.path}" for root in self.root_rows)
            )
        else:
            self.query_one("#preview_content", Static).update(
                "No whitelist configured.\n\nOpen the Whitelist tab to add one or more directories."
            )
        self.query_one("#preview", VerticalScroll).scroll_home(animate=False)
        self.refresh_root_list()
        self.refresh_status()
        self.refresh_stats()

    def refresh_root_list(self) -> None:
        root_list = self.query_one("#root_list", ListView)
        root_list.clear()
        for root in self.root_rows:
            root_list.append(ListItem(Static(Text.from_markup(f"[bold]{root.name}[/bold]\n{root.path}"))))
        self.query_one("#root_help", Static).update(
            "Whitelist entries persist across sessions. Edit them here."
        )

    @on(ListView.Highlighted, "#results")
    def show_selected(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.list_view.index is None:
            return
        self.show_hit(event.list_view.index)

    def show_hit(self, index: int) -> None:
        hit = self.hits[index]
        _, _, _, page_text = load_page_number(
            Path(str(hit["file_path"])),
            int(hit["page_number"]),
        )
        preview = escape(page_text) if page_text else "No page preview available."
        for term in sorted(set(self.current_query_terms), key=len, reverse=True):
            preview = re.sub(rf"(?i)({re.escape(term)})", r"[reverse]\1[/reverse]", preview)
        self.query_one("#preview_content", Static).update(Text.from_markup(preview))
        self.query_one("#preview", VerticalScroll).scroll_home(animate=False)

    @on(Button.Pressed, "#clear_index")
    def clear_index(self) -> None:
        self.metadata.clear(self.settings.roots)
        self.hits = []
        self.related_terms = []
        self.current_page = 1
        self.total_hits = 0
        self.query_one("#results", ListView).clear()
        self.refresh_related_terms()
        self.refresh_pagination()
        self.query_one("#preview_content", Static).update("Index cleared.")
        self.query_one("#preview", VerticalScroll).scroll_home(animate=False)
        self.refresh_status()
        self.refresh_stats()

    @on(Button.Pressed, "#copy_snippet")
    def copy_snippet(self) -> None:
        results = self.query_one("#results", ListView)
        if results.index is None or not self.hits:
            self.query_one("#status", Static).update("No selected result to copy.")
            return
        snippet = str(self.hits[results.index].get("snippet", ""))
        if not snippet:
            snippet = self.backend.snippet_for_location(
                str(self.hits[results.index]["file_path"]),
                int(self.hits[results.index]["page_number"]),
                self.current_query_terms,
            )
            self.hits[results.index]["snippet"] = snippet
        plain_snippet = re.sub(r"</?mark>", "", snippet)
        self.copy_to_clipboard(plain_snippet)
        self.refresh_status(message="Snippet copied.")

    def refresh_status(self, message: str | None = None) -> None:
        status = "indexing" if self.sync_service.is_indexing else "ready"
        try:
            result_count = self.total_hits if self.current_query else len(self.hits)
            line = (
                f'{self.metadata.total_file_count(self.settings.roots)} files | '
                f'{self.metadata.unique_hash_count(self.settings.roots)} hashes | '
                f'{result_count} results | '
                f'{len(self.root_rows)} whitelist entries | '
                f'status: {status}'
            )
            if self.sync_service.last_error:
                line = f"{line} | error: {self.sync_service.last_error}"
            if message:
                line = f"{line} | {message}"
            self.query_one("#status", Static).update(line)
        except sqlite3.OperationalError as exc:
            self.query_one("#status", Static).update(
                f'{len(self.root_rows)} whitelist entries | status: {status} | db unavailable: {exc}'
            )

    def refresh_stats(self) -> None:
        try:
            db_size = self.metadata.database_size_bytes(self.settings.roots)
            table_stats = self.metadata.table_stats(self.settings.roots)
            lines = [
                "Index Stats",
                "",
                f"Database size: {self._format_bytes(db_size)}",
                f"Indexed files: {self.metadata.total_file_count(self.settings.roots)}",
                f"Unique content hashes: {self.metadata.unique_hash_count(self.settings.roots)}",
                f"Unique terms: {self.metadata.term_count(self.settings.roots)}",
                f"Term-document links: {self.metadata.term_link_count(self.settings.roots)}",
                "",
                "Table sizes:",
            ]
            for item in table_stats:
                size_label = self._format_bytes(int(item["size_bytes"])) if item["size_bytes"] is not None else "n/a"
                lines.append(f'- {item["table"]}: {item["rows"]} rows | {size_label}')
            lines.extend(
                [
                    "",
                    "Configured whitelist:",
                ]
            )
            if self.root_rows:
                lines.extend(f"- {root.path}" for root in self.root_rows)
            else:
                lines.append("- none")
            self.query_one("#stats_panel", Static).update("\n".join(lines))
        except sqlite3.OperationalError as exc:
            self.query_one("#stats_panel", Static).update(f"Index Stats\n\nDatabase temporarily unavailable: {exc}")

    def refresh_related_terms(self) -> None:
        if self.related_terms:
            self.query_one("#related_terms", Static).update(
                "Related terms: " + ", ".join(self.related_terms)
            )
            return
        self.query_one("#related_terms", Static).update("Related terms will appear here after a search.")

    def refresh_pagination(self) -> None:
        max_page = max((self.total_hits + self.page_size - 1) // self.page_size, 1)
        self.query_one("#page_info", Static).update(f"Page {self.current_page}/{max_page}")
        self.query_one("#prev_page", Button).disabled = self.current_page <= 1 or self.total_hits == 0
        self.query_one("#next_page", Button).disabled = self.current_page >= max_page or self.total_hits == 0

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        value = float(num_bytes)
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        return f"{value:.1f} {unit}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Local search engine TUI")
    parser.add_argument("--query", help="Run a single query and print results without starting the TUI.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON for --query mode.")
    args = parser.parse_args()

    if args.query:
        _, _, backend, indexer, _ = build_runtime()
        backend.bootstrap()
        indexer.initial_scan()
        hits = backend.search(args.query).get("hits", [])
        if args.json:
            def compact_snippet(snippet: str) -> str:
                plain = re.sub(r"</?mark>", "", snippet)
                lines = [re.sub(r"\s+", " ", line).strip() for line in plain.splitlines()]
                return " ".join(line for line in lines if line)

            grouped_hits: dict[str, list[dict[str, object]]] = {}
            for hit in hits:
                relative_path = str(hit["relative_path"])
                grouped_hits.setdefault(relative_path, []).append(
                    {
                        "page_number": hit["page_number"],
                        "snippet": compact_snippet(str(hit["snippet"])),
                    }
                )

            json_hits = [
                {
                    "relative_path": relative_path,
                    "hits": group,
                }
                for relative_path, group in grouped_hits.items()
            ]
            print(json.dumps(json_hits, indent=2))
            return
        for hit in hits:
            print(
                f'{hit["relative_path"]} | page {hit["page_number"]} | '
                f'score {float(hit["score"]):.2f}'
            )
            print(hit["snippet"])
            print()
        return

    app = SearchTUI()
    app.run()


if __name__ == "__main__":
    main()
