def decompose_series(
    data,
    value_column: str,
    time_column: str = "timestamp",
    period: int = 24,
    output_dir: str = "artifacts/plots",
) -> dict:
    """시계열을 추세·주기·잔차로 분해합니다 (가법 고전 분해).

    추세는 주기 길이의 중심 이동평균, 주기 성분은 추세를 뺀 값의 위상별
    평균(합이 0이 되게 맞춤), 잔차는 나머지입니다.

    Args:
        data: 입력 DataFrame (한 계열. 여러 설비가 섞였으면 먼저 거르세요)
        value_column: 대상 수치형 컬럼
        time_column: 시간 컬럼
        period: 주기 길이 (행 수, 예: 시간 단위 데이터의 하루 = 24)
        output_dir: 그림 저장 경로

    Returns:
        {"trend_change": float, "seasonal_amplitude": float,
         "residual_sd": float, "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    series = (
        data.sort_values(time_column)
        .set_index(time_column)[value_column]
        .astype(float)
    )
    if series.isna().any():
        series = series.interpolate(limit_direction="both")
    period = int(period)
    if period < 2:
        raise ValueError("period는 2 이상이어야 합니다.")
    if len(series) < 2 * period:
        raise ValueError(
            f"데이터가 {len(series)}행입니다. "
            f"주기({period})의 2배 이상이어야 합니다."
        )
    values = series.to_numpy()
    if period % 2 == 0:  # 2 x period centered moving average
        weights = np.r_[0.5, np.ones(period - 1), 0.5] / period
    else:
        weights = np.ones(period) / period
    half = len(weights) // 2
    trend = np.full(len(values), np.nan)
    trend[half : len(values) - half] = np.convolve(
        values, weights, mode="valid"
    )
    detrended = values - trend
    phase = np.arange(len(values)) % period
    means = (
        pd.Series(detrended).groupby(phase).mean().reindex(range(period))
    ).to_numpy()
    means = means - np.nanmean(means)
    seasonal = means[phase]
    resid = values - trend - seasonal

    index = series.index
    fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
    for ax, part, title in zip(
        axes,
        (values, trend, seasonal, resid),
        ("observed", "trend", "seasonal", "residual"),
        strict=True,
    ):
        ax.plot(index, part, lw=0.8)
        ax.set_ylabel(title)
    axes[0].set_title(f"decompose: {value_column} (period={period})")
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"decompose_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    valid = trend[~np.isnan(trend)]
    out = {
        "trend_change": float(valid[-1] - valid[0]),
        "seasonal_amplitude": float(np.nanmax(means) - np.nanmin(means)),
        "residual_sd": float(np.nanstd(resid, ddof=1)),
        "plot_path": path,
    }
    print(f"decompose_series: {out}")
    return out
