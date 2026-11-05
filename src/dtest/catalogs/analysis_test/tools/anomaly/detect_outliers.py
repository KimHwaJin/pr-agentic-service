def detect_outliers(
    data,
    columns: list | None = None,
    method: str = "iqr",
    threshold: float | None = None,
    group_column: str | None = None,
) -> dict:
    """수치형 컬럼별 이상치를 IQR 또는 z-score 기준으로 찾습니다.

    Args:
        data: 입력 DataFrame
        columns: 대상 컬럼 (None이면 좌표를 뺀 수치형 전부)
        method: "iqr"(Q1-k*IQR, Q3+k*IQR) 또는 "zscore"(|z| > k)
        threshold: k 값 (None이면 iqr 1.5, zscore 3.0)
        group_column: 그룹(예: 설비)마다 기준을 따로 잡을 때 그룹 컬럼

    Returns:
        {"data": pandas.DataFrame, "outliers": dict, "outlier_rows": int,
         "method": str}
    """
    import numpy as np
    import pandas as pd

    if method not in {"iqr", "zscore"}:
        raise ValueError(
            f"method '{method}'은 지원하지 않습니다. iqr 또는 zscore를 쓰세요."
        )
    k = (
        float(threshold)
        if threshold is not None
        else (1.5 if method == "iqr" else 3.0)
    )
    skip = {"x", "y", group_column}
    numeric = [
        c for c in data.select_dtypes("number").columns if c not in skip
    ]
    cols = [c for c in (columns or numeric) if c in numeric]
    if not cols:
        raise ValueError("이상치를 볼 수치형 컬럼이 없습니다.")

    def flags(frame):
        out = pd.DataFrame(False, index=frame.index, columns=cols)
        for c in cols:
            v = frame[c]
            if method == "iqr":
                q1, q3 = v.quantile(0.25), v.quantile(0.75)
                iqr = q3 - q1
                out[c] = (v < q1 - k * iqr) | (v > q3 + k * iqr)
            else:
                sd = v.std()
                out[c] = ((v - v.mean()).abs() / sd > k) if sd else False
        return out

    if group_column:
        mask = pd.concat(
            [flags(part) for _, part in data.groupby(group_column)]
        ).reindex(data.index, fill_value=False)
    else:
        mask = flags(data)
    result = data.copy()
    result["is_outlier"] = mask.any(axis=1).to_numpy()
    counts = {c: int(n) for c, n in mask.sum().items() if n}
    out = {
        "data": result,
        "outliers": counts,
        "outlier_rows": int(np.sum(result["is_outlier"])),
        "method": f"{method}(k={k})",
    }
    print(f"detect_outliers: {counts or '없음'} rows={out['outlier_rows']}")
    return out
