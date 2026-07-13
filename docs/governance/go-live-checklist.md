# VITA Go-Live 前剩餘勾選清單

Version: 1.6 (HSS D3 rollback drill complete)  
Date: 2026-07-12  
Baseline: develop @ `9012c91`（HSS D3 rollback + 2.1/2.2 fire test）  
權威來源: [execution-program.md](execution-program.md) exit criteria、[governance-matrix.md](governance-matrix.md)、[RACI.md](RACI.md)  
用途: 列出「repo 工程已完成、但 go-live 前仍須完成」之營運與組織項目，逐項標記 **Accountable（A）** 負責角色。

## 負責角色（對齊 RACI）

實名 roster 存於外部加密儲存（見 [RACI.md § Named roles](RACI.md#named-roles)），本清單只用角色代號。

| 代號 | 角色 | RACI 外部欄位 |
|------|------|---------------|
| PO | Product owner | `product_owner` |
| ENG | Engineering lead | `engineering_lead` |
| CLIN | Clinical advisor | `clinical_advisor` |
| OPS | Operations / on-call primary | `on_call_primary` |

**A** = Accountable（最終負責、簽核），**R** = Responsible（實際執行）。下表 Owner 欄填 **A**。

---

## 0. 前置：實名 roster 與分支保護

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 0.1 | 填入外部 roster（PO/ENG/CLIN/OPS 實名 + 聯絡） | 11 | PO | ENG | RACI 外部欄位 `OPS-ROSTER-001`；`RACI.md` 指向該 ID | 未完成 |
| 0.2 | GitHub branch protection（main/develop：PR review + CI 必過） | 7 | ENG | ENG | [github-setup-c-zone.md](../operations/github-setup-c-zone.md) C1 + 外部 BP-RECORD | **部分** — repo 驗證就緒；GitHub UI 待 ENG |
| 0.3 | Release tag 流程 formalize（語意版號 + 標記規則） | 7 | ENG | ENG | `branch-strategy.md` 附錄 + RC tags | **完成** — `v1.0.0-rc.1` / `rc.2` / `rc.3` |

---

## 1. CI/CD 與部署（staging 實跑）

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 1.1 | 設定 GitHub Encrypted Secrets（DB/JWT/ENCRYPT/API + `DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_PATH`/`DEPLOY_KEY`） | 8 | ENG | OPS | [github-setup-c-zone.md](../operations/github-setup-c-zone.md) C2 + SEC-RECORD | **部分** — 契約驗證在 CI；密鑰值待 GitHub UI |
| 1.2 | deploy workflow `environment=staging`, `dry_run=true` | 8 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D1 + run URL | **完成** — Deploy #8 @ `c6888b6`（build-and-smoke 綠；deploy-host 跳過） |
| 1.3 | deploy workflow `dry_run=false`（staging 真部署） | 8 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D2 + smoke pass | **部分** — host bootstrap 文件化；實跑待 OPS |
| 1.4 | Rollback 演練並記錄 | 8 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D3 + `DEP-DRILL-*` | **完成** — `DEP-DRILL-2026-07-003` HSS local；`latest` -> `drill-before` smoke pass |
| 1.5 | 關閉或展延 TD-009（deploy host registry） | 12 | PO | ENG | `tech-debt-register.md` 更新（關閉或帶到期日 waiver） | **完成** — Closed B-go-live |

---

## 2. 監控與告警（staging live）

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 2.1 | Staging Grafana / VictoriaMetrics / vita-api `/metrics` 持續 UP | 9 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D4 + scrape UP 記錄 | **完成** — HSS `D:\vita`；`verify_p5_monitoring.py` 全綠（2026-07-11） |
| 2.2 | 臨床告警 fire test（注入 missed log 觸發） | 9 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D4 + 告警截圖 | **完成** — `FIRE-DRILL-2026-07-001`；VMUI LogsQL `missed=1`（2026-07-12） |
| 2.3 | Escalation webhook live drill（非 dry-run） | 9 / 10 | OPS | ENG | [deploy-d-zone.md](../operations/deploy-d-zone.md) D4 + 送達證明 | **部分** — drill 腳本就緒；live 待 OPS |
| 2.4 | steady-state：missed-interception 7 日 = 0 | 9 | OPS | ENG | [mon-steady-state-7d.md](../operations/mon-steady-state-7d.md) + `record_mon_steady_state.py` 7 日記錄 | **部分** — 記錄腳本就緒；Day 0/7 待 OPS 每日執行 |

---

## 3. 異狀除錯與演練

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 3.1 | Tabletop S2（語言退化）演練 < 30 min | 10 | OPS | ENG + CLIN | `tabletop-s2-language-regression.md` 外部演練記錄 | 未完成 |
| 3.2 | On-call 值班表啟用（實名輪值） | 10 | OPS | OPS | `on-call.md` 指向外部 roster；首週輪值確認 | 未完成 |

---

## 4. 資安與資料

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 4.1 | Staging 金鑰輪替演練並記錄 | 4 | ENG | OPS | `key-rotation-runbook.md` 執行記錄 | 未完成 |
| 4.2 | Retention 排程營運 dry-run 記錄 | 3 | ENG | OPS | `retention_batch.py` + pg_cron dry-run 記錄 | 未完成 |
| 4.3 | `DELETE /user/{id}` 抹除 API（依資料分級 cascade） | 3 | ENG | ENG | API 實作 + 測試 | **完成** — `user_erasure.py` + tests |

---

## 5. 效能

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 5.1 | 生產 / staging p95 延遲基線量測，寫回 `slo.md` | 5 | ENG | ENG | `slo.md` 補實測 baseline | 未完成 |
| 5.2 | 危機路徑 SLO 標籤（全鏈路） | 2 / 5 | ENG | ENG | safety-critical-path 標註 SLO | **完成** |

---

## 6. 需求與臨床簽核（外部真人）

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 6.1 | 臨床顧問完成 PRD v1.0 審閱清單（SC-001..010） | 1 | CLIN | CLIN | 外部 `prd-v1-clinical-approval-checklist.md` 全勾 `CLIN-SIGN-PRD-v1-001` | 未完成 |
| 6.2 | 首次 production release 臨床簽核歸檔 | 11 | CLIN | ENG | `clinical-signoff-template.md` 填妥並與 release 一併歸檔（P6-1.4） | 未完成 |

---

## 7. 測試品質門檻（可 go-live 後強化）

| # | 項目 | 治理項 | Owner (A) | 執行 (R) | 產出 / 驗收 | 狀態 |
|---|------|--------|-----------|----------|-------------|------|
| 7.1 | 關鍵路徑覆蓋率門檻（clinical / safety） | 6 | ENG | ENG | CI coverage gate | **完成** — `app/clinical` >= 70% + SC/hub functional tests |

---

## Go-Live 判定門檻（Gate）

**必須全綠才可 production（阻斷項）：**

- 第 0 節（roster、branch protection）
- 第 1 節 1.1–1.4（staging deploy + rollback 實跑）
- 第 2 節（監控 live + 告警 + escalation）
- 第 3 節（tabletop + on-call）
- 第 4 節 4.1–4.2（金鑰輪替、retention dry-run）
- 第 6 節（PRD 臨床簽核 + release 歸檔）

**可帶 waiver 進 production（非阻斷，需 PO 核准並登記到期日）：**

- 5.1（生產 p95 基線量測 — staging/生產量測待補）

---

## 簽核會議（全綠後）

對齊 [governance-matrix.md](governance-matrix.md#master-驗證清單12-項全綠前必跑) 議程：

1. 走查 traceability matrix（ENG）
2. 開放 TD 審查：High = 0 或 waiver（PO）
3. Staging deploy + rollback 示範（OPS）
4. Grafana + 臨床告警 fire + webhook drill（OPS）
5. RACI 外部 roster + PRD 臨床簽核 + release 歸檔備查（CLIN）

**放行決議：** PO（產品）+ ENG（工程）+ CLIN（臨床）三方 Accountable 簽字。

---

## 相關文件

- [execution-program.md](execution-program.md) — 階段路線圖與 exit criteria（權威）
- [governance-matrix.md](governance-matrix.md) — 12 項治理計分
- [RACI.md](RACI.md) — 角色與外部 roster
- [tech-debt-register.md](tech-debt-register.md) — TD/CD 登記（TD-009 開）
- [../operations/deploy.md](../operations/deploy.md) — 部署與 rollback 演練
- [../operations/github-setup-c-zone.md](../operations/github-setup-c-zone.md) — branch protection + Encrypted Secrets（C-zone）
- [../operations/deploy-d-zone.md](../operations/deploy-d-zone.md) — staging deploy + monitoring drills（D-zone）
- [prd-v1-clinical-approval-checklist.md](prd-v1-clinical-approval-checklist.md) — PRD 臨床簽核
