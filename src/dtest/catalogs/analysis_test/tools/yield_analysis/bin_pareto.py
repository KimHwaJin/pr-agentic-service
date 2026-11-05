def bin_pareto(
    data,
    bin_column: str = "PT1H.symbol",
    exclude: list | None = None,
    group_column: str | None = None,
    output_dir: str = "artifacts/plots",
) -> dict:
    """불량 bin(또는 불량 유형)을 많은 순으로 세어 파레토 차트를 그립니다.

    Args:
        data: 입력 DataFrame
        bin_column: bin·불량 유형 컬럼
        exclude: 셀 때 뺄 값 (None이면 ["PASS"])
        group_column: 그룹별 bin 구성을 같이 볼 때 그룹 컬럼 (예: LOT)

    Returns:
        {"bins": list, "top_bin": str, "total": int, "by_group": dict,
         "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    if bin_column not in data:
        raise ValueError(f"bin 컬럼 '{bin_column}'이 데이터에 없습니다.")
    skip = ["PASS"] if exclude is None else list(exclude)
    fails = data[~data[bin_column].isin(skip)].dropna(subset=[bin_column])
    if fails.empty:
        raise ValueError("제외 값 말고 남은 bin이 없습니다.")
    counts = fails[bin_column].astype(str).value_counts()
    total = int(counts.sum())
    cumulative = counts.cumsum() / total * 100
    bins = [
        {
            "bin": str(b),
            "count": int(c),
            "pct": round(100 * c / total, 2),
            "cum_pct": round(float(cumulative[b]), 2),
        }
        for b, c in counts.items()
    ]
    by_group = {}
    if group_column:
        table = (
            fails.groupby(group_column)[bin_column]
            .value_counts(normalize=True)
            .mul(100)
            .round(2)
        )
        by_group = {
            str(g): {str(b): float(v) for b, v in part.droplevel(0).items()}
            for g, part in table.groupby(level=0)
        }
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(counts.index.astype(str), counts.to_numpy())
    ax2 = ax.twinx()
    ax2.plot(
        counts.index.astype(str),
        cumulative.to_numpy(),
        color="red",
        marker="o",
    )
    ax2.set_ylim(0, 105)
    ax.set_title(f"Pareto: {bin_column}")
    ax.tick_params(axis="x", rotation=60)
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / "bin_pareto.png")
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "bins": bins,
        "top_bin": bins[0]["bin"],
        "total": total,
        "by_group": by_group,
        "plot_path": path,
    }
    print(f"bin_pareto: total={total} top={bins[:3]}")
    return out
