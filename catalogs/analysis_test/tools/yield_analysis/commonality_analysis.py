def commonality_analysis(
    data,
    target_column: str,
    factor_columns: list | None = None,
    alpha: float = 0.05,
) -> dict:
    """수율·불량과 관련 있는 공통 요인(설비, 챔버, 공정 경로 등)을 찾습니다.

    범주형 요인마다 수준별 목표 값을 비교해 유의성 순으로 정렬합니다.
    목표가 0/1(불량 여부)이면 카이제곱 검정, 수치형(수율 등)이면
    Kruskal-Wallis 검정을 씁니다.

    Args:
        data: 입력 DataFrame
        target_column: 목표 컬럼 (예: "yield_pct", "PT1H.p_f")
        factor_columns: 볼 범주형 요인 (None이면 값 종류가 2~30개인
            문자열 컬럼 전부, 키 컬럼 제외)
        alpha: 유의수준

    Returns:
        {"factors": list, "top_factor": str | None, "significant": list}
    """
    import pandas as pd
    from scipy import stats

    if target_column not in data:
        raise ValueError(f"목표 컬럼 '{target_column}'이 데이터에 없습니다.")
    keys = {target_column, "alias_lot_id", "wf_id", "x", "y", "timestamp"}
    if factor_columns is None:
        factor_columns = [
            c
            for c in data.columns
            if c not in keys
            and not pd.api.types.is_numeric_dtype(data[c])
            and 2 <= data[c].nunique() <= 30
        ]
    if not factor_columns:
        raise ValueError(
            "비교할 범주형 요인이 없습니다. factor_columns를 정하세요."
        )
    target = data[target_column]
    binary = target.dropna().nunique() <= 2
    factors = []
    for factor in factor_columns:
        frame = data[[factor, target_column]].dropna()
        if frame[factor].nunique() < 2:
            continue
        if binary:
            table = pd.crosstab(frame[factor], frame[target_column])
            if table.shape[1] < 2:
                continue
            p = float(stats.chi2_contingency(table).pvalue)
            test = "chi_square"
        else:
            groups = [g[target_column] for _, g in frame.groupby(factor)]
            p = float(stats.kruskal(*groups).pvalue)
            test = "kruskal"
        levels = frame.groupby(factor)[target_column].mean()
        worst = levels.idxmax() if binary else levels.idxmin()
        best = levels.idxmin() if binary else levels.idxmax()
        factors.append(
            {
                "factor": factor,
                "test": test,
                "p_value": p,
                "significant": p < alpha,
                "worst_level": str(worst),
                "best_level": str(best),
                "gap": round(float(abs(levels[worst] - levels[best])), 4),
                "levels": {
                    str(k): round(float(v), 4) for k, v in levels.items()
                },
            }
        )
    factors.sort(key=lambda r: r["p_value"])
    significant = [r["factor"] for r in factors if r["significant"]]
    out = {
        "factors": factors,
        "top_factor": factors[0]["factor"] if significant else None,
        "significant": significant,
    }
    print(
        "commonality_analysis: "
        + ", ".join(
            f"{r['factor']} p={r['p_value']:.3g} worst={r['worst_level']}"
            for r in factors
        )
    )
    return out
