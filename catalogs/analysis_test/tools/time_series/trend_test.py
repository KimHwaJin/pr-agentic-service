def trend_test(
    data,
    value_column: str,
    time_column: str = "timestamp",
    group_column: str | None = None,
    alpha: float = 0.05,
) -> dict:
    """값이 시간에 따라 꾸준히 오르거나 내리는지(단조 추세) 검정합니다.

    Mann-Kendall 방식(시간 순서와 값의 Kendall 순위 상관)으로 유의성을,
    Theil-Sen 기울기로 하루당 변화량을 계산합니다. 이상치에 강합니다.

    Args:
        data: 입력 DataFrame
        value_column: 대상 수치형 컬럼
        time_column: 시간 컬럼
        group_column: 그룹 컬럼 (예: "eqp_id")
        alpha: 유의수준

    Returns:
        {"trends": list, "has_trend": bool}
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    trends = []
    parts = data.groupby(group_column) if group_column else [("all", data)]
    for name, part in parts:
        part = part[[time_column, value_column]].dropna()
        part = part.sort_values(time_column)
        if len(part) < 10:
            continue
        t = part[time_column]
        if pd.api.types.is_datetime64_any_dtype(t):
            x = ((t - t.iloc[0]).dt.total_seconds() / 86400).to_numpy()
            unit = "per_day"
        else:
            x = np.arange(len(part), dtype=float)
            unit = "per_row"
        y = part[value_column].to_numpy(dtype=float)
        tau, p = stats.kendalltau(x, y)
        slope, _, low, high = stats.theilslopes(y, x)
        trends.append(
            {
                "group": str(name),
                "tau": round(float(tau), 4),
                "p_value": float(p),
                "slope": float(slope),
                "slope_ci": [float(low), float(high)],
                "slope_unit": unit,
                "direction": ("증가" if tau > 0 else "감소")
                if p < alpha
                else "없음",
            }
        )
    print(f"trend_test: {trends}")
    return {
        "trends": trends,
        "has_trend": any(r["direction"] != "없음" for r in trends),
    }
