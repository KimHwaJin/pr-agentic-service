def fragile_transform(data, mode: str = "scale", factor: float = 1.0) -> dict:
    """[시험용] 수치형 컬럼에 factor를 곱하거나 더합니다.

    인자가 틀리면 분명한 오류를 냅니다.

    실패 복구(인자 수정 후 재실행)를 시험할 때만 씁니다.

    Args:
        data: 입력 DataFrame
        mode: "scale"(곱하기) | "offset"(더하기)
        factor: 곱하거나 더할 값 (0보다 커야 함)

    Returns:
        {"data": pandas.DataFrame, "mode": str, "factor": float}
    """
    if mode not in {"scale", "offset"}:
        raise ValueError(
            f"mode '{mode}'은 지원하지 않습니다. "
            "'scale' 또는 'offset'을 쓰세요."
        )
    if factor <= 0:
        raise ValueError(f"factor는 0보다 커야 합니다 (받은 값: {factor}).")
    frame = data.copy()
    numeric = frame.select_dtypes("number").columns
    frame[numeric] = (
        frame[numeric] * factor if mode == "scale" else frame[numeric] + factor
    )
    print(f"fragile_transform: {mode} {factor} on {len(numeric)} columns")
    return {"data": frame, "mode": mode, "factor": factor}
