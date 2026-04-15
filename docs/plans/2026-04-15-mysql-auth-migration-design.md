# MySQL Auth Migration Design

**Date:** 2026-04-15
**Scope:** Move authentication storage from SQLite `auth.db` to MySQL `doc-cloud`, remove random bootstrap passwords, and keep only five fixed accounts.

## 1. Goal

- Stop using SQLite for authentication entirely.
- Keep authentication data in the same MySQL database that already stores business data.
- Use exactly these five fixed accounts:
  - `gago-1 / 2aZ8gx-pbXQsxXv4Mf9Q`
  - `gago-2 / F_jGYw8BMhF@j&*bgp_A`
  - `gago-3 / 2A4Qt7miqT!xsnSv5gV2`
  - `gago-4 / %@5#=vgP=v%mb9LzK$Nh`
  - `gago-5 / 3*u8a4ph.Z&x+4gP5XvF`
- Preserve the current HTTP API:
  - `POST /auth/login`
  - `GET /auth/me`
  - `POST /auth/logout`

## 2. Chosen Approach

- Add two MySQL auth tables in `doc-cloud`:
  - `auth_user`
  - `auth_session`
- Introduce a MySQL-backed auth repository that matches the existing auth service contract.
- Replace the current SQLite auth bootstrap flow with a fixed in-code credential seed.
- Keep password hashing and token hashing logic unchanged.

## 3. Why This Design

- It matches the user's operational workflow because MySQL tables are visible in the existing database tools.
- It avoids dual writes and drift between SQLite and MySQL.
- It keeps the frontend unchanged because the HTTP contract stays the same.
- It keeps the backend migration small because only the auth persistence layer changes.

## 4. Table Design

### 4.1 `auth_user`

- `id BIGINT PRIMARY KEY AUTO_INCREMENT`
- `username VARCHAR(64) NOT NULL UNIQUE`
- `password_hash VARCHAR(255) NOT NULL`
- `password_salt VARCHAR(255) NOT NULL`
- `is_active TINYINT NOT NULL DEFAULT 1`
- `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- `updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`

### 4.2 `auth_session`

- `id BIGINT PRIMARY KEY AUTO_INCREMENT`
- `user_id BIGINT NOT NULL`
- `token_hash VARCHAR(255) NOT NULL UNIQUE`
- `created_at DATETIME NOT NULL`
- `expires_at DATETIME NOT NULL`
- `last_used_at DATETIME NOT NULL`
- Foreign key to `auth_user(id)`

## 5. Runtime Behavior

- On backend startup:
  - ensure MySQL business tables exist
  - ensure MySQL auth tables exist
  - upsert the five fixed users into `auth_user`
  - if a user already exists but has a different password hash, sync it to the fixed password
- During login:
  - load user from MySQL
  - verify password with the existing scrypt logic
  - create a MySQL-backed session row
- During `/auth/me`:
  - resolve token through `auth_session` and `auth_user`
- During logout:
  - delete the matching MySQL session

## 6. Migration Boundary

- SQLite `auth.db` becomes unused by runtime auth.
- No user data is migrated from SQLite because the target state is exactly the five fixed users.
- Existing frontend code and frontend deployment stay unchanged.

## 7. Verification

- Unit-test the MySQL auth repository through mocked SQL execution boundaries.
- Keep the existing auth service tests green against a fake repository and against the MySQL repo where practical.
- Verify live login on `ai.luyaxiang.com` after rollout.
