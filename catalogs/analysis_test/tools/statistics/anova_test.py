def anova_test(data, value_column: str, group_column: str) -> dict:
    """세 그룹 이상의 평균 차이를 일원분산분석(ANOVA)으로 비교합니다.

    Args:
        data: 입력 DataFrame
        value_column: 비교할 수치형 컬럼
        group_column: 그룹 컬럼

    Returns:
        {"statistic": float, "p_value": float, "group_means": dict,
         "highest_group": str}
    """
    from scipy import stats

    values = data[[group_column, value_column]].dropna()
    groups = {
        str(k): g[value_column].to_numpy()
        for k, g in values.groupby(group_column)
    }
    if len(groups) < 3:
        raise ValueError(
            f"그룹이 {len(groups)}개입니다. ANOVA는 3개 이상일 때 쓰세요 "
            "(2개면 compare_groups_ttest)."
        )
    result = stats.f_oneway(*groups.values())
    means = {k: float(v.mean()) for k, v in groups.items()}
    out = {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "group_means": means,
        "highest_group": max(means, key=means.__getitem__),
    }
    print(f"anova_test: {out}")
    return out
