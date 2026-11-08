def correlation_test(
    data,
    x_column: str,
    y_column: str,
    method: str = "pearson",
    group_column: str | None = None,
) -> dict:
    """두 수치형 변수의 상관계수와 유의성(p-value)을 검정합니다.

    Args:
        data: 입력 DataFrame
        x_column: 첫 번째 수치형 컬럼
        y_column: 두 번째 수치형 컬럼
        method: "pearson"(선형), "spearman"(순위), "kendall"(순위)
        group_column: 그룹별로 따로 볼 때 그룹 컬럼

    Returns:
        {"results": list, "method": str, "strongest": dict}
    """
    from scipy import stats

    funcs = {
        "pearson": stats.pearsonr,
        "spearman": stats.spearmanr,
        "kendall": stats.kendalltau,
    }
    if method not in funcs:
        raise ValueError(
            f"method '{method}'은 지원하지 않습니다. "
            "pearson, spearman, kendall 중 하나를 쓰세요."
        )
    cols = [x_column, y_column] + ([group_column] if group_column else [])
    frame = data[cols].dropna()
    parts = frame.groupby(group_column) if group_column else [("all", frame)]
    results = []
    for name, part in parts:
        if len(part) < 3:
            continue
        r, p = funcs[method](part[x_column], part[y_column])
        results.append(
            {
                "group": str(name),
                "r": round(float(r), 4),
                "p_value": float(p),
                "rows": int(len(part)),
            }
        )
    if not results:
        raise ValueError("상관을 계산할 행이 3개 이상인 그룹이 없습니다.")
    strongest = max(results, key=lambda r: abs(r["r"]))
    print(f"correlation_test ({method}): {results}")
    return {"results": results, "method": method, "strongest": strongest}
