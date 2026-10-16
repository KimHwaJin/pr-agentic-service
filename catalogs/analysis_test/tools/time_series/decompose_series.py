def decompose_series(
    data,
    value_column: str,
    time_column: str = "timestamp",
    period: int = 24,
    output_dir: str = "artifacts/plots",
) -> dict:
    """시계열을 추세·주기·잔차로 분해합니다 (statsmodels).

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
    from statsmodels.tsa.seasonal import seasonal_decompose

    series = data.sort_values(time_column).set_index(time_column)[value_column]
    if len(series) < 2 * period:
        raise ValueError(
            f"데이터가 {len(series)}행입니다. "
            f"주기({period})의 2배 이상이어야 합니다."
        )
    result = seasonal_decompose(series, period=period)
    trend = result.trend.dropna()
    fig = result.plot()
    fig.set_size_inches(12, 8)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / f"decompose_{value_column}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "trend_change": float(trend.iloc[-1] - trend.iloc[0]),
        "seasonal_amplitude": float(
            result.seasonal.max() - result.seasonal.min()
        ),
        "residual_sd": float(result.resid.dropna().std()),
        "plot_path": path,
    }
    print(f"decompose_series: {out}")
    return out
