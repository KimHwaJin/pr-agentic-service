def aggregate_by(
    data,
    group_columns: list,
    value_columns: list | None = None,
    agg: str = "mean",
) -> dict:
    """그룹별로 수치형 컬럼을 집계합니다.

    Args:
        data: 입력 DataFrame
        group_columns: 묶을 컬럼 (예: ["alias_lot_id"])
        value_columns: 집계할 컬럼 (None이면 그룹 컬럼을 뺀 수치형 전부)
        agg: "mean" | "median" | "sum" | "count" | "std" | "min" | "max"

    Returns:
        {"data": pandas.DataFrame, "shape": list}
    """
    allowed = {"mean", "median", "sum", "count", "std", "min", "max"}
    if agg not in allowed:
        raise ValueError(
            f"agg '{agg}'은 지원하지 않습니다. "
            f"{sorted(allowed)} 중 하나를 쓰세요."
        )
    missing = [c for c in group_columns if c not in data]
    if missing:
        raise ValueError(f"그룹 컬럼 {missing}이 데이터에 없습니다.")
    values = value_columns or [
        c
        for c in data.select_dtypes("number").columns
        if c not in group_columns
    ]
    frame = data.groupby(group_columns)[values].agg(agg).reset_index()
    print(f"aggregate_by: {group_columns} {agg} -> {frame.shape}")
    return {"data": frame, "shape": list(frame.shape)}
