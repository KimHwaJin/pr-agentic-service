def transform_nce(data: dict | None = None, transform_op: str = "pivot") -> dict:
    """NCE 데이터를 wide 분석 형식(DataFrame)으로 변환합니다.

    Args:
        data: extract_data의 data 출력
        transform_op: 변환 방식 ("pivot")

    Returns:
        {"data": pandas.DataFrame, "shape": list}
    """
    import pandas as pd

    frame = pd.DataFrame(data) if data else pd.read_parquet("/workspace/pv/default_data/df_nce_wide_format.parquet")
    print(f"transform_nce: shape={frame.shape}")
    return {"data": frame, "shape": list(frame.shape)}
