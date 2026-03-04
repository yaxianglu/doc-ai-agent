# AI Agent MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a runnable AI-agent MVP that supports evidence-backed data Q&A from exported reports and advisory responses.

**Architecture:** The system ingests XLSX report data into SQLite, routes user questions to either a controlled SQL query engine or an advisory engine, and serves results via HTTP endpoints. Query answers always include evidence metadata.

**Tech Stack:** Python 3.9, stdlib (`sqlite3`, `zipfile`, `xml.etree`, `http.server`, `unittest`)

---

### Task 1: Project scaffold and config

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/doc_ai_agent/__init__.py`
- Create: `src/doc_ai_agent/config.py`

**Step 1: Write the failing test**
- Test loading default config values and overrides.

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest tests/test_config.py -v`

**Step 3: Write minimal implementation**
- Add config dataclass and env loading.

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest tests/test_config.py -v`

### Task 2: XLSX ingestion and parsing

**Files:**
- Create: `src/doc_ai_agent/xlsx_loader.py`
- Test: `tests/test_xlsx_loader.py`

**Step 1: Write the failing test**
- Parse provided xlsx and assert row extraction for required fields.

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest tests/test_xlsx_loader.py -v`

**Step 3: Write minimal implementation**
- Implement sharedStrings + sheet xml parsing and normalized row mapping.

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest tests/test_xlsx_loader.py -v`

### Task 3: Persistence layer

**Files:**
- Create: `src/doc_ai_agent/repository.py`
- Test: `tests/test_repository.py`

**Step 1: Write the failing test**
- Insert alert rows and verify count/top queries.

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest tests/test_repository.py -v`

**Step 3: Write minimal implementation**
- Add schema init, upsert/insert, aggregation methods.

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest tests/test_repository.py -v`

### Task 4: Query and advice engines

**Files:**
- Create: `src/doc_ai_agent/query_engine.py`
- Create: `src/doc_ai_agent/advice_engine.py`
- Create: `src/doc_ai_agent/agent.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**
- Validate routing for “多少条” and “top5” and advisory prompts.

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest tests/test_agent.py -v`

**Step 3: Write minimal implementation**
- Implement intent routing + SQL-backed responses + advisory rules.

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest tests/test_agent.py -v`

### Task 5: HTTP API

**Files:**
- Create: `src/doc_ai_agent/server.py`
- Create: `scripts/run_server.py`
- Test: `tests/test_server.py`

**Step 1: Write the failing test**
- Validate `/health`, `/refresh`, `/chat` responses.

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest tests/test_server.py -v`

**Step 3: Write minimal implementation**
- Add HTTP handler and app wiring.

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest tests/test_server.py -v`

### Task 6: End-to-end verification

**Files:**
- Modify: `README.md`

**Step 1: Run full verification**
- Run: `python3 -m unittest discover -s tests -v`

**Step 2: Manual smoke command**
- Run: `python3 scripts/run_server.py`
- Call endpoints with curl.

**Step 3: Document runbook**
- Add setup/run/API examples.
