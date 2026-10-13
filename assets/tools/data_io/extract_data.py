def extract_data(
    data_type: str,
    lot_cd: str | None = None,
    process: list | str | None = None,
    start_dt: str | None = None,
    end_dt: str | None = None,
    limit: int | None = None,
) -> dict:
    """원천 데이터를 추출합니다. (mock: 실제 추출 없이 조건만 반환)

    Args:
        data_type: 데이터 유형. "nce" 또는 "wt"
        lot_cd: LOT 코드
        process: 공정 코드 또는 목록
        start_dt: 조회 시작일 (YYYY-MM-DD)
        end_dt: 조회 종료일 (YYYY-MM-DD)
        limit: 최대 행 수

    Returns:
        {"data": dict, "query": dict}
    """
    query = {"data_type": str(data_type).lower(), "lot_cd": lot_cd, "process": process,
             "start_dt": start_dt, "end_dt": end_dt, "limit": limit}
    print(f"extract_data mock: {query}")
    return {"data": {}, "query": query}
