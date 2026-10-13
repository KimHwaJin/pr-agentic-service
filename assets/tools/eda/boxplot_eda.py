def boxplot_eda(data, columns: list | None = None, output_dir: str = "artifacts/plots", figsize: list = (10, 5), dpi: int = 110) -> dict:
    """수치형 컬럼의 박스플롯으로 이상치를 시각화합니다.

    Args:
        data: 입력 DataFrame
        columns: 대상 컬럼 (None이면 수치형 최대 12개)
        output_dir: 그림 저장 경로
        figsize: 그림 크기
        dpi: 해상도

    Returns:
        {"plot_path": str}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt

    numeric = data.select_dtypes("number")
    cols = [c for c in (columns or numeric.columns[:12]) if c in numeric.columns]
    plt.figure(figsize=tuple(figsize))
    numeric[cols].boxplot(rot=60)
    plt.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(output_dir) / "boxplot.png")
    plt.savefig(path, dpi=dpi)
    plt.show()
    return {"plot_path": path}
