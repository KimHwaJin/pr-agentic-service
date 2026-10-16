def feature_importance(
    data,
    target_column: str,
    feature_columns: list | None = None,
    n_estimators: int = 200,
    top_n: int = 15,
) -> dict:
    """랜덤 포레스트로 목표 컬럼에 영향이 큰 변수를 순서대로 찾습니다.

    목표가 범주형(또는 0/1)이면 분류, 수치형이면 회귀로 학습합니다.
    범주형 변수는 one-hot으로 바꿔 넣습니다.

    Args:
        data: 입력 DataFrame
        target_column: 목표 컬럼 (예: "yield_pct", "PT1H.p_f")
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)
        n_estimators: 트리 수
        top_n: 돌려줄 상위 변수 수

    Returns:
        {"importances": list, "task": str, "score": float, "rows": int}
    """
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.model_selection import cross_val_score

    if target_column not in data:
        raise ValueError(f"목표 컬럼 '{target_column}'이 데이터에 없습니다.")
    skip = {target_column, "alias_lot_id", "wf_id", "x", "y", "timestamp"}
    features = feature_columns or [c for c in data.columns if c not in skip]
    frame = data[features + [target_column]].dropna()
    X = pd.get_dummies(frame[features], drop_first=False)
    y = frame[target_column]
    classify = y.dtype == object or y.nunique() <= 2
    model = (
        RandomForestClassifier(n_estimators=n_estimators, random_state=0)
        if classify
        else RandomForestRegressor(n_estimators=n_estimators, random_state=0)
    )
    score = float(cross_val_score(model, X, y, cv=3).mean())
    model.fit(X, y)
    ranked = sorted(
        zip(X.columns, model.feature_importances_, strict=True),
        key=lambda p: -p[1],
    )[:top_n]
    out = {
        "importances": [
            {"feature": str(f), "importance": round(float(v), 4)}
            for f, v in ranked
        ],
        "task": "classification" if classify else "regression",
        "score": round(score, 4),
        "rows": len(frame),
    }
    print(f"feature_importance: {out}")
    return out
