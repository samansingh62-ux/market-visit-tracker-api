"""Management Excel report for saved TL and SS EOD remarks."""
import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = ["Date", "Submitted By", "Role", "Retailer Code", "Retailer",
           "TL", "SS", "RDS", "Remarks", "Created At", "Updated At"]
KEYS = ["remark_date", "submitted_by", "submitted_role", "retailer_code",
        "retailer_name", "tl", "ss", "rds", "remark", "created_at", "updated_at"]


def build_eod_workbook(rows, start, end, coverage=None):
    wb = Workbook()
    summary = wb.active
    summary.title = "Report Summary"
    summary.append(["EOD Remarks — TL and SS", "Value"])
    summary.append(["From", start.isoformat()])
    summary.append(["To", end.isoformat()])
    summary.append(["TL remarks", sum(r.get("submitted_role") == "TL" for r in rows)])
    summary.append(["SS remarks", sum(r.get("submitted_role") == "SS" for r in rows)])
    summary.append(["Coverage", "All saved TL and SS remarks; no hierarchy filter"])
    for role in ("TL", "SS"):
        names = {r["submitted_by"] for r in rows if r.get("submitted_role") == role}
        summary.append([role + "s who submitted remarks", len(names)])
        summary.append([role + " submitter names", ", ".join(sorted(names)) or "None"])
        if coverage is not None:
            accounts = {r["name"] for r in coverage if r["role"] == role}
            summary.append(["Active " + role + " accounts", len(accounts)])
            summary.append([role + "s with no remarks in period", len(accounts - names)])
    summary.append(["Eligibility rule", "FTD sales = 0 or FTD sales < 60% of Required/Day"])
    summary.append(["Required/Day", "Remaining monthly target divided by remaining days, including the report date"])
    summary.append(["Note", "Eligibility is recalculated for each date using current alignment and available monthly targets. Unavailable sales are not counted as zero."])
    if coverage is not None:
        summary.append([])
        summary.append(["Daily non-submitters", "Role", "Name", "Eligible retailers", "Remarks submitted", "Remarks pending", "Status"])
        for item in sorted(coverage, key=lambda r: (r["date"], r["role"], r["name"])):
            if item["submitted_count"]:
                continue
            eligible = item["eligible_count"]
            summary.append([item["date"], item["role"], item["name"],
                            eligible if eligible is not None else "Unavailable",
                            0, item["pending_count"] if eligible is not None else "Unavailable",
                            "Sales unavailable" if eligible is None else ("No eligible retailers" if eligible == 0 else "Not submitted")])
        ws = wb.create_sheet("Daily Submission Status")
        ws.append(["Date", "Role", "Name", "Eligible retailers", "Remarks submitted", "Remarks pending"])
        for item in coverage:
            ws.append([item["date"], item["role"], item["name"],
                       item["eligible_count"] if item["eligible_count"] is not None else "Unavailable",
                       item["submitted_count"], item["pending_count"] if item["pending_count"] is not None else "Unavailable"])
        for cells in ws:
            for cell in cells:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col, width in zip("ABCDEF", (14, 10, 32, 22, 22, 22)):
            ws.column_dimensions[col].width = width
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="DCEBFF")
    for row in summary:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col in "CDEFG":
        summary.column_dimensions[col].width = 26
    summary.freeze_panes = "A2"
    summary.column_dimensions["A"].width = 36
    summary.column_dimensions["B"].width = 64
    for cells in summary:
        lines = max((len(str(cell.value or "")) // max(int(summary.column_dimensions[cell.column_letter].width or 26), 1) + 1 for cell in cells), default=1)
        summary.row_dimensions[cells[0].row].height = max(20, lines * 18)
    for cell in summary[1]:
        cell.font = Font(bold=True, color="17365D")
        cell.fill = PatternFill("solid", fgColor="DCEBFF")
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
