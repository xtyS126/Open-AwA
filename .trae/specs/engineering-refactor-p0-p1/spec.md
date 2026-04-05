# Engineering Refactoring (P0/P1) Spec

## Why
This system has grown into a powerful platform, yet portions of its implementation retain experimental traits. The primary issue is a lack of clear boundaries, with varying implementation depth and engineering maturity. Addressing the P0 (Global Singleton AIAgent, Production Auto-Login, Bloated Routing) and P1 (Raw Text Structured Data Models, Dual-Channel Request Inconsistency) issues will resolve immediate data pollution, security, and maintenance risks.

## What Changes
- **BREAKING**: Removed the global singleton `agent` from `chat.py`. Each HTTP request and WebSocket connection will now instantiate its own short-lived execution context and `AIAgent`.
- **BREAKING**: Replaced long-lived `self._db_session = SessionLocal()` inside `AIAgent` with explicitly injected database sessions (`Session` dependency in routers), eliminating concurrent request contamination.
- Refactored `chat.py` to extract SSE streaming protocol, WebSocket connection management, and chunking into a separate `protocol` service layer, making the routing layer lightweight.
- Modified frontend `App.tsx` initialization to ensure automatic registration and login of `test_user_default` occurs strictly in the development environment (`import.meta.env.DEV`).
- Updated high-frequency structured fields (e.g., `config`, `tags`, `dependencies`, `details`, `llm_input`, `llm_output`) in `db/models.py` from `Text` to `JSON` types to improve queryability and standardization.
- Unified frontend streaming and non-streaming request channels. The `chatAPI.sendMessageStream` in `api.ts` will now ensure it correctly injects `X-Request-Id`, headers, and authorization using interceptor-like logic.

## Impact
- Affected specs: Chat execution flow, WebSockets, API request layer, App initialization.
- Affected code:
  - `backend/core/agent.py`
  - `backend/api/routes/chat.py`
  - `backend/db/models.py`
  - `frontend/src/App.tsx`
  - `frontend/src/shared/api/api.ts`

## ADDED Requirements
### Requirement: Short-Lived Contexts
The backend SHALL execute AI operations using short-lived contexts.
#### Scenario: High concurrency
- **WHEN** multiple users invoke chat operations concurrently
- **THEN** they receive independent `AIAgent` instances and database sessions, preventing context bleeding or database lock contention.

## MODIFIED Requirements
### Requirement: Frontend Initialization
- **WHEN** the application initializes in a production environment
- **THEN** it SHALL NOT automatically register or login the `test_user_default` test account.

### Requirement: Database Models
- **WHEN** structured fields are saved or queried
- **THEN** they SHALL be treated as standard JSON documents natively handled by the ORM mapping to database JSON features.

### Requirement: Chat Request Protocol
- **WHEN** initiating a streaming chat response
- **THEN** it SHALL construct request headers identically to standard axios interceptors, including request IDs and authentication headers.
