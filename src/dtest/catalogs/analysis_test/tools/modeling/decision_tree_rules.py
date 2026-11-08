def decision_tree_rules(
    data,
    target_column: str,
    feature_columns: list | None = None,
    max_depth: int = 3,
    min_samples_leaf: int = 10,
) -> dict:
    """얕은 결정 트리로 "어떤 조건에서 결과가 나빠지나"를 규칙으로 보여줍니다.

    목표가 범주형(또는 0/1)이면 분류, 수치형이면 회귀 트리입니다.

    Args:
        data: 입력 DataFrame
        target_column: 목표 컬럼 (예: "yield_pct", "PT1H.p_f")
        feature_columns: 사용할 변수 (None이면 목표·키 컬럼을 뺀 나머지)
        max_depth: 트리 깊이 (깊을수록 규칙이 길어짐)
        min_samples_leaf: 마지막 갈래의 최소 행 수

    Returns:
        {"rules": str, "task": str, "score": float, "top_split": str,
         "rows": int}
    """
    import pandas as pd
    from sklearn.model_selection import cross_val_score
    from sklearn.tree import (
        DecisionTreeClassifier,
        DecisionTreeRegressor,
        export_text,
    )

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
    X = pd.get_dummies(frame[features], drop_first=False).astype(float)
    y = frame[target_column]
    classify = not pd.api.types.is_numeric_dtype(y) or y.nunique() <= 2
    cls = DecisionTreeClassifier if classify else DecisionTreeRegressor
    model = cls(
        max_depth=max_depth, min_samples_leaf=min_samples_leaf, random_state=0
    )
    score = float(cross_val_score(model, X, y, cv=3).mean())
    model.fit(X, y)
    rules = export_text(model, feature_names=[str(c) for c in X.columns])
    root = model.tree_.feature[0]
    top = str(X.columns[root]) if root >= 0 else ""
    out = {
        "rules": rules,
        "task": "classification" if classify else "regression",
        "score": round(score, 4),
        "top_split": top,
        "rows": int(len(frame)),
    }
    print(f"decision_tree_rules: top_split={top} score={out['score']}")
    print(rules)
    return out
