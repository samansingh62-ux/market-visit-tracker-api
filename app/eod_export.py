"""Management Excel report for saved TL and SS EOD remarks."""
import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = ["Date", "Submitted By", "Role", "Retailer Code", "Retailer",
           "TL", "SS", "RDS", "Remarks", "Created At", "Updated At"]
KEYS = ["remark_date", "submitted_by", "submitted_role", "retailer_code",
        "retailer_name", "tl", "ss", "rds", "remark", "created_at", "updated_at"]


def build_eod_workbook(rows, start, end):
    wb = Workbook()
    summary = wb.active
    summary.title = "Report Summary"
    summary.append(["EOD Remarks — TL and SS", "Value"])
    summary.append(["From", start.isoformat()])
    summary.append(["To", end.isoformat()])
    summary.append(["TL remarks", sum(r.get("submitted_role") == "TL" for r in rows)])
    summary.append(["SS remarks", sum(r.get("submitted_role") == "SS" for r in rows)])
    summary.append(["Coverage", "All saved TL and SS remarks; no hierarchy filter"])
    summary.append(["Note", "Users without submitted remarks have no detail rows."])
    summary.column_dimensions["A"].width = 36
    summary.column_dimensions["B"].width = 64
    for title, role in [("All Remarks", None), ("TL Remarks", "TL"), ("SS Remarks", "SS")]:
        ws = wb.create_sheet(title)
        ws.append(HEADERS)
        for row in rows:
            if role and row.get("submitted_role") != role:
                continue
            values = [str(row.get(k) or "") for k in KEYS]
            ws.append(values)
            # Explicit strings keep user-entered remarks from becoming Excel formulas.
            for cell in ws[ws.max_row]:
                cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="DCEBFF")
            cell.font = Font(bold=True, color="17365D")
        for index, width in enumerate([14, 26, 10, 20, 34, 26, 26, 26, 70, 28, 28], 1):
            ws.column_dimensions[ws.cell(1, index).column_letter].width = width
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out
