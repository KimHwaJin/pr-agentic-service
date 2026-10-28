def validate_ranges(data, rules: dict | None = None) -> dict:
    """값이 허용 범위를 벗어난 행을 셉니다.

    Args:
        data: 입력 DataFrame
        rules: {"컬럼": [최소, 최대]} (None이면 x·y를 뺀 수치형 컬럼에서
            음수를 위반으로 봄. 최소·최대에 null을 쓰면 그쪽은 제한 없음)

    Returns:
        {"violations": dict, "has_violations": bool, "rules": dict}
    """
    if rules is None:
        numeric = [
            c
            for c in data.select_dtypes("number").columns
            if c not in {"x", "y"}
        ]
        rules = {c: [0, None] for c in numeric}
    violations = {}
    for column, (low, high) in rules.items():
        if column not in data:
            raise ValueError(f"컬럼 '{column}'이 데이터에 없습니다.")
        values = data[column]
        bad = 0
        if low is not None:
            bad += int((values < low).sum())
        if high is not None:
            bad += int((values > high).sum())
        if bad:
            violations[str(column)] = bad
    print(f"validate_ranges: {violations or '위반 없음'}")
    return {
        "violations": violations,
        "has_violations": bool(violations),
        "rules": rules,
    }
