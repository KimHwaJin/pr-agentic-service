def control_chart(
    data,
    value_column: str,
    time_column: str | None = None,
    baseline_ratio: float = 0.5,
    sigma: float = 3.0,
    output_dir: str = "artifacts/plots",
) -> dict:
    """개별값 관리도(I-chart)를 그리고 관리 한계를 벗어난 점을 셉니다.

    관리 한계는 앞부분(baseline_ratio) 데이터로 정합니다.

    Args:
        data: 입력 DataFrame
        value_column: 관리할 수치형 컬럼
        time_column: 시간 순서 컬럼 (None이면 행 순서)
        baseline_ratio: 관리 한계 계산에 쓸 앞부분 비율
        sigma: 관리 한계 폭 (표준편차 배수)
        output_dir: 그림 저장 경로

    Returns:
        {"center": float, "ucl": float, "lcl": float, "out_of_control": int,
         "first_out_time": str | None, "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    frame = data.sort_values(time_column) if time_column else data
    values = frame[value_column].dropna()
    base = values.iloc[: max(int(len(values) * baseline_ratio), 2)]
    center, sd = float(base.mean()), float(base.std())
    ucl, lcl = center + sigma * sd, center - sigma * sd
    out = (values > ucl) | (values < lcl)
    x = frame.loc[values.index, time_column] if time_column else values.index
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(x, values, lw=0.8)
    for level in (center, ucl, lcl):
        ax.axhline(level, color="red" if level != center else "green", ls="--")
    ax.scatter(x[out.to_numpy()], values[out], color="red", s=10)
    ax.set_title(f"I-chart: {value_column}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"control_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    first = (
        str(x[out.to_numpy()].iloc[0]) if out.any() and time_column else None
    )
    result = {
        "center": center,
        "ucl": ucl,
        "lcl": lcl,
        "out_of_control": int(out.sum()),
        "first_out_time": first,
        "plot_path": path,
    }
    print(f"control_chart: {result}")
    return result
