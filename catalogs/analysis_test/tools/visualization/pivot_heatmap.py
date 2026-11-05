def pivot_heatmap(
    data,
    index_column: str,
    columns_column: str,
    value_column: str,
    agg: str = "mean",
    output_dir: str = "artifacts/plots",
) -> dict:
    """두 범주(예: LOT × 설비, 날짜 × 챔버)로 값을 집계해 히트맵을 그립니다.

    Args:
        data: 입력 DataFrame
        index_column: 행 범주 컬럼
        columns_column: 열 범주 컬럼
        value_column: 집계할 수치형 컬럼
        agg: 집계 방법 ("mean", "median", "sum", "count", "std")
        output_dir: 그림 저장 경로

    Returns:
        {"data": pandas.DataFrame, "max_cell": dict, "min_cell": dict,
         "plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import seaborn as sns

    if agg not in {"mean", "median", "sum", "count", "std"}:
        raise ValueError(
            f"agg '{agg}'은 지원하지 않습니다. mean, median, sum, count, std "
            "중 하나를 쓰세요."
        )
    table = data.pivot_table(
        index=index_column,
        columns=columns_column,
        values=value_column,
        aggfunc=agg,
    )
    if table.size == 0:
        raise ValueError("집계 결과가 비었습니다.")
    if table.shape[0] > 60 or table.shape[1] > 60:
        raise ValueError(
            f"표가 {table.shape[0]}×{table.shape[1]}로 너무 큽니다. "
            "범주가 60개 이하가 되게 거르거나 묶으세요."
        )
    stacked = table.stack().dropna()
    hi, lo = stacked.idxmax(), stacked.idxmin()
    fig, ax = plt.subplots(
        figsize=(
            max(6, 0.7 * table.shape[1] + 3),
            max(4, 0.4 * table.shape[0] + 2),
        )
    )
    sns.heatmap(
        table,
        annot=table.size <= 150,
        fmt=".3g",
        cmap="viridis",
        ax=ax,
    )
    ax.set_title(f"{agg}({value_column})")
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(
        Path(output_dir) / f"heatmap_{index_column}_{columns_column}.png"
    )
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "data": table.reset_index(),
        "max_cell": {
            index_column: str(hi[0]),
            columns_column: str(hi[1]),
            "value": float(stacked[hi]),
        },
        "min_cell": {
            index_column: str(lo[0]),
            columns_column: str(lo[1]),
            "value": float(stacked[lo]),
        },
        "plot_path": path,
    }
    print(f"pivot_heatmap: max={out['max_cell']} min={out['min_cell']}")
    return out
