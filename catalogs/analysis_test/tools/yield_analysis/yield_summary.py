def yield_summary(
    data,
    group_columns: list | str,
    fail_column: str | None = "PT1H.p_f",
    yield_column: str | None = None,
) -> dict:
    """그룹(LOT, 웨이퍼, 설비 등)별 수율을 계산하고 낮은 순으로 정렬합니다.

    die별 pass/fail 데이터(WT)면 fail_column(1=fail)로 수율을 계산하고,
    이미 수율이 있는 데이터면 yield_column의 평균을 씁니다.

    Args:
        data: 입력 DataFrame
        group_columns: 그룹 컬럼 또는 목록 (예: ["alias_lot_id"])
        fail_column: fail 여부 컬럼 (1 = fail). yield_column을 쓰면 무시
        yield_column: 수율(%) 컬럼 (예: "yield_pct")

    Returns:
        {"data": pandas.DataFrame, "overall_yield": float, "lowest": dict,
         "highest": dict}
    """
    keys = (
        [group_columns]
        if isinstance(group_columns, str)
        else list(group_columns)
    )
    missing = [c for c in keys if c not in data]
    if missing:
        raise ValueError(f"그룹 컬럼 {missing}이 데이터에 없습니다.")
    if yield_column:
        if yield_column not in data:
            raise ValueError(
                f"수율 컬럼 '{yield_column}'이 데이터에 없습니다."
            )
        table = (
            data.groupby(keys)[yield_column]
            .agg(yield_pct="mean", count="count")
            .reset_index()
        )
        overall = float(data[yield_column].mean())
    else:
        if not fail_column or fail_column not in data:
            raise ValueError(
                f"fail 컬럼 '{fail_column}'이 없습니다. fail_column이나 "
                "yield_column을 정하세요."
            )
        fails = data[fail_column].astype(float)
        table = (
            data.assign(_fail=fails)
            .groupby(keys)["_fail"]
            .agg(fail_rate="mean", count="count")
            .reset_index()
        )
        table["yield_pct"] = 100 * (1 - table.pop("fail_rate"))
        overall = float(100 * (1 - fails.mean()))
    table = table.sort_values("yield_pct").reset_index(drop=True)
    table["gap_to_overall"] = table["yield_pct"] - overall

    def row(r):
        return {k: str(r[k]) for k in keys} | {
            "yield_pct": round(float(r["yield_pct"]), 2)
        }

    out = {
        "data": table,
        "overall_yield": round(overall, 2),
        "lowest": row(table.iloc[0]),
        "highest": row(table.iloc[-1]),
    }
    print(
        f"yield_summary: overall={out['overall_yield']}% "
        f"lowest={out['lowest']} highest={out['highest']}"
    )
    return out
