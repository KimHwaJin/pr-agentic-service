def filter_rows(
    data,
    column: str,
    values: list | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
) -> dict:
    """한 컬럼의 값 목록이나 범위로 행을 고릅니다.

    Args:
        data: 입력 DataFrame
        column: 기준 컬럼
        values: 남길 값 목록 (예: ["L1", "L3"])
        min_value: 최솟값 (이상)
        max_value: 최댓값 (이하)

    Returns:
        {"data": pandas.DataFrame, "shape": list}
    """
    if column not in data:
        raise ValueError(f"컬럼 '{column}'이 데이터에 없습니다.")
    frame = data
    if values is not None:
        frame = frame[frame[column].isin(values)]
    if min_value is not None:
        frame = frame[frame[column] >= min_value]
    if max_value is not None:
        frame = frame[frame[column] <= max_value]
    frame = frame.reset_index(drop=True)
    print(f"filter_rows: {column} -> {len(data)} -> {len(frame)} rows")
    return {"data": frame, "shape": list(frame.shape)}
