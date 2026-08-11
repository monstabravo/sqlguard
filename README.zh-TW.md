# sqlguard

[![CI](https://github.com/monstabravo/sqlguard/actions/workflows/ci.yml/badge.svg)](https://github.com/monstabravo/sqlguard/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)

[English](README.md)

**用 AST 解析來確保一段 SQL 只能讀、不可能寫。**

只要有東西會對正式環境產出 SQL——BI 工具、內部查詢平台、LLM 都算——你就需要一個「它不可能寫入」的保證。`sqlguard` 是把語句**解析成語法樹**來給這個保證，不是拿關鍵字去比對字串。

```python
from sqlguard import assert_select_only, ReadOnlyViolation

assert_select_only("SELECT id FROM users")           # 通過
assert_select_only("DELETE FROM users")              # 拋出 ReadOnlyViolation
```

## 為什麼不能只比對字串

所有靠關鍵字比對的檢查都長同一個樣子：找 `DELETE`、`UPDATE`、`DROP`，沒找到就放行。以下三種寫法可以直接走過去：

```sql
-- 兩個語句，第一個是無害的查詢
SELECT * FROM users; DELETE FROM users

-- 根節點是 SELECT，寫入藏在 CTE 裡面
WITH x AS (DELETE FROM users RETURNING id) SELECT * FROM x

-- 用註解把 payload 藏過逐行掃描
SELECT * FROM users; -- 無害
DROP TABLE users
```

解析器看到的是事實：兩個語句、一個會改資料的 CTE、一個 `DROP`。沒有任何正則表達式能穩定得到同樣的結論——真要寫到那個程度，等於在寫一個很爛的 SQL 解析器。

`sqlguard` 用 [sqlglot](https://github.com/tobymao/sqlglot) 建出 AST，然後做四道檢查：

1. **能否解析** — 解析不了就代表無法背書，直接拒絕（fail closed）。
2. **必須恰好一個語句** — 在計數這關就擋掉多語句 payload，不必去判斷第 2..n 個語句是否剛好無害。
3. **根節點必須是查詢** — `SELECT` / `UNION` / `INTERSECT` / `EXCEPT` 白名單。沒認出來的節點型別**拒絕**而不是放行。
4. **每個 CTE 內容都必須是查詢** — 遞迴檢查，所以巢狀藏不住。

## 跟其他做法的比較

| | 關鍵字／regex 檢查 | `sqlparse` token 掃描 | 資料庫唯讀權限 | **sqlguard** |
|---|:-:|:-:|:-:|:-:|
| 擋得住 `INSERT` / `UPDATE` / `DELETE` | ✅ | ✅ | ✅ | ✅ |
| 擋得住多語句夾帶（`SELECT …; DELETE …`）| ❌ | ⚠️ 得自己切語句 | ✅ | ✅ |
| 擋得住藏在 CTE 裡的寫入（`WITH x AS (DELETE …) SELECT …`）| ❌ | ❌ | ✅ | ✅ |
| 擋得住註解／大小寫／空白的規避手法 | ❌ | ✅ | ✅ | ✅ |
| 解析不了就拒絕（fail closed）| ❌ | ❌ | 不適用 | ✅ |
| 用白名單而非黑名單，沒認出的語句型別一律拒絕 | ❌ | ❌ | ✅ | ✅ |
| 在查詢送出網路**之前**就攔下 | ✅ | ✅ | ❌ | ✅ |
| 回得出可以直接顯示給呼叫端的訊息 | ⚠️ 語焉不詳 | ⚠️ 語焉不詳 | ❌ 只有 driver 錯誤 | ✅ 明講拒絕原因 |
| 需要另外開一組資料庫帳號／請 DBA 改權限 | — | — | ✅ 必須 | ❌ 不需要 |

資料庫唯讀權限才是強度最高的那道防線，該有還是要有。
`sqlguard` 是更早、更便宜、而且講得清楚的那一層 —— 而且在你**拿不到**第二組資料庫帳號的
情況下（共用的資料倉儲憑證、廠商 API、託管的連線池）也一樣能用。

**最穩的組合是兩者並用。**

## 安裝

```bash
pip install sqlglot   # 唯一依賴
```

之後把 `src/sqlguard/` 併進你的專案，或從原始碼安裝：

```bash
pip install .
```

## 使用方式

### 放在邊界上強制執行

把這道檢查放在 SQL 離開你的程式、準備送往資料庫的那個點上，每條查詢路徑呼叫一次，沒有例外：

```python
from sqlguard import assert_select_only

def run_query(sql: str, dialect: str = "mysql"):
    assert_select_only(sql, dialect=dialect)   # 在任何東西執行之前就拋出
    return connection.execute(sql)
```

### 布林版本

```python
from sqlguard import is_select_only

if not is_select_only(user_sql, dialect="postgres"):
    return {"error": "只接受唯讀查詢"}
```

### 方言

傳入目標引擎實際使用的方言：

```python
assert_select_only("SELECT `id` FROM `users`", dialect="mysql")       # 反引號識別字
assert_select_only("SELECT id FROM t QUALIFY ...", dialect="databricks")
```

用正確的解析器是**正確性，不是繞過**——四道檢查在任何方言下都照跑。用**錯**的解析器才會製造漏洞：合法語法可能解析失敗，或更糟，解析成你沒預期的形狀。傳入不存在的方言名稱會拋出 `ReadOnlyViolation`，不會默默退回預設值。

## 防得住什麼、防不住什麼

**防得住**：語句層級的變更——DML（`INSERT`/`UPDATE`/`DELETE`/`MERGE`/`TRUNCATE`）、DDL（`CREATE`/`ALTER`/`DROP`）、DCL（`GRANT`/`REVOKE`）、多語句 payload，以及藏在 CTE 裡的寫入。

**防不住**：資料列層級授權、欄位遮罩、資源耗盡（一個 `SELECT` 照樣能把資料倉儲整表掃過去），以及使用者自訂函式內部的副作用。這是**一層**防禦，它搭配而不是取代「只有 `SELECT` 權限的資料庫帳號」。

最穩的配置是兩者並存：最小權限帳號負責真正的強制，`sqlguard` 負責早一步擋下來——查詢還沒碰到網路就被拒絕，而且拒絕的理由講得清楚到可以直接回給呼叫端。

## 測試

```bash
pip install pytest sqlglot
PYTHONPATH=src python -m pytest tests/ -q
```

28 個測試。其中一半是繞過嘗試（`tests/test_guard.py`）——多語句 payload、藏在 CTE（含巢狀）裡的寫入、註解繞過、大小寫與空白花招、無法解析的輸入。

## 背景

只要一個服務把查詢入口攤開到不只一個資料源上，遲早會碰到同一個要求：**這些路徑都不能寫入**。
一般的解法是加一道關鍵字檢查，而一般的結局是——它撐得住，直到有人送出兩個語句，
或者把寫入塞進 CTE 裡。

`sqlguard` 就是那道檢查認真做出來的版本：小到可以一次讀完、嚴格到講得出它保證什麼，
而且對它**做不到**的部分同樣誠實。

## 授權

MIT
