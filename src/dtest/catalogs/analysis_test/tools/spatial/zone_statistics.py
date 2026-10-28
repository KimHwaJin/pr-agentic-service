def zone_statistics(
    data,
    value_column: str,
    x_column: str = "x",
    y_column: str = "y",
    rings: int = 3,
) -> dict:
    """wafer 중심에서의 거리 구간(ring)별로 값을 요약합니다.

    Args:
        data: 입력 DataFrame (die 좌표 포함)
        value_column: 요약할 수치형 컬럼 (0/1이면 비율)
        x_column: x 좌표 컬럼
        y_column: y 좌표 컬럼
        rings: 거리 구간 수 (안쪽 ring_1 ~ 바깥 ring_N)

    Returns:
        {"stats": dict, "outer_to_inner_ratio": float}
    """
    import numpy as np
    import pandas as pd

    cx = (data[x_column].min() + data[x_column].max()) / 2
    cy = (data[y_column].min() + data[y_column].max()) / 2
    dist = np.sqrt((data[x_column] - cx) ** 2 + (data[y_column] - cy) ** 2)
    ring = pd.cut(
        dist / dist.max(),
        bins=rings,
        labels=[f"ring_{i + 1}" for i in range(rings)],
    )
    grouped = data[value_column].groupby(ring, observed=True)
    stats = {
        str(k): {"mean": float(v.mean()), "count": int(v.count())}
        for k, v in grouped
    }
    inner, outer = stats["ring_1"]["mean"], stats[f"ring_{rings}"]["mean"]
    ratio = float(outer / inner) if inner else float("inf")
    print(f"zone_statistics: {stats} outer/inner={ratio:.2f}")
    return {"stats": stats, "outer_to_inner_ratio": ratio}
