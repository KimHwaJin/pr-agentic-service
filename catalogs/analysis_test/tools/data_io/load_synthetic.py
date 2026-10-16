def load_synthetic(
    data_type: str,
    lot_cd: list | str | None = None,
    process: list | str | None = None,
    start_dt: str | None = None,
    end_dt: str | None = None,
    limit: int | None = None,
) -> dict:
    """시험용 합성 데이터를 조건대로 만들어 wide 분석 형식으로 불러옵니다.

    같은 조건이면 항상 같은 데이터가 나옵니다(고정 seed).

    Args:
        data_type: 데이터 유형. "nce"(공정 마스크 측정), "wt"(웨이퍼 테스트),
            "fdc"(설비 센서 시계열), "yield"(LOT·웨이퍼 수율)
        lot_cd: LOT 코드 또는 목록 (nce·wt: L1~L6, yield: YL01~YL40)
        process: nce는 공정 이름(예: "SN OPEN") 또는 목록, fdc·yield는
            설비(ETCH_A, ETCH_B)
        start_dt: fdc 시작일 (YYYY-MM-DD, 2026-09-01 ~ 2026-09-30)
        end_dt: fdc 종료일 (YYYY-MM-DD)
        limit: 최대 행 수

    Returns:
        {"data": pandas.DataFrame, "shape": list, "query": dict}
    """
    import numpy as np
    import pandas as pd

    kind = str(data_type).lower()
    if kind not in {"nce", "wt", "fdc", "yield"}:
        raise ValueError(
            f"data_type '{data_type}'은 지원하지 않습니다. "
            "nce, wt, fdc, yield 중 하나를 쓰세요."
        )
    rng = np.random.default_rng(20261016)

    # die grid shared by nce and wt: 6 lots x 4 wafers x round wafer
    lots = [f"L{i}" for i in range(1, 7)]
    wafers = [f"W{i:02d}" for i in range(1, 5)]
    grid = [
        (x, y)
        for x in range(1, 22)
        for y in range(1, 22)
        if (x - 11) ** 2 + (y - 11) ** 2 <= 100
    ]
    keys = pd.DataFrame(
        [(lot, w, x, y) for lot in lots for w in wafers for (x, y) in grid],
        columns=["alias_lot_id", "wf_id", "x", "y"],
    )
    n = len(keys)
    edge = (
        np.sqrt((keys["x"] - 11) ** 2 + (keys["y"] - 11) ** 2) / 10 > 0.8
    ).to_numpy()
    names = [
        "BLC(CELL) OPEN",
        "DNW",
        "ISO(PERI)+CUT",
        "M4C",
        "MBO",
        "P+ADD",
        "PMX",
        "REP",
        "SN OPEN",
        "SNC PARTITION",
    ]
    common = rng.normal(0, 1, n)
    pair = rng.normal(0, 1, n)
    nce = keys.copy()
    sn_z = None
    for i, name in enumerate(names):
        own = rng.normal(0, 1, n)
        if name in ("DNW", "MBO"):
            z = 0.55 * common + 0.75 * pair + 0.37 * own
        else:
            z = 0.55 * common + 0.835 * own
        if name == "SN OPEN":
            sn_z = z
        nce[f"{name} MASK MACRO.max_val"] = 2.0 + 0.12 * i + 0.144 * z
    lot3 = (nce["alias_lot_id"] == "L3").to_numpy()
    nce.loc[lot3, "SN OPEN MASK MACRO.max_val"] += 0.3

    if kind == "nce":
        frame = nce
        missing = rng.choice(n, size=n // 100, replace=False)
        frame.loc[frame.index[missing], "PMX MASK MACRO.max_val"] = np.nan
        dupes = rng.choice(n, size=n // 200, replace=False)
        frame = pd.concat([frame, frame.iloc[dupes]], ignore_index=True)
    elif kind == "wt":
        assert sn_z is not None
        p_fail = 0.12 + 0.14 * edge + 0.10 * (sn_z > 1)
        fail = rng.random(n) < p_fail
        bins = rng.choice(["B07", "B12", "B21", "B33"], size=n)
        frame = keys.copy()
        frame["PT1H.p_f"] = fail.astype("int8")
        frame["PT1H.symbol"] = np.where(fail, bins, "PASS")
        frame["PT1H.end_tm"] = pd.Timestamp("2026-09-20") + pd.to_timedelta(
            rng.integers(0, 72 * 3600, n), unit="s"
        )
    elif kind == "fdc":
        times = pd.date_range("2026-09-01", periods=30 * 24, freq="h")
        rows = []
        for eqp in ("ETCH_A", "ETCH_B"):
            for chamber in ("CH1", "CH2"):
                m = len(times)
                hours = np.arange(m)
                pressure = 50 + rng.normal(0, 0.5, m)
                if eqp == "ETCH_B":
                    drift_from = np.asarray(times >= "2026-09-18")
                    since = np.cumsum(drift_from) * drift_from
                    pressure = pressure + 0.01 * since
                rows.append(
                    pd.DataFrame(
                        {
                            "timestamp": times,
                            "eqp_id": eqp,
                            "chamber_id": chamber,
                            "CH_PRESSURE": pressure,
                            "CH_TEMP": 65
                            + 1.5 * np.sin(2 * np.pi * hours / 24)
                            + rng.normal(0, 0.3, m),
                            "RF_POWER": 1200 + rng.normal(0, 15, m),
                            "GAS_FLOW": 200 + rng.normal(0, 3, m),
                        }
                    )
                )
        frame = pd.concat(rows, ignore_index=True)
        bad = rng.choice(len(frame), size=6, replace=False)
        frame.loc[frame.index[bad], "GAS_FLOW"] = -1.0
    else:  # yield
        lot_ids = [f"YL{i:02d}" for i in range(1, 41)]
        frame = pd.DataFrame(
            [(lot, w) for lot in lot_ids for w in wafers],
            columns=["alias_lot_id", "wf_id"],
        )
        m = len(frame)
        route_b = np.repeat(rng.random(len(lot_ids)) < 0.5, len(wafers))
        frame["eqp_id"] = np.where(route_b, "ETCH_B", "ETCH_A")
        frame["chamber_id"] = rng.choice(["CH1", "CH2"], size=m)
        frame["avg_pressure"] = 50 + rng.normal(0, 0.6, m) + 1.0 * route_b
        frame["avg_temp"] = 65 + rng.normal(0, 0.4, m)
        frame["rf_power"] = 1200 + rng.normal(0, 12, m)
        frame["cd_mean"] = 45 + rng.normal(0, 0.8, m)
        frame["yield_pct"] = (
            92
            - 4.0 * route_b
            - 1.5 * (frame["avg_pressure"] - 50)
            + rng.normal(0, 1.2, m)
        ).clip(0, 100)

    if lot_cd is not None and "alias_lot_id" in frame:
        wanted = [lot_cd] if isinstance(lot_cd, str) else list(lot_cd)
        frame = frame[frame["alias_lot_id"].isin(wanted)]
    if process is not None:
        wanted = [process] if isinstance(process, str) else list(process)
        if kind == "nce":
            keep = [
                c
                for c in frame.columns
                if not c.endswith(".max_val")
                or any(c.startswith(p) for p in wanted)
            ]
            frame = frame[keep]
        elif "eqp_id" in frame:
            frame = frame[frame["eqp_id"].isin(wanted)]
    if kind == "fdc" and start_dt:
        frame = frame[frame["timestamp"] >= pd.Timestamp(start_dt)]
    if kind == "fdc" and end_dt:
        frame = frame[
            frame["timestamp"] < pd.Timestamp(end_dt) + pd.Timedelta(days=1)
        ]
    if limit:
        frame = frame.head(int(limit))
    frame = frame.reset_index(drop=True)
    query = {
        "data_type": kind,
        "lot_cd": lot_cd,
        "process": process,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "limit": limit,
    }
    print(f"load_synthetic: {query} -> shape={frame.shape}")
    return {"data": frame, "shape": list(frame.shape), "query": query}
