"""Search screen: collection keyword search backed by the CMR API."""

import threading
import tkinter as tk
import tkinter.ttk as ttk

import earthaccess
import requests
from earthaccess.daac import find_provider

try:
    import customtkinter as ctk
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False
    ctk = None

from . import theme


_DAACS = [
    "Any DAAC", "NSIDC", "GHRCDAAC", "PODAAC", "ASF",
    "ORNLDAAC", "LPDAAC", "GES_DISC", "OBDAAC", "SEDAC", "LAADS", "ASDC",
]

# Maps DAAC labels to their UAT CMR provider IDs.
# Each entry is a list because a DAAC may have both on-prem and cloud providers in UAT.
_UAT_DAAC_PROVIDERS: dict[str, list[str]] = {
    "NSIDC":    ["NSIDC_TS1", "NSIDC_CUAT"],
    "GHRCDAAC": ["GHRC", "GHRC_CLOUD"],
    "PODAAC":   ["PODAAC", "POCLOUD"],
    "ASF":      ["ASF"],
    "ORNLDAAC": ["ORNL_DAAC", "ORNL_CLOUD"],
    "LPDAAC":   ["LPDAAC_TS1", "LPCLOUDUAT"],
    "GES_DISC": ["GES_DISC", "GESDISCCLD"],
    "OBDAAC":   ["OB_DAAC", "OB_CLOUD"],
    "SEDAC":    ["SEDAC"],
    "LAADS":    ["LAADS", "LAADSCDUAT"],
    "ASDC":     ["LARC_ASDC", "LARC_CLOUD"],
}


