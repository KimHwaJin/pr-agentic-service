def compute_statistics(data, columns: list | None = None, output_dir: str = "artifacts/metrics") -> dict:
    """수치형 컬럼의 기술 통계와 IQR 이상치 비율을 계산합니다.

    Args:
        data: 입력 DataFrame
        columns: 대상 컬럼 (None이면 전체 수치형)
        output_dir: 통계 CSV 저장 경로

    Returns:
        {"statistics": pandas.DataFrame, "numeric_columns": list, "outlier_ratio": dict}
    """
    from pathlib import Path

    numeric = data.select_dtypes("number")
    if columns:
        numeric = numeric[[c for c in columns if c in numeric.columns]]
    stats = numeric.describe().T
    q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
    iqr = q3 - q1
    outliers = ((numeric < q1 - 1.5 * iqr) | (numeric > q3 + 1.5 * iqr)).mean().round(4)
    stats["outlier_ratio"] = outliers
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    stats.to_csv(Path(output_dir) / "statistics.csv")
    print(stats.to_string())
    return {"statistics": stats, "numeric_columns": list(numeric.columns), "outlier_ratio": outliers.to_dict()}
