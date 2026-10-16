def clean_data(
    data,
    drop_duplicates: bool = True,
    missing: str = "drop",
    clip_ranges: dict | None = None,
    key_columns: list | None = None,
) -> dict:
    """중복·결측·범위 위반을 정리한 데이터를 만듭니다.

    Args:
        data: 입력 DataFrame
        drop_duplicates: 중복 행 제거 여부
        missing: 결측 처리. "drop"(행 제거) | "fill_median"(중앙값) | "keep"
        clip_ranges: {"컬럼": [최소, 최대]}. 범위를 벗어난 행을 제거
        key_columns: 중복 판단 기준 컬럼 (None이면 모든 컬럼)

    Returns:
        {"data": pandas.DataFrame, "removed_rows": int, "shape": list}
    """
    if missing not in {"drop", "fill_median", "keep"}:
        raise ValueError(
            f"missing '{missing}'은 지원하지 않습니다. "
            "drop, fill_median, keep 중 하나를 쓰세요."
        )
    frame = data.copy()
    before = len(frame)
    if drop_duplicates:
        frame = frame.drop_duplicates(subset=key_columns)
    if missing == "drop":
        frame = frame.dropna()
    elif missing == "fill_median":
        numeric = frame.select_dtypes("number").columns
        frame[numeric] = frame[numeric].fillna(frame[numeric].median())
    for column, (low, high) in (clip_ranges or {}).items():
        if low is not None:
            frame = frame[frame[column] >= low]
        if high is not None:
            frame = frame[frame[column] <= high]
    frame = frame.reset_index(drop=True)
    removed = before - len(frame)
    print(f"clean_data: {before} -> {len(frame)} rows (removed {removed})")
    return {"data": frame, "removed_rows": removed, "shape": list(frame.shape)}
