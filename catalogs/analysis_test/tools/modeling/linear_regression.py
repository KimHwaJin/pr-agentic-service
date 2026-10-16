def linear_regression(
    data, target_column: str, feature_columns: list | None = None
) -> dict:
    """선형회귀(OLS)로 목표 컬럼과 변수들의 관계를 추정합니다.

    범주형 변수는 one-hot(첫 범주 기준)으로 바꿔 넣습니다.

    Args:
        data: 입력 DataFrame
        target_column: 수치형 목표 컬럼
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)

    Returns:
        {"coefficients": dict, "p_values": dict, "r2": float, "rows": int}
    """
    import pandas as pd
    import statsmodels.api as sm

    skip = {target_column, "alias_lot_id", "wf_id", "x", "y", "timestamp"}
    features = feature_columns or [c for c in data.columns if c not in skip]
    frame = data[features + [target_column]].dropna()
    X = sm.add_constant(
        pd.get_dummies(frame[features], drop_first=True).astype(float)
    )
    model = sm.OLS(frame[target_column].astype(float), X).fit()
    out = {
        "coefficients": {
            k: round(float(v), 4) for k, v in model.params.items()
        },
        "p_values": {k: float(v) for k, v in model.pvalues.items()},
        "r2": round(float(model.rsquared), 4),
        "rows": len(frame),
    }
    print(f"linear_regression: r2={out['r2']} coef={out['coefficients']}")
    return out
