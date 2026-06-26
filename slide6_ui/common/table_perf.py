"""table_perf.py — helpers for populating QTableWidget without UI freezes.

A column set to ``QHeaderView.ResizeToContents`` re-measures EVERY row's width
on each ``setItem``/``setCellWidget`` call. Populating N rows is therefore
O(N^2): with a few hundred rows it freezes the main thread for seconds (this was
the cause of the process / file-browser / app-list / crash-list refresh stalls).

Wrap the fill loop in :func:`batch_table_fill` to switch the auto-sized columns
to ``Fixed`` and pause repaints while filling, then restore each column's prior
resize mode (one final measuring pass) and the prior repaint state — turning the
populate cost back into O(N).

CONVENTION (team rule): any QTableWidget that has at least one
``QHeaderView.ResizeToContents`` column AND is (re)populated in a loop MUST be
filled through :func:`batch_table_fill`. Do not call ``setRowCount`` + a
``setItem`` / ``setCellWidget`` loop with ResizeToContents active outside this
helper — that reintroduces the O(N^2) freeze. Streaming / append-only tables
should instead use ``Interactive`` column widths plus a row cap (see
``slide6_ui/syslog/oslog_panel.py``).
"""

from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtWidgets import QHeaderView, QTableWidget


@contextmanager
def batch_table_fill(table: QTableWidget, auto_cols: "tuple[int, ...]" = ()):
    """Populate ``table`` without the O(rows^2) ResizeToContents cost.

    ``auto_cols`` lists the columns that are normally ``ResizeToContents``; they
    are temporarily set to ``Fixed`` during the fill and restored afterwards.
    Use as::

        with batch_table_fill(self.table, auto_cols=(0, 2, 3)):
            self.table.setRowCount(len(rows))
            for row, item in enumerate(rows):
                ...
    """
    header = table.horizontalHeader()
    # Capture the entry state so we restore exactly what the caller had, rather
    # than hardcoding ResizeToContents / updates-enabled (which would clobber a
    # different prior mode or wrongly re-enable repaints inside a nested batch).
    prev_updates = table.updatesEnabled()
    prev_modes = [(c, header.sectionResizeMode(c)) for c in auto_cols]
    table.setUpdatesEnabled(False)
    for c in auto_cols:
        header.setSectionResizeMode(c, QHeaderView.Fixed)
    try:
        yield
    finally:
        # Restore each column's prior mode (re-triggers one measuring pass for
        # any that were ResizeToContents), then restore the prior repaint state.
        for c, mode in prev_modes:
            header.setSectionResizeMode(c, mode)
        table.setUpdatesEnabled(prev_updates)
