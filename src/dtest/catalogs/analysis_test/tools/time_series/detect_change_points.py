def detect_change_points(
    data,
    value_column: str,
    time_column: str = "timestamp",
    group_column: str | None = None,
    min_shift_sd: float = 2.0,
) -> dict:
    """평균이 크게 바뀐 시점을 찾습니다 (그룹별, 한 번의 변화 기준).

    Args:
        data: 입력 DataFrame
        value_column: 대상 수치형 컬럼
        time_column: 시간 컬럼
        group_column: 그룹 컬럼 (예: "eqp_id")
        min_shift_sd: 변화 전 표준편차의 몇 배 이상 바뀌어야 변화로 볼지

    Returns:
        {"change_points": list, "has_change": bool}
    """
    import numpy as np

    found = []
    parts = data.groupby(group_column) if group_column else [("all", data)]
    for name, part in parts:
        part = part.sort_values(time_column)
        values = part[value_column].to_numpy(dtype=float)
        n = len(values)
        if n < 20:
            continue
        best, best_i = 0.0, None
        total = np.cumsum(values)
        for i in range(10, n - 10):
            before = total[i - 1] / i
            after = (total[-1] - total[i - 1]) / (n - i)
            gap = abs(after - before)
            if gap > best:
                best, best_i = gap, i
        if best_i is None:
            continue
        sd = float(np.std(values[:best_i])) or 1e-9
        shift = best / sd
        if shift >= min_shift_sd:
            found.append(
                {
                    "group": str(name),
                    "time": str(part[time_column].iloc[best_i]),
                    "before_mean": float(values[:best_i].mean()),
                    "after_mean": float(values[best_i:].mean()),
                    "shift_sd": round(float(shift), 2),
                }
            )
    print(f"detect_change_points: {found or '변화 없음'}")
    return {"change_points": found, "has_change": bool(found)}