class SearchScreen(tk.Frame if not _HAS_CTK else ctk.CTkFrame):
    """Collection search with DAAC filter and paginated Treeview results."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._collections = []
        self._build()

    def _build(self):
        theme.setup_ttk_style()

        top = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        top.pack(fill="x", padx=16, pady=(16, 8))

        if _HAS_CTK:
            ctk.CTkLabel(
                top, text="Search Collections", font=("Helvetica", 20, "bold")
            ).pack(side="left")
        else:
            tk.Label(
                top, text="Search Collections", font=("Helvetica", 16, "bold")
            ).pack(side="left")

        bar = ctk.CTkFrame(self, fg_color="transparent") if _HAS_CTK else tk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(0, 8))

        self._search_var = tk.StringVar()
        self._daac_var = tk.StringVar(value="Any DAAC")

        if _HAS_CTK:
            entry = ctk.CTkEntry(
                bar, textvariable=self._search_var,
                placeholder_text="Short name or keyword (e.g. ATL06)", width=340,
            )
            entry.pack(side="left", padx=(0, 8))
            self._daac_menu = ctk.CTkOptionMenu(
                bar, variable=self._daac_var, values=_DAACS, width=140
            )
            self._daac_menu.pack(side="left", padx=(0, 8))
            self._search_btn = ctk.CTkButton(
                bar, text="Search", command=self._on_search, width=100
            )
            self._search_btn.pack(side="left")
        else:
            entry = tk.Entry(bar, textvariable=self._search_var, width=40)
            entry.pack(side="left", padx=(0, 8))
            tk.OptionMenu(bar, self._daac_var, *_DAACS).pack(side="left", padx=(0, 8))
            self._search_btn = tk.Button(bar, text="Search", command=self._on_search)
            self._search_btn.pack(side="left")

        entry.bind("<Return>", lambda _: self._on_search())

        self._status_label = (
            ctk.CTkLabel(bar, text="", font=("Helvetica", 11))
            if _HAS_CTK
            else tk.Label(bar, text="")
        )
        self._status_label.pack(side="left", padx=(12, 0))

        table_frame = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        cols = ("short_name", "version", "concept_id", "provider")
        self._tree = ttk.Treeview(
            table_frame, columns=cols, show="headings", selectmode="browse"
        )
        headers = {
            "short_name": ("Short Name", 180),
            "version":    ("Version",     60),
            "concept_id": ("Concept ID", 250),
            "provider":   ("Provider",   140),
        }
        for col, (label, width) in headers.items():
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, minwidth=50)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self._tree.bind("<Double-1>", lambda _: self._on_select())
        self._tree.bind("<Return>", lambda _: self._on_select())
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        btm = ctk.CTkFrame(self) if _HAS_CTK else tk.Frame(self)
        btm.pack(fill="x", padx=16, pady=(0, 16))

        if _HAS_CTK:
            ctk.CTkButton(
                btm, text="Back", command=self.app.show_home, width=140
            ).pack(side="left")
            self._select_btn = ctk.CTkButton(
                btm, text="Select Collection",
                command=self._on_select, state="disabled", width=180,
            )
            self._select_btn.pack(side="right")
        else:
            tk.Button(btm, text="Back", command=self.app.show_home).pack(side="left")
            self._select_btn = tk.Button(
                btm, text="Select", command=self._on_select, state="disabled"
            )
            self._select_btn.pack(side="right")

    # ── search ────────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self._search_var.get().strip()
        if not query:
            return
        self._search_btn.configure(state="disabled")
        if _HAS_CTK:
            self._status_label.configure(
                text="Searching...", text_color=theme.TEXT_STATUS
            )
        else:
            self._status_label.configure(text="Searching...")
        for row in self._tree.get_children():
            self._tree.delete(row)
        daac = self._daac_var.get()
        daac = None if daac == "Any DAAC" else daac
        threading.Thread(
            target=self._search_worker, args=(query, daac), daemon=True
        ).start()

    def _search_worker(self, query: str, daac: str | None):
        """Fetch matching collections from CMR; runs on a background thread."""
        try:
            if getattr(self.app, "env", "OPS") == "UAT":
                results = self._search_uat(query, daac)
            else:
                results = self._search_ops(query, daac)
            self.after(0, lambda: self._populate(results))
        except Exception as exc:
            self.after(
                0,
                lambda msg=str(exc): self._set_status(f"Error: {msg}", error=True),
            )
            self.after(0, lambda: self._search_btn.configure(state="normal"))

    def _search_ops(self, query: str, daac: str | None) -> list:
        """Search OPS CMR using earthaccess."""
        base = {"has_granules": True, "count": 20}
        if daac:
            # Each DAAC has separate on-prem and cloud providers — search both
            # so collections like EMIT (LPCLOUD) aren't missed when filtering LPDAAC.
            on_prem = find_provider(daac, False)
            cloud = find_provider(daac, True)
            providers = list(dict.fromkeys([on_prem, cloud]))
            seen: set[str] = set()
            results = []
            for provider in providers:
                kw = {**base, "provider": provider}
                batch = earthaccess.search_datasets(short_name=query, **kw)
                if not batch:
                    batch = earthaccess.search_datasets(keyword=query, **kw)
                for col in batch:
                    cid = col.get("meta", {}).get("concept-id", "")
                    if cid not in seen:
                        seen.add(cid)
                        results.append(col)
            return results
        results = earthaccess.search_datasets(short_name=query, **base)
        if not results:
            results = earthaccess.search_datasets(keyword=query, **base)
        return results

    def _search_uat(self, query: str, daac: str | None) -> list:
        """Search UAT CMR directly via requests (earthaccess does not support UAT)."""
        token = getattr(self.app, "uat_token", None) or ""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        base_url = "https://cmr.uat.earthdata.nasa.gov/search/collections.umm_json"
        params = {"has_granules": "true", "page_size": 20}

        if daac:
            providers = _UAT_DAAC_PROVIDERS.get(daac, [daac])
            seen: set[str] = set()
            all_items: list[dict] = []
            for provider in providers:
                p = {**params, "provider": provider}
                for search_mode in ("short_name", "keyword"):
                    resp = requests.get(
                        base_url, params={**p, search_mode: query},
                        headers=headers, timeout=20
                    )
                    resp.raise_for_status()
                    items = resp.json().get("items", [])
                    for item in items:
                        cid = item.get("meta", {}).get("concept-id", "")
                        if cid not in seen:
                            seen.add(cid)
                            all_items.append(
                                {"umm": item.get("umm", {}), "meta": item.get("meta", {})}
                            )
                    if all_items:
                        break  # short_name hit — skip keyword fallback for this provider
            return all_items

        # No DAAC filter — try short_name then keyword across all providers.
        for search_mode in ("short_name", "keyword"):
            p = {**params, search_mode: query}
            resp = requests.get(base_url, params=p, headers=headers, timeout=20)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                return [
                    {"umm": item.get("umm", {}), "meta": item.get("meta", {})}
                    for item in items
                ]
        return []

    def _populate(self, results):
        self._collections = results
        for row in self._tree.get_children():
            self._tree.delete(row)
        for col in results:
            umm = col.get("umm", {})
            meta = col.get("meta", {})
            self._tree.insert("", "end", values=(
                umm.get("ShortName", ""),
                umm.get("Version", ""),
                meta.get("concept-id", ""),
                meta.get("provider-id", ""),
            ))
        count = len(results)
        self._set_status(
            f"{count} collection(s) found" if count else "No collections found"
        )
        self._search_btn.configure(state="normal")

    def _set_status(self, text, error=False):
        color = theme.STATUS_FAIL if error else theme.TEXT_MUTED
        if _HAS_CTK:
            self._status_label.configure(text=text, text_color=color)
        else:
            self._status_label.configure(text=text)

    def _on_tree_select(self, _event=None):
        state = "normal" if self._tree.selection() else "disabled"
        self._select_btn.configure(state=state)

    def _on_select(self):
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        if idx < len(self._collections):
            self.app.selected_collection = self._collections[idx]
            if getattr(self.app, "_inspector_entry", False):
                self.app._inspector_entry = False
                self.app.show_inspector_config()
            else:
                self.app.show_config()
