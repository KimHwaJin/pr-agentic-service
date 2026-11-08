def isolation_forest_outliers(
    data,
    columns: list | None = None,
    contamination: float = 0.01,
    top_n: int = 10,
) -> dict:
    """여러 변수를 함께 보고 이상한 행을 Isolation Forest로 찾습니다.

    한 컬럼만 보면 정상이지만 조합이 이상한 행(다변량 이상치)을 찾습니다.

    Args:
        data: 입력 DataFrame
        columns: 사용할 수치형 컬럼 (None이면 좌표를 뺀 수치형 전부)
        contamination: 이상치로 볼 비율 (0~0.5)
        top_n: 점수가 가장 이상한 행을 몇 개 돌려줄지

    Returns:
        {"data": pandas.DataFrame, "anomalies": int, "top_rows": list,
         "columns": list}
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    if not 0 < contamination <= 0.5:
        raise ValueError("contamination은 0보다 크고 0.5 이하여야 합니다.")
    numeric = [
        c for c in data.select_dtypes("number").columns if c not in {"x", "y"}
    ]
    cols = [c for c in (columns or numeric) if c in numeric]
    if not cols:
        raise ValueError("이상치를 볼 수치형 컬럼이 없습니다.")
    frame = data[cols].dropna()
    X = StandardScaler().fit_transform(frame)
    model = IsolationForest(contamination=contamination, random_state=0)
    labels = model.fit_predict(X)
    scores = -model.score_samples(X)  # larger = more unusual
    result = data.copy()
    result["anomaly_score"] = float("nan")
    result.loc[frame.index, "anomaly_score"] = scores
    result["is_anomaly"] = False
    result.loc[frame.index, "is_anomaly"] = labels == -1
    top = result.loc[frame.index].nlargest(top_n, "anomaly_score")
    top_rows = [
        {"row": int(i), "score": round(float(r["anomaly_score"]), 4)}
        | {c: float(r[c]) for c in cols}
        for i, r in top.iterrows()
    ]
    out = {
        "data": result,
        "anomalies": int((labels == -1).sum()),
        "top_rows": top_rows,
        "columns": cols,
    }
    print(f"isolation_forest_outliers: anomalies={out['anomalies']}")
    return out
