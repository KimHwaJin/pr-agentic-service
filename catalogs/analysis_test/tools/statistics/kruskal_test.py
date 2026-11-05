def kruskal_test(data, value_column: str, group_column: str) -> dict:
    """세 그룹 이상의 분포(중앙값) 차이를 Kruskal-Wallis 검정으로 비교합니다.

    정규분포를 가정하지 않는 ANOVA 대안입니다.

    Args:
        data: 입력 DataFrame
        value_column: 비교할 수치형 컬럼
        group_column: 그룹 컬럼

    Returns:
        {"statistic": float, "p_value": float, "group_medians": dict,
         "highest_group": str}
    """
    import numpy as np
    from scipy import stats

    values = data[[group_column, value_column]].dropna()
    groups = {
        str(k): g[value_column].to_numpy()
        for k, g in values.groupby(group_column)
    }
    if len(groups) < 3:
        raise ValueError(
            f"그룹이 {len(groups)}개입니다. Kruskal-Wallis는 3개 이상일 때 "
            "쓰세요 (2개면 compare_groups_nonparametric)."
        )
    result = stats.kruskal(*groups.values())
    medians = {k: float(np.median(v)) for k, v in groups.items()}
    out = {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "group_medians": medians,
        "highest_group": max(medians, key=medians.__getitem__),
    }
    print(f"kruskal_test: {out}")
    return out
