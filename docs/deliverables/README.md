# 개발 산출물

기준: master 브랜치, 2026-11-27. 문서 본문은 Markdown, 목록과 정의서는 Excel, 그림 원본은 Draw.io입니다.

| 번호 | 산출물 | 파일 | 그림 원본 |
| --- | --- | --- | --- |
| 1 | 전체 시스템 구성도 | `01-system-architecture.md` | `diagrams/01-system-architecture.drawio` |
| 2 | 프로그램 목록 (Agent workflow) | `02-program-list.xlsx` | `diagrams/02-agent-workflow.drawio` |
| 3 | 프로그램 명세서 (Agent Graph) | `03-program-spec.md` | `diagrams/03-agent-graph.drawio` |
| 4 | 논리 ERD | `04-erd-logical.md` | `diagrams/04-erd-logical.drawio` |
| 5 | 물리 ERD | `05-erd-physical.md` | `diagrams/05-erd-physical.drawio` |
| 6 | Table 정의서 (RDB, Vector 저장소) | `06-table-definition.xlsx` | |
| 7 | 사용자 메뉴얼 | `07-user-manual.md` | `diagrams/07-user-flow.drawio` |
| 8 | 운영자 메뉴얼 | `08-operator-manual.pptx` (공식 양식, PPT). 상세 원문은 `08-operator-manual.md` | `diagrams/08-ops-flow.drawio`, `diagrams/09-ops-sw-interface.drawio` |

- `diagrams/export/`는 그림의 PNG, SVG 미리보기입니다. 문서 본문은 이 PNG를 참조합니다.
- `tools/`는 그림과 Excel을 만든 스크립트입니다. ERD와 Table 정의서는 `docs/handover/03-db-physical.md`를 읽어 만듭니다.
- 운영자 메뉴얼 PPT는 `tools/build_ops_pptx.js`로 만듭니다(pptxgenjs).
- 사용자 메뉴얼의 `[화면 그림 n]`은 실제 화면을 찍어 넣을 자리입니다.
