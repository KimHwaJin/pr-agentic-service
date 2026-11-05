def linear_regression(
    data, target_column: str, feature_columns: list | None = None
) -> dict:
    """선형회귀(OLS)로 목표 컬럼과 변수들의 관계를 추정합니다.

    범주형 변수는 one-hot(첫 범주 기준)으로 바꿔 넣습니다. 계수의 표준오차와
    p-value는 일반 OLS 공식(t 분포)으로 계산합니다.

    Args:
        data: 입력 DataFrame
        target_column: 수치형 목표 컬럼
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)

    Returns:
        {"coefficients": dict, "std_errors": dict, "p_values": dict,
         "r2": float, "adj_r2": float, "rows": int}
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    if target_column not in data:
        raise ValueError(f"목표 컬럼 '{target_column}'이 데이터에 없습니다.")
    skip = {target_column, "alias_lot_id", "wf_id", "x", "y", "timestamp"}
    features = feature_columns or [c for c in data.columns if c not in skip]
    frame = data[list(features) + [target_column]].dropna()
    X = pd.get_dummies(frame[features], drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    y = frame[target_column].astype(float).to_numpy()
    n, k = X.shape
    if n <= k:
        raise ValueError(
            f"행({n})이 변수 수({k})보다 많아야 합니다. 변수를 줄이세요."
        )
    A = X.to_numpy()
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ beta
    dof = n - k
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.pinv(A.T @ A)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, beta / se, np.inf)
    p = 2 * stats.t.sf(np.abs(t), dof)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(resid @ resid) / ss_tot if ss_tot else 0.0
    adj = 1 - (1 - r2) * (n - 1) / dof
    names = list(X.columns)
    out = {
        "coefficients": {
            c: round(float(v), 4) for c, v in zip(names, beta, strict=True)
        },
        "std_errors": {
            c: round(float(v), 4) for c, v in zip(names, se, strict=True)
        },
        "p_values": {c: float(v) for c, v in zip(names, p, strict=True)},
        "r2": round(float(r2), 4),
        "adj_r2": round(float(adj), 4),
        "rows": int(n),
    }
    print(f"linear_regression: r2={out['r2']} coef={out['coefficients']}")
    return out
