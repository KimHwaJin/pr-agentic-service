def compare_groups_ttest(
    data,
    value_column: str,
    group_column: str,
    group_a: str | None = None,
    group_b: str | None = None,
) -> dict:
    """두 그룹의 평균 차이를 Welch t-검정으로 비교합니다.

    Args:
        data: 입력 DataFrame
        value_column: 비교할 수치형 컬럼
        group_column: 그룹 컬럼
        group_a: 첫 그룹 값 (None이면 첫 번째 그룹)
        group_b: 둘째 그룹 값 (None이면 나머지 전체)

    Returns:
        {"statistic": float, "p_value": float, "mean_a": float,
         "mean_b": float, "group_a": str, "group_b": str}
    """
    from scipy import stats

    values = data[[group_column, value_column]].dropna()
    labels = sorted(values[group_column].astype(str).unique())
    if len(labels) < 2:
        raise ValueError(f"'{group_column}'의 그룹이 2개 미만입니다: {labels}")
    a = str(group_a) if group_a is not None else labels[0]
    keys = values[group_column].astype(str)
    in_a = keys == a
    in_b = keys == str(group_b) if group_b is not None else ~in_a
    b = str(group_b) if group_b is not None else f"{a} 외 전체"
    result = stats.ttest_ind(
        values.loc[in_a, value_column],
        values.loc[in_b, value_column],
        equal_var=False,
    )
    out = {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "mean_a": float(values.loc[in_a, value_column].mean()),
        "mean_b": float(values.loc[in_b, value_column].mean()),
        "group_a": a,
        "group_b": b,
    }
    print(f"compare_groups_ttest: {out}")
    return out
