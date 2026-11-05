def xgboost_model(
    data,
    target_column: str,
    feature_columns: list | None = None,
    n_estimators: int = 300,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    test_ratio: float = 0.25,
    top_n: int = 15,
) -> dict:
    """XGBoost(그래디언트 부스팅)로 목표를 예측하고 영향 변수를 찾습니다.

    비선형·상호작용이 있는 관계에서 랜덤 포레스트보다 정확한 경우가
    많습니다. 목표가 범주형(또는 0/1)이면 분류, 수치형이면 회귀입니다.
    떼어 둔 시험 데이터(test_ratio)로 성능을 잽니다.

    Args:
        data: 입력 DataFrame
        target_column: 목표 컬럼 (예: "yield_pct", "PT1H.p_f")
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)
        n_estimators: 트리 수
        max_depth: 트리 깊이
        learning_rate: 학습률
        test_ratio: 시험 데이터 비율
        top_n: 돌려줄 상위 변수 수

    Returns:
        {"importances": list, "task": str, "metric": str, "score": float,
         "rows": int}
    """
    import pandas as pd
    from sklearn.metrics import r2_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from xgboost import XGBClassifier, XGBRegressor

    if target_column not in data:
        raise ValueError(f"목표 컬럼 '{target_column}'이 데이터에 없습니다.")
    skip = {target_column, "alias_lot_id", "wf_id", "x", "y", "timestamp"}
    features = feature_columns or [c for c in data.columns if c not in skip]
    frame = data[list(features) + [target_column]].dropna()
    X = pd.get_dummies(frame[features], drop_first=False).astype(float)
    X.columns = [str(c).replace("[", "(").replace("]", ")") for c in X.columns]
    target = frame[target_column]
    classify = target.dtype == object or target.nunique() <= 2
    params = dict(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        random_state=0,
        n_jobs=2,
    )
    if classify:
        if target.nunique() != 2:
            raise ValueError("분류는 목표 값이 두 종류일 때만 지원합니다.")
        y = (target == sorted(target.unique(), key=str)[-1]).astype(int)
        model = XGBClassifier(eval_metric="logloss", **params)
    else:
        y = target.astype(float)
        model = XGBRegressor(**params)
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_ratio,
        random_state=0,
        stratify=y if classify else None,
    )
    model.fit(X_train, y_train)
    if classify:
        score = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
        metric = "auc"
    else:
        score = r2_score(y_test, model.predict(X_test))
        metric = "r2"
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
        "metric": metric,
        "score": round(float(score), 4),
        "rows": int(len(frame)),
    }
    print(
        f"xgboost_model: {metric}={out['score']} top={out['importances'][:3]}"
    )
    return out
