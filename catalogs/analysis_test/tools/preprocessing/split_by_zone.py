def split_by_zone(
    data,
    x_column: str = "x",
    y_column: str = "y",
    center: list | None = None,
    edge_ratio: float = 0.8,
) -> dict:
    """die 좌표로 wafer edge·center 구역을 나눠 zone 컬럼을 붙입니다.

    Args:
        data: 입력 DataFrame (die 좌표 포함)
        x_column: x 좌표 컬럼
        y_column: y 좌표 컬럼
        center: wafer 중심 [x, y] (None이면 좌표 범위의 가운데)
        edge_ratio: 중심에서 가장 먼 die까지 거리 대비 이 비율을 넘으면 edge

    Returns:
        {"data": pandas.DataFrame, "zone_counts": dict}
    """
    import numpy as np

    for column in (x_column, y_column):
        if column not in data:
            raise ValueError(f"좌표 컬럼 '{column}'이 데이터에 없습니다.")
    cx, cy = center or [
        (data[x_column].min() + data[x_column].max()) / 2,
        (data[y_column].min() + data[y_column].max()) / 2,
    ]
    dist = np.sqrt((data[x_column] - cx) ** 2 + (data[y_column] - cy) ** 2)
    frame = data.copy()
    frame["zone"] = np.where(dist / dist.max() > edge_ratio, "edge", "center")
    counts = {str(k): int(v) for k, v in frame["zone"].value_counts().items()}
    print(f"split_by_zone: {counts}")
    return {"data": frame, "zone_counts": counts}
