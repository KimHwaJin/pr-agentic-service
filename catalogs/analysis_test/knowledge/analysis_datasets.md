---
name: analysis_datasets
description: 분석에 쓰는 데이터 4종(NCE, WT, FDC, 수율)의 컬럼, 키, LOT·설비·기간 범위를 설명하는 도메인 지식. 어떤 데이터를 불러올지, 어떻게 결합할지 정할 때 사용한다.
---

# 분석 데이터 안내

모든 데이터는 `data_load` skill의 `load_synthetic`으로 불러온다.

## NCE (`data_type="nce"`)
- die 단위 공정 마스크 측정값. 행 = LOT × 웨이퍼 × die.
- 키: `alias_lot_id`(L1~L6), `wf_id`(W01~W04), `x`, `y`(1~21, 원형 wafer).
- 측정 컬럼 10개: `<공정> MASK MACRO.max_val` (BLC(CELL) OPEN, DNW, ISO(PERI)+CUT, M4C, MBO, P+ADD, PMX, REP, SN OPEN, SNC PARTITION).
- `process` 조건은 공정 이름 앞부분으로 측정 컬럼을 고른다.

## WT (`data_type="wt"`)
- die 단위 전기 테스트 결과. 키는 NCE와 같다.
- `PT1H.p_f`(1 = fail), `PT1H.symbol`(PASS 또는 bin 코드), `PT1H.end_tm`.

## FDC (`data_type="fdc"`)
- 설비·챔버별 시간당 센서값. 2026-09-01 ~ 2026-09-30.
- 키: `timestamp`, `eqp_id`(ETCH_A, ETCH_B), `chamber_id`(CH1, CH2).
- 센서: `CH_PRESSURE`(mTorr), `CH_TEMP`(°C), `RF_POWER`(W), `GAS_FLOW`(sccm).
- `process` 조건은 설비(eqp_id), `start_dt`·`end_dt`는 기간.

## 수율 (`data_type="yield"`)
- LOT·웨이퍼별 수율과 공정 조건. LOT은 YL01~YL40 (NCE·WT LOT과 다름).
- 컬럼: `eqp_id`(거친 식각 설비), `chamber_id`, `avg_pressure`, `avg_temp`, `rf_power`, `cd_mean`, `yield_pct`(%).

## 결합
- NCE와 WT는 `alias_lot_id`, `wf_id`, `x`, `y`로 결합한다.
- FDC·수율은 die 좌표가 없어 wafer map 분석에 쓸 수 없다.
