def pca_analysis(
    data,
    columns: list | None = None,
    n_components: int = 3,
    color_column: str | None = None,
    output_dir: str = "artifacts/plots",
) -> dict:
    """여러 측정값을 주성분(PCA)으로 줄여, 함께 움직이는 변수 묶음을 찾습니다.

    값은 표준화한 뒤 계산합니다. 첫 두 주성분 산점도를 그립니다.

    Args:
        data: 입력 DataFrame
        columns: 사용할 수치형 컬럼 (None이면 좌표를 뺀 수치형 전부)
        n_components: 주성분 수
        color_column: 산점도 색을 나눌 컬럼 (예: "alias_lot_id")
        output_dir: 그림 저장 경로

    Returns:
        {"explained_variance": list, "cumulative": list, "loadings": dict,
         "data": pandas.DataFrame, "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import seaborn as sns
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    numeric = [
        c for c in data.select_dtypes("number").columns if c not in {"x", "y"}
    ]
    cols = [c for c in (columns or numeric) if c in numeric]
    if len(cols) < 2:
        raise ValueError("PCA에는 수치형 컬럼이 2개 이상 필요합니다.")
    frame = data.dropna(subset=cols)
    n = min(int(n_components), len(cols))
    pca = PCA(n_components=n, random_state=0)
    scores = pca.fit_transform(StandardScaler().fit_transform(frame[cols]))
    names = [f"PC{i + 1}" for i in range(n)]
    result = frame.copy()
    for i, name in enumerate(names):
        result[name] = scores[:, i]
    loadings = {
        name: dict(
            sorted(
                (
                    (c, round(float(w), 4))
                    for c, w in zip(cols, pca.components_[i], strict=True)
                ),
                key=lambda p: -abs(p[1]),
            )[:5]
        )
        for i, name in enumerate(names)
    }
    ratio = [round(float(v), 4) for v in pca.explained_variance_ratio_]
    cumulative = [round(float(sum(ratio[: i + 1])), 4) for i in range(n)]
    fig, ax = plt.subplots(figsize=(7, 6))
    sns.scatterplot(
        data=result,
        x="PC1",
        y="PC2" if n > 1 else "PC1",
        hue=color_column if color_column in result else None,
        s=12,
        ax=ax,
    )
    ax.set_title(f"PCA ({cumulative[-1]:.0%} explained)")
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / "pca_scatter.png")
    plt.savefig(path, dpi=110)
    plt.show()
    print(f"pca_analysis: explained={ratio} loadings={loadings}")
    return {
        "explained_variance": ratio,
        "cumulative": cumulative,
        "loadings": loadings,
        "data": result,
        "plot_path": path,
    }
