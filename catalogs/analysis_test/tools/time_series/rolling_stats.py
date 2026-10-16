def rolling_stats(
    data,
    value_column: str,
    time_column: str = "timestamp",
    window: int = 24,
    group_column: str | None = None,
    output_dir: str = "artifacts/plots",
) -> dict:
    """이동 평균·이동 표준편차를 구하고 그래프로 그립니다.

    Args:
        data: 입력 DataFrame
        value_column: 대상 수치형 컬럼
        time_column: 시간 컬럼
        window: 이동 구간 (행 수)
        group_column: 그룹별로 따로 계산할 컬럼 (예: "eqp_id")
        output_dir: 그림 저장 경로

    Returns:
        {"data": pandas.DataFrame, "summary": dict, "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    frame = data.sort_values(time_column).copy()
    keys = frame[group_column] if group_column else None
    rolled = (
        frame.groupby(keys)[value_column]
        if keys is not None
        else frame[value_column]
    )
    frame["rolling_mean"] = rolled.transform(
        lambda s: s.rolling(window).mean()
    )
    frame["rolling_std"] = rolled.transform(lambda s: s.rolling(window).std())
    summary = {}
    fig, ax = plt.subplots(figsize=(12, 4))
    for name, part in (
        frame.groupby(group_column) if group_column else [("all", frame)]
    ):
        means = part["rolling_mean"].dropna()
        summary[str(name)] = {
            "first": float(means.iloc[0]) if len(means) else None,
            "last": float(means.iloc[-1]) if len(means) else None,
            "max": float(means.max()) if len(means) else None,
        }
        ax.plot(part[time_column], part["rolling_mean"], label=str(name))
    ax.set_title(f"{value_column} rolling mean (window={window})")
    ax.legend()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"rolling_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    print(f"rolling_stats: {summary}")
    return {"data": frame, "summary": summary, "plot_path": path}
