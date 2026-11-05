def export_excel(
    data,
    file_name: str = "analysis_result.xlsx",
    sheet_name: str = "data",
    extra_tables: dict | None = None,
    output_dir: str = "artifacts/files",
) -> dict:
    """분석 결과 표를 엑셀(.xlsx) 파일로 저장합니다 (openpyxl).

    여러 표를 한 파일의 여러 시트로 저장할 수 있습니다. 머리글은 굵게,
    열 너비는 내용에 맞추고, 첫 행을 고정합니다.

    Args:
        data: 저장할 DataFrame (첫 시트)
        file_name: 파일 이름 (.xlsx)
        sheet_name: 첫 시트 이름
        extra_tables: 더 저장할 표 {시트 이름: DataFrame 또는 dict/list}
        output_dir: 저장 경로

    Returns:
        {"file_path": str, "sheets": dict}
    """
    from pathlib import Path

    import pandas as pd
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    if not file_name.lower().endswith(".xlsx"):
        file_name += ".xlsx"
    tables = {sheet_name: data, **(extra_tables or {})}
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / file_name)
    sheets = {}
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, table in tables.items():
            if not isinstance(table, pd.DataFrame):
                table = pd.DataFrame(
                    table if isinstance(table, list) else [table]
                )
            title = str(name)[:31] or "sheet"
            for ch in "[]:*?/\\":
                title = title.replace(ch, "_")
            frame = table.copy()
            for c in frame.columns:  # Excel has no timezone-aware datetimes
                if isinstance(frame[c].dtype, pd.DatetimeTZDtype):
                    frame[c] = frame[c].dt.tz_localize(None)
            frame.to_excel(writer, sheet_name=title, index=False)
            sheet = writer.sheets[title]
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            for i, c in enumerate(frame.columns, start=1):
                sample = frame[c].astype(str).head(200).str.len()
                width = max([len(str(c)), *sample.tolist(), 6])
                sheet.column_dimensions[get_column_letter(i)].width = min(
                    width + 2, 60
                )
            sheet.freeze_panes = "A2"
            sheets[title] = list(frame.shape)
    print(f"export_excel: {path} sheets={sheets}")
    return {"file_path": path, "sheets": sheets}
