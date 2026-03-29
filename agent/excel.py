"""
agent/excel_exporter.py
Appends confirmed orders to a daily Excel sheet.
One file per day: /exports/orders/YYYY-MM-DD_orders.xlsx
Appends rows to existing file — safe to call multiple times per day.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Absolute path so Excel always lands in the same place regardless of cwd.
# Defaults to   <project_root>/exports/orders/
# Override via EXPORTS_DIR env var in .env
_HERE       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.getenv("EXPORTS_DIR", os.path.join(_HERE, "exports", "orders"))

HEADERS = [
    "Date", "Time (IST)", "Session ID", "Phone", "Caller Name",
    "Customer Type", "Product", "Weight/Size", "Qty",
    "Unit Price (₹)", "Total (₹)", "Notes",
]

# Column widths (chars)
COL_WIDTHS = [12, 12, 24, 16, 20, 14, 30, 12, 8, 14, 12, 35]

# Header fill colour
HEADER_COLOR = "1D3557"


class ExcelExporter:
    def __init__(self, exports_dir: str = EXPORTS_DIR):
        self.exports_dir = exports_dir
        os.makedirs(exports_dir, exist_ok=True)

    def _today_path(self) -> str:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        return os.path.join(self.exports_dir, f"{today}_orders.xlsx")

    def _make_header_style(self, ws):
        """Apply header row styling."""
        try:
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            header_fill  = PatternFill("solid", fgColor=HEADER_COLOR)
            header_font  = Font(bold=True, color="FFFFFF", size=11)
            thin_border  = Border(
                bottom=Side(style="thin", color="CCCCCC"),
                right =Side(style="thin", color="CCCCCC"),
            )
            center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
            left_align   = Alignment(horizontal="left",   vertical="center", wrap_text=True)

            for col_idx, (cell, width) in enumerate(zip(ws[1], COL_WIDTHS), start=1):
                cell.fill      = header_fill
                cell.font      = header_font
                cell.alignment = center_align
                cell.border    = thin_border
                ws.column_dimensions[cell.column_letter].width = width

            ws.row_dimensions[1].height = 22
            ws.freeze_panes             = "A2"
        except ImportError:
            pass  # openpyxl styles not critical

    def _data_row_style(self, row, is_alt: bool):
        """Zebra-stripe data rows."""
        try:
            from openpyxl.styles import PatternFill, Alignment, Font
            fill  = PatternFill("solid", fgColor="F0F4FF") if is_alt else PatternFill("solid", fgColor="FFFFFF")
            align = Alignment(vertical="center", wrap_text=True)
            font  = Font(size=10)
            for cell in row:
                cell.fill      = fill
                cell.alignment = align
                cell.font      = font
        except ImportError:
            pass

    def save(self, order: Dict, session_id: str = "") -> Optional[str]:
        """
        Append one order (possibly multi-item) to today's Excel file.
        Returns the file path on success, None on failure.
        """
        try:
            import openpyxl
        except ImportError:
            logger.error("[Excel] openpyxl not installed. Run: pip install openpyxl")
            return None

        path       = self._today_path()
        now        = datetime.now(IST)
        date_str   = now.strftime("%d/%m/%Y")
        time_str   = now.strftime("%I:%M %p")
        phone      = order.get("phone", "")
        name       = order.get("caller_name", "")
        ctype      = order.get("customer_type", "")
        notes      = order.get("notes", "")
        items      = order.get("items", [])

        if not items:
            logger.warning("[Excel] No items in order — skipping")
            return None

        # Load or create workbook
        if os.path.exists(path):
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            existing_rows = ws.max_row
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title        = now.strftime("%d %b %Y")
            ws.append(HEADERS)
            self._make_header_style(ws)
            existing_rows = 1

        # Append one row per line item
        for item in items:
            row_data = [
                date_str,
                time_str,
                session_id,
                phone,
                name,
                ctype,
                item.get("product_name", ""),
                item.get("weight", ""),
                item.get("quantity", 0),
                item.get("unit_price", 0.0),
                item.get("total_price", 0.0),
                notes,
            ]
            ws.append(row_data)
            is_alt = (ws.max_row % 2 == 0)
            self._data_row_style(ws[ws.max_row], is_alt)

        # Auto-filter on header row
        ws.auto_filter.ref = f"A1:{ws.cell(1, len(HEADERS)).column_letter}{ws.max_row}"

        try:
            wb.save(path)
            logger.info(f"[Excel] Saved {len(items)} item(s) → {path}")
            return path
        except Exception as e:
            logger.error(f"[Excel] Save failed: {e}")
            return None

    def save_many(self, orders: List[Dict]) -> Optional[str]:
        """Save multiple orders in one pass (batch at day end)."""
        if not orders:
            return None
        path = None
        for order in orders:
            path = self.save(order)
        return path