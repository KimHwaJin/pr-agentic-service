def tukey_posthoc(
    data, value_column: str, group_column: str, alpha: float = 0.05
) -> dict:
    """ANOVA 뒤에 어느 그룹 쌍이 다른지 Tukey HSD 사후검정으로 찾습니다.

    다중 비교를 보정한 p-value를 돌려줍니다.

    Args:
        data: 입력 DataFrame
        value_column: 비교할 수치형 컬럼
        group_column: 그룹 컬럼
        alpha: 유의수준

    Returns:
        {"pairs": list, "significant_pairs": list, "groups": int}
    """
    from scipy import stats

    values = data[[group_column, value_column]].dropna()
    groups = {
        str(k): g[value_column].to_numpy(dtype=float)
        for k, g in values.groupby(group_column)
    }
    if len(groups) < 3:
        raise ValueError(
            f"그룹이 {len(groups)}개입니다. 사후검정은 3개 이상일 때 쓰세요."
        )
    names = list(groups)
    result = stats.tukey_hsd(*groups.values())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            p = float(result.pvalue[i, j])
            pairs.append(
                {
                    "group_a": names[i],
                    "group_b": names[j],
                    "mean_diff": round(float(result.statistic[i, j]), 6),
                    "p_value": p,
                    "significant": p < alpha,
                }
            )
    pairs.sort(key=lambda r: r["p_value"])
    significant = [
        f"{r['group_a']} vs {r['group_b']}" for r in pairs if r["significant"]
    ]
    print(f"tukey_posthoc: significant={significant or '없음'}")
    return {
        "pairs": pairs,
        "significant_pairs": significant,
        "groups": len(names),
    }
