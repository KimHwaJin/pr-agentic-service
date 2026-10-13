def merge_data(left_data, right_data, join_columns: list, how: str = "inner") -> dict:
    """두 데이터를 공통 키 컬럼으로 결합합니다.

    Args:
        left_data: 왼쪽 DataFrame
        right_data: 오른쪽 DataFrame
        join_columns: 결합 키 컬럼 목록 (예: ["alias_lot_id", "wf_id", "x", "y"])
        how: 결합 방식 ("inner", "left", "outer")

    Returns:
        {"merged_data": pandas.DataFrame, "shape": list}
    """
    merged = left_data.merge(right_data, on=join_columns, how=how)
    print(f"merge_data: {left_data.shape} + {right_data.shape} -> {merged.shape}")
    return {"merged_data": merged, "shape": list(merged.shape)}
