def chi_square_test(data, column_a: str, column_b: str) -> dict:
    """두 범주형 컬럼이 서로 독립인지 카이제곱 검정으로 확인합니다.

    Args:
        data: 입력 DataFrame
        column_a: 첫 범주형 컬럼 (예: "zone")
        column_b: 둘째 범주형 컬럼 (예: "PT1H.p_f")

    Returns:
        {"statistic": float, "p_value": float, "table": dict, "dof": int}
    """
    import pandas as pd
    from scipy import stats

    for column in (column_a, column_b):
        if column not in data:
            raise ValueError(f"컬럼 '{column}'이 데이터에 없습니다.")
    table = pd.crosstab(data[column_a], data[column_b])
    result = stats.chi2_contingency(table)
    out = {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "dof": int(result.dof),
        "table": {
            str(r): {str(c): int(v) for c, v in row.items()}
            for r, row in table.iterrows()
        },
    }
    print(f"chi_square_test: p={out['p_value']:.4g} table={out['table']}")
    return out
