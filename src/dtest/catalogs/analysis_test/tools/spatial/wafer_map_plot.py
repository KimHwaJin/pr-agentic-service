def wafer_map_plot(
    data,
    value_column: str,
    x_column: str = "x",
    y_column: str = "y",
    output_dir: str = "artifacts/plots",
) -> dict:
    """die 좌표별 평균값을 wafer map(열지도)으로 그립니다.

    Args:
        data: 입력 DataFrame (die 좌표 포함, 여러 wafer면 좌표별 평균)
        value_column: 색으로 나타낼 수치형 컬럼 (불량 여부 0/1이면 불량률)
        x_column: x 좌표 컬럼
        y_column: y 좌표 컬럼
        output_dir: 그림 저장 경로

    Returns:
        {"plot_path": str, "min": float, "max": float, "dies": int}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    grid = data.pivot_table(
        index=y_column, columns=x_column, values=value_column, aggfunc="mean"
    )
    fig, ax = plt.subplots(figsize=(6, 6))
    image = ax.imshow(grid.to_numpy(), origin="lower", cmap="viridis")
    fig.colorbar(image, ax=ax, label=value_column)
    ax.set_title(f"wafer map: {value_column}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(
        Path(output_dir) / f"wafer_map_{value_column}.png".replace(" ", "_")
    )
    plt.savefig(path, dpi=110)
    plt.show()
    values = grid.stack()
    out = {
        "plot_path": path,
        "min": float(values.min()),
        "max": float(values.max()),
        "dies": int(values.size),
    }
    print(f"wafer_map_plot: {out}")
    return out
