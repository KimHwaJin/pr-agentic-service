def cusum_chart(
    data,
    value_column: str,
    time_column: str | None = None,
    baseline_ratio: float = 0.3,
    k: float = 0.5,
    h: float = 8.0,
    output_dir: str = "artifacts/plots",
) -> dict:
    """CUSUM 관리도로 작은 평균 이동(서서히 생기는 drift)을 일찍 잡습니다.

    개별값 관리도(control_chart)는 큰 튐에 강하고, CUSUM은 작은 변화가
    쌓이는 것에 강합니다. 기준 평균·표준편차는 앞부분(baseline_ratio)으로
    정하고, k·h는 표준편차 배수입니다.

    Args:
        data: 입력 DataFrame (한 계열)
        value_column: 관리할 수치형 컬럼
        time_column: 시간 순서 컬럼 (None이면 행 순서)
        baseline_ratio: 기준 계산에 쓸 앞부분 비율
        k: 허용 폭 (보통 0.5)
        h: 경보 한계 (교과서 값은 4~5. 수백 행 이상인 긴 계열은 우연한
            경보를 줄이려고 기본 8)
        output_dir: 그림 저장 경로

    Returns:
        {"target": float, "sigma": float, "alarms": int, "direction": str,
         "first_alarm_time": str | None, "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import numpy as np

    frame = data.sort_values(time_column) if time_column else data
    frame = frame.dropna(subset=[value_column])
    values = frame[value_column].to_numpy(dtype=float)
    base = values[: max(int(len(values) * baseline_ratio), 5)]
    target, sigma = float(base.mean()), float(base.std(ddof=1)) or 1e-9
    z = (values - target) / sigma
    upper = np.zeros(len(z))
    lower = np.zeros(len(z))
    for i in range(len(z)):
        prev_u = upper[i - 1] if i else 0.0
        prev_l = lower[i - 1] if i else 0.0
        upper[i] = max(0.0, prev_u + z[i] - k)
        lower[i] = min(0.0, prev_l + z[i] + k)
    alarm = (upper > h) | (lower < -h)
    x = frame[time_column].to_numpy() if time_column else np.arange(len(z))
    first = None
    direction = "없음"
    if alarm.any():
        i = int(np.argmax(alarm))
        first = str(frame[time_column].iloc[i]) if time_column else str(i)
        direction = "증가" if upper[i] > h else "감소"
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(x, upper, lw=0.8, label="C+")
    ax.plot(x, lower, lw=0.8, label="C-")
    ax.axhline(h, color="red", ls="--")
    ax.axhline(-h, color="red", ls="--")
    ax.set_title(f"CUSUM: {value_column} (k={k}, h={h})")
    ax.legend()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"cusum_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "target": target,
        "sigma": sigma,
        "alarms": int(alarm.sum()),
        "direction": direction,
        "first_alarm_time": first,
        "plot_path": path,
    }
    print(f"cusum_chart: {out}")
    return out
