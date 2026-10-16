def process_capability(
    data, value_column: str, lsl: float, usl: float
) -> dict:
    """규격 하한·상한 대비 공정능력(Cp, Cpk)을 계산합니다.

    Args:
        data: 입력 DataFrame
        value_column: 대상 수치형 컬럼
        lsl: 규격 하한
        usl: 규격 상한

    Returns:
        {"cp": float, "cpk": float, "mean": float, "std": float,
         "within_spec_ratio": float}
    """
    if usl <= lsl:
        raise ValueError(f"usl({usl})은 lsl({lsl})보다 커야 합니다.")
    values = data[value_column].dropna()
    mean, sd = float(values.mean()), float(values.std())
    cp = (usl - lsl) / (6 * sd)
    cpk = min(usl - mean, mean - lsl) / (3 * sd)
    within = float(((values >= lsl) & (values <= usl)).mean())
    out = {
        "cp": round(cp, 3),
        "cpk": round(cpk, 3),
        "mean": mean,
        "std": sd,
        "within_spec_ratio": round(within, 4),
    }
    print(f"process_capability: {out}")
    return out
