def export_parquet(
    data,
    file_name: str = "analysis_result.parquet",
    output_dir: str = "artifacts/files",
    compression: str = "snappy",
) -> dict:
    """큰 분석 데이터를 Parquet 파일로 저장합니다 (pyarrow).

    CSV·엑셀보다 작고 빠르며 컬럼 타입이 그대로 유지됩니다. 다시 읽을 때는
    pandas.read_parquet을 씁니다.

    Args:
        data: 저장할 DataFrame
        file_name: 파일 이름 (.parquet)
        output_dir: 저장 경로
        compression: 압축 방식 ("snappy", "zstd", "gzip", "none")

    Returns:
        {"file_path": str, "rows": int, "columns": int, "size_bytes": int,
         "schema": dict}
    """
    from pathlib import Path

    import pyarrow as pa
    import pyarrow.parquet as pq

    if not file_name.lower().endswith(".parquet"):
        file_name += ".parquet"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = Path(output_dir) / file_name
    frame = data.copy()
    frame.columns = [str(c) for c in frame.columns]
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(
        table, path, compression=None if compression == "none" else compression
    )
    out = {
        "file_path": str(path),
        "rows": int(table.num_rows),
        "columns": int(table.num_columns),
        "size_bytes": int(path.stat().st_size),
        "schema": {f.name: str(f.type) for f in table.schema},
    }
    print(
        f"export_parquet: {out['file_path']} rows={out['rows']} "
        f"size={out['size_bytes']}"
    )
    return out
