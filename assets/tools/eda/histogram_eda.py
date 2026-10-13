def histogram_eda(
    data, columns: list | None = None, bins: int = 30, output_dir: str = "artifacts/plots", figsize: list | None = None, dpi: int = 110
) -> dict:
    """수치형 컬럼의 분포 히스토그램을 그립니다.

    Args:
        data: 입력 DataFrame
        columns: 대상 컬럼 (None이면 수치형 최대 12개)
        bins: 구간 수
        output_dir: 그림 저장 경로
        figsize: 그림 크기 (None이면 컬럼 수에 맞춤)
        dpi: 해상도

    Returns:
        {"plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    numeric = data.select_dtypes("number")
    cols = [c for c in (columns or numeric.columns[:12]) if c in numeric.columns]
    axes = numeric[cols].hist(bins=bins, figsize=tuple(figsize) if figsize else (14, 3 * ((len(cols) + 3) // 4)), layout=(-1, 4))
    plt.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / "histogram.png")
    plt.savefig(path, dpi=dpi)
    plt.show()
    return {"plot_path": path, "columns": cols, "axes": len(axes.flat)}
