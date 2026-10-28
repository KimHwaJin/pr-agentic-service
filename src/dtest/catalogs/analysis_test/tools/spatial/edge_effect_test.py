def edge_effect_test(
    data,
    value_column: str,
    x_column: str = "x",
    y_column: str = "y",
    edge_ratio: float = 0.8,
    alpha: float = 0.05,
) -> dict:
    """wafer edge와 center의 값 차이가 통계적으로 유의한지 검정합니다.

    값이 0/1이면 비율 차이(카이제곱), 아니면 평균 차이(Welch t-검정)를 봅니다.

    Args:
        data: 입력 DataFrame (die 좌표 포함)
        value_column: 비교할 컬럼
        x_column: x 좌표 컬럼
        y_column: y 좌표 컬럼
        edge_ratio: edge로 볼 거리 비율 (중심~가장 먼 die 거리 대비)
        alpha: 유의수준

    Returns:
        {"edge_mean": float, "center_mean": float, "ratio": float,
         "p_value": float, "significant": bool, "method": str}
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    cx = (data[x_column].min() + data[x_column].max()) / 2
    cy = (data[y_column].min() + data[y_column].max()) / 2
    dist = np.sqrt((data[x_column] - cx) ** 2 + (data[y_column] - cy) ** 2)
    is_edge = dist / dist.max() > edge_ratio
    values = data[value_column]
    edge, center = values[is_edge].dropna(), values[~is_edge].dropna()
    binary = set(values.dropna().unique()) <= {0, 1}
    if binary:
        table = pd.crosstab(is_edge, values)
        p_value = float(stats.chi2_contingency(table).pvalue)
        method = "chi-square (비율)"
    else:
        p_value = float(stats.ttest_ind(edge, center, equal_var=False).pvalue)
        method = "Welch t-test (평균)"
    out = {
        "edge_mean": float(edge.mean()),
        "center_mean": float(center.mean()),
        "ratio": float(edge.mean() / center.mean())
        if center.mean()
        else float("inf"),
        "p_value": p_value,
        "significant": p_value < alpha,
        "method": method,
    }
    print(f"edge_effect_test: {out}")
    return out
