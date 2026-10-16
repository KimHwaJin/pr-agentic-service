def normality_test(
    data,
    value_column: str,
    group_column: str | None = None,
    alpha: float = 0.05,
) -> dict:
    """값이 정규분포를 따르는지 검정합니다 (그룹별 가능).

    Args:
        data: 입력 DataFrame
        value_column: 검정할 수치형 컬럼
        group_column: 그룹 컬럼 (있으면 그룹마다 검정)
        alpha: 유의수준

    Returns:
        {"is_normal": bool, "p_values": dict, "groups": int, "method": str}
    """
    from scipy import stats

    if value_column not in data:
        raise ValueError(f"컬럼 '{value_column}'이 데이터에 없습니다.")
    groups = (
        {
            str(k): g[value_column].dropna()
            for k, g in data.groupby(group_column)
        }
        if group_column
        else {"all": data[value_column].dropna()}
    )
    p_values = {}
    for name, values in groups.items():
        sample = values.sample(min(len(values), 5000), random_state=0)
        p_values[name] = float(stats.normaltest(sample).pvalue)
    normal = all(p >= alpha for p in p_values.values())
    print(f"normality_test: {value_column} normal={normal} p={p_values}")
    return {
        "is_normal": normal,
        "p_values": p_values,
        "groups": len(groups),
        "method": "D'Agostino-Pearson",
    }
