# MySQL Auth Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move backend authentication from SQLite to MySQL and lock credentials to five fixed accounts.

**Architecture:** Add a MySQL auth repository and tables alongside the existing business schema, then wire the existing `AuthService` to use that repository while removing random bootstrap-file auth from runtime startup.

**Tech Stack:** Python 3.11, unittest, MySQL CLI-backed repository, HTTPServer

---

### Task 1: Add failing tests for fixed credential bootstrap

**Files:**
- Modify: `tests/test_auth.py`

**Step 1: Write tests that describe the fixed seed credential behavior.**

**Step 2: Run `python3 -m unittest tests.test_auth` and verify the new tests fail for the right reason.**

**Step 3: Implement only the minimal fixed-credential helper needed by the tests.**

**Step 4: Re-run `python3 -m unittest tests.test_auth`.**

### Task 2: Add failing tests for MySQL auth repository behavior

**Files:**
- Create: `tests/test_mysql_auth_repository.py`

**Step 1: Write tests for MySQL auth table creation, user lookup, upsert, session creation, and session deletion.**

**Step 2: Mock SQL execution boundaries so the tests are deterministic and fast.**

**Step 3: Run `python3 -m unittest tests.test_mysql_auth_repository` and verify failure before implementation.**

### Task 3: Implement MySQL auth repository

**Files:**
- Modify: `src/doc_ai_agent/auth.py`
- Modify: `src/doc_ai_agent/mysql_repository.py`

**Step 1: Add fixed credential seed definitions.**

**Step 2: Add a MySQL-backed auth repository implementation with the same service-facing methods as the SQLite repository.**

**Step 3: Add MySQL auth DDL and seed support.**

**Step 4: Re-run the new auth repository tests.**

### Task 4: Switch runtime wiring from SQLite auth to MySQL auth

**Files:**
- Modify: `src/doc_ai_agent/server.py`
- Modify: `src/doc_ai_agent/config.py`
- Modify: `tests/test_http_auth.py`
- Modify: `tests/test_config.py`

**Step 1: Remove runtime dependence on `auth.db` and `auth-initial-credentials.txt`.**

**Step 2: Wire `AuthService` to the MySQL auth repository when `db_url` is configured.**

**Step 3: Keep the HTTP auth API contract unchanged.**

**Step 4: Run the targeted HTTP auth tests.**

### Task 5: Verify end to end

**Files:**
- No new repo file required

**Step 1: Run targeted auth/config tests.**

**Step 2: Restart the backend and verify live login with the five fixed credentials.**

**Step 3: Verify `POST /auth/login`, `GET /auth/me`, and `POST /auth/logout` against `ai.luyaxiang.com`.**
