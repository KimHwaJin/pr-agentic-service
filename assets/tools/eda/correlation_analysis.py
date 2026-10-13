def correlation_analysis(data, method: str = "pearson", top_n: int = 10, output_dir: str = "artifacts/plots") -> dict:
    """수치형 컬럼 간 상관계수를 계산하고 히트맵을 그립니다.

    Args:
        data: 입력 DataFrame
        method: 상관 방법 ("pearson", "spearman", "kendall")
        top_n: 출력할 상관 상위 쌍 수
        output_dir: 그림 저장 경로

    Returns:
        {"correlation": pandas.DataFrame, "top_pairs": list}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import seaborn as sns

    corr = data.select_dtypes("number").corr(method=method)
    pairs = corr.where(~corr.isna()).stack()
    pairs = pairs[pairs.index.get_level_values(0) < pairs.index.get_level_values(1)]
    top = pairs.abs().sort_values(ascending=False).head(top_n)
    top_pairs = [{"a": a, "b": b, "corr": round(float(corr.loc[a, b]), 4)} for a, b in top.index]
    plt.figure(figsize=(10, 8))
    sns.heatmap(corr, cmap="coolwarm", center=0)
    plt.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    plt.savefig(Path(output_dir) / "correlation.png", dpi=110)
    plt.show()
    print(top_pairs)
    return {"correlation": corr, "top_pairs": top_pairs}
