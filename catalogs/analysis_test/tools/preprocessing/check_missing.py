def check_missing(data) -> dict:
    """컬럼별 결측값 수와 비율을 셉니다.

    Args:
        data: 입력 DataFrame

    Returns:
        {"missing": dict, "missing_ratio": dict, "total_rows": int,
         "has_missing": bool}
    """
    counts = data.isna().sum()
    counts = counts[counts > 0]
    total = len(data)
    missing = {str(k): int(v) for k, v in counts.items()}
    ratio = {
        k: round(v / total, 4) if total else 0.0 for k, v in missing.items()
    }
    print(f"check_missing: {missing or '결측 없음'} (rows={total})")
    return {
        "missing": missing,
        "missing_ratio": ratio,
        "total_rows": total,
        "has_missing": bool(missing),
    }
