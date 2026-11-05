def scatter_plot(
    data,
    x_column: str,
    y_column: str,
    hue_column: str | None = None,
    fit_line: bool = True,
    max_points: int = 5000,
    output_dir: str = "artifacts/plots",
) -> dict:
    """두 수치형 변수의 산점도를 그립니다 (seaborn, 회귀선·그룹 색 가능).

    Args:
        data: 입력 DataFrame
        x_column: x축 수치형 컬럼
        y_column: y축 수치형 컬럼
        hue_column: 색을 나눌 그룹 컬럼 (예: "eqp_id")
        fit_line: 회귀선 표시 (hue_column이 있으면 그룹별)
        max_points: 그릴 최대 점 수 (넘으면 무작위 표본)
        output_dir: 그림 저장 경로

    Returns:
        {"plot_path": str, "pearson_r": float, "rows": int}
    """
    from pathlib import Path

    import matplotlib.pyplot as plt
    import seaborn as sns

    cols = [x_column, y_column] + ([hue_column] if hue_column else [])
    frame = data[cols].dropna()
    if len(frame) < 2:
        raise ValueError("그릴 행이 2개 미만입니다.")
    r = float(frame[x_column].corr(frame[y_column]))
    shown = (
        frame.sample(max_points, random_state=0)
        if len(frame) > max_points
        else frame
    )
    if fit_line:
        grid = sns.lmplot(
            data=shown,
            x=x_column,
            y=y_column,
            hue=hue_column,
            height=5,
            aspect=1.4,
            scatter_kws={"s": 10, "alpha": 0.6},
        )
        fig = grid.figure
    else:
        fig, ax = plt.subplots(figsize=(7, 5))
        sns.scatterplot(
            data=shown, x=x_column, y=y_column, hue=hue_column, s=10, ax=ax
        )
    fig.suptitle(f"{y_column} vs {x_column} (r={r:.2f})")
    fig.tight_layout()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    safe = f"{x_column}_vs_{y_column}".replace("/", "_").replace(" ", "_")
    path = str(Path(output_dir) / f"scatter_{safe}.png")
    plt.savefig(path, dpi=110)
    plt.show()
    out = {
        "plot_path": path,
        "pearson_r": round(r, 4),
        "rows": int(len(frame)),
    }
    print(f"scatter_plot: {out}")
    return out
