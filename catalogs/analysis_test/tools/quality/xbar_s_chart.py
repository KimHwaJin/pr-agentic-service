def xbar_s_chart(
    data,
    value_column: str,
    subgroup_column: str,
    baseline_ratio: float = 0.5,
    output_dir: str = "artifacts/plots",
) -> dict:
    """부분군(웨이퍼, LOT, 날짜)별 평균·표준편차로 X-bar·S 관리도를 그립니다.

    부분군 평균의 이동(X-bar)과 부분군 안 산포의 변화(S)를 함께 봅니다.
    관리 한계는 앞부분(baseline_ratio) 부분군으로 정합니다.

    Args:
        data: 입력 DataFrame
        value_column: 관리할 수치형 컬럼
        subgroup_column: 부분군 컬럼 (예: "wf_id", "alias_lot_id", 날짜 컬럼)
        baseline_ratio: 관리 한계 계산에 쓸 앞부분 부분군 비율
        output_dir: 그림 저장 경로

    Returns:
        {"xbar": dict, "s": dict, "out_of_control": list, "subgroups": int,
         "subgroup_size": float, "plot_path": str}
    """
    from math import exp, lgamma, sqrt
    from pathlib import Path

    import matplotlib.pyplot as plt

    groups = (
        data.dropna(subset=[value_column])
        .groupby(subgroup_column)[value_column]
        .agg(["mean", "std", "count"])
        .sort_index()
    )
    groups = groups[groups["count"] >= 2]
    if len(groups) < 4:
        raise ValueError(
            f"크기 2 이상인 부분군이 {len(groups)}개입니다. "
            "4개 이상 필요합니다."
        )
    n = float(groups["count"].mean())
    c4 = sqrt(2 / (n - 1)) * exp(lgamma(n / 2) - lgamma((n - 1) / 2))
    base = groups.iloc[: max(int(len(groups) * baseline_ratio), 2)]
    center, s_bar = float(base["mean"].mean()), float(base["std"].mean())
    spread = 3 * s_bar / (c4 * sqrt(n))
    width = 3 * sqrt(1 - c4**2) / c4
    xbar = {"center": center, "ucl": center + spread, "lcl": center - spread}
    s = {
        "center": s_bar,
        "ucl": s_bar * (1 + width),
        "lcl": max(0.0, s_bar * (1 - width)),
    }
    flags = []
    for name, row in groups.iterrows():
        why = []
        if not xbar["lcl"] <= row["mean"] <= xbar["ucl"]:
            why.append("평균")
        if not s["lcl"] <= row["std"] <= s["ucl"]:
            why.append("산포")
        if why:
            flags.append(
                {
                    "subgroup": str(name),
                    "mean": float(row["mean"]),
                    "std": float(row["std"]),
                    "reason": why,
                }
            )
    labels = [str(i) for i in groups.index]
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for ax, column, limits, title in (
        (axes[0], "mean", xbar, "X-bar"),
        (axes[1], "std", s, "S"),
    ):
        ax.plot(labels, groups[column], marker="o", ms=3, lw=0.8)
        ax.axhline(limits["center"], color="green", ls="--")
        ax.axhline(limits["ucl"], color="red", ls="--")
        ax.axhline(limits["lcl"], color="red", ls="--")
        ax.set_ylabel(title)
    axes[0].set_title(f"X-bar/S chart: {value_column} by {subgroup_column}")
    step = max(len(labels) // 20, 1)
    axes[1].set_xticks(range(0, len(labels), step))
    axes[1].set_xticklabels(labels[::step], rotation=60)
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"xbar_s_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "xbar": xbar,
        "s": s,
        "out_of_control": flags,
        "subgroups": int(len(groups)),
        "subgroup_size": round(n, 2),
        "plot_path": path,
    }
    print(f"xbar_s_chart: out_of_control={[f['subgroup'] for f in flags]}")
    return out
