def resample_series(
    data,
    time_column: str = "timestamp",
    value_columns: list | None = None,
    rule: str = "1D",
    group_column: str | None = None,
    agg: str = "mean",
) -> dict:
    """시계열을 일정 간격으로 묶어 집계합니다.

    Args:
        data: 입력 DataFrame (시간 컬럼 포함)
        time_column: 시간 컬럼
        value_columns: 집계할 컬럼 (None이면 수치형 전부)
        rule: 묶는 간격 (예: "1h", "1D", "1W")
        group_column: 함께 묶을 그룹 컬럼 (예: "eqp_id")
        agg: "mean" | "median" | "max" | "min"

    Returns:
        {"data": pandas.DataFrame, "shape": list}
    """
    import pandas as pd

    if agg not in {"mean", "median", "max", "min"}:
        raise ValueError(
            f"agg '{agg}'은 지원하지 않습니다 (mean, median, max, min)."
        )
    frame = data.copy()
    frame[time_column] = pd.to_datetime(frame[time_column])
    values = value_columns or list(frame.select_dtypes("number").columns)
    keys = [group_column] if group_column else []
    out = (
        frame.set_index(time_column)
        .groupby(keys + [pd.Grouper(freq=rule)])[values]
        .agg(agg)
        .reset_index()
    )
    print(f"resample_series: rule={rule} -> {out.shape}")
    return {"data": out, "shape": list(out.shape)}
