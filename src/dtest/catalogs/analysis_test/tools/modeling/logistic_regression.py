def logistic_regression(
    data,
    target_column: str,
    feature_columns: list | None = None,
    positive_value=None,
) -> dict:
    """로지스틱 회귀로 불량(0/1) 같은 이진 결과에 영향을 주는 변수를 봅니다.

    수치형 변수는 표준화해서 넣으므로, odds ratio는 "표준편차 1만큼
    커질 때 결과가 나올 odds가 몇 배가 되는가"입니다. 범주형 변수는
    one-hot(첫 범주 기준)입니다.

    Args:
        data: 입력 DataFrame
        target_column: 이진 목표 컬럼 (예: "PT1H.p_f")
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)
        positive_value: 1로 볼 값 (None이면 0/1 또는 두 값 중 큰 값)

    Returns:
        {"odds_ratios": list, "auc": float, "positive_rate": float,
         "rows": int}
    """
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    if target_column not in data:
        raise ValueError(f"목표 컬럼 '{target_column}'이 데이터에 없습니다.")
    skip = {
        target_column,
        "alias_lot_id",
        "wf_id",
        "x",
        "y",
        "timestamp",
        "PT1H.symbol",  # restates pass/fail, it would explain PT1H.p_f alone
        "PT1H.end_tm",
    }
    features = feature_columns or [c for c in data.columns if c not in skip]
    frame = data[list(features) + [target_column]].dropna()
    target = frame[target_column]
    levels = sorted(target.unique().tolist(), key=str)
    if positive_value is None:
        if len(levels) != 2:
            raise ValueError(
                f"목표 값이 {len(levels)}종류입니다. 두 값이어야 하고, "
                "아니면 positive_value를 정하세요."
            )
        positive_value = levels[-1]
    y = (target == positive_value).astype(int).to_numpy()
    if y.min() == y.max():
        raise ValueError("목표 값이 한 종류뿐이라 학습할 수 없습니다.")
    X = pd.get_dummies(frame[features], drop_first=True).astype(float)
    numeric = [c for c in X.columns if X[c].nunique() > 2]
    X[numeric] = (X[numeric] - X[numeric].mean()) / X[numeric].std(ddof=0)
    model = LogisticRegression(max_iter=2000)
    auc = float(cross_val_score(model, X, y, cv=3, scoring="roc_auc").mean())
    model.fit(X, y)
    ratios = sorted(
        (
            {
                "feature": str(c),
                "coef": round(float(b), 4),
                "odds_ratio": round(float(np.exp(b)), 4),
            }
            for c, b in zip(X.columns, model.coef_[0], strict=True)
        ),
        key=lambda r: -abs(r["coef"]),
    )
    out = {
        "odds_ratios": ratios,
        "auc": round(auc, 4),
        "positive_rate": round(float(y.mean()), 4),
        "rows": int(len(frame)),
    }
    print(f"logistic_regression: auc={out['auc']} top={ratios[:3]}")
    return out
