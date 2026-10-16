def kmeans_clustering(
    data, feature_columns: list | None = None, n_clusters: int = 3
) -> dict:
    """수치형 변수로 K-means 군집을 나눕니다 (표준화 후).

    Args:
        data: 입력 DataFrame
        feature_columns: 사용할 수치형 변수 (None이면 좌표를 뺀 수치형 전부)
        n_clusters: 군집 수

    Returns:
        {"data": pandas.DataFrame, "cluster_sizes": dict, "centers": dict}
    """
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    features = feature_columns or [
        c for c in data.select_dtypes("number").columns if c not in {"x", "y"}
    ]
    frame = data.dropna(subset=features).copy()
    scaled = StandardScaler().fit_transform(frame[features])
    model = KMeans(n_clusters=n_clusters, n_init=10, random_state=0)
    frame["cluster"] = model.fit_predict(scaled)
    sizes = {
        str(k): int(v) for k, v in frame["cluster"].value_counts().items()
    }
    centers = {
        str(k): {c: round(float(v), 4) for c, v in g[features].mean().items()}
        for k, g in frame.groupby("cluster")
    }
    print(f"kmeans_clustering: sizes={sizes}")
    return {"data": frame, "cluster_sizes": sizes, "centers": centers}
