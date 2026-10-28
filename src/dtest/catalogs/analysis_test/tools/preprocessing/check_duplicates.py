def check_duplicates(data, key_columns: list | None = None) -> dict:
    """완전히 같은 행(또는 키가 같은 행)이 몇 개인지 셉니다.

    Args:
        data: 입력 DataFrame
        key_columns: 중복 판단 기준 컬럼 (None이면 모든 컬럼)

    Returns:
        {"duplicate_rows": int, "duplicate_ratio": float,
         "has_duplicates": bool}
    """
    dup = int(data.duplicated(subset=key_columns).sum())
    ratio = round(dup / len(data), 4) if len(data) else 0.0
    print(f"check_duplicates: {dup} rows ({ratio:.2%}), keys={key_columns}")
    return {
        "duplicate_rows": dup,
        "duplicate_ratio": ratio,
        "has_duplicates": dup > 0,
    }
