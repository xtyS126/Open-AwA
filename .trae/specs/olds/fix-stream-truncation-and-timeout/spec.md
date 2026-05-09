# Fix Stream Truncation and Timeout Spec

## Why
When the model outputs very long content, the frontend SSE parser drops chunks across network boundaries resulting in stream truncation, and the hardcoded max_tokens (1000) causes premature generation cutoff. The timeout is also too short (30s) for long reasoning.

## What Changes
- Add `max_tokens` field to `ModelConfiguration` and database schema.
- Update frontend settings page to configure `max_tokens` per provider.
- Read `max_tokens` in `_resolve_llm_configuration` and use it in `_call_llm_api_stream`.
- Increase `ProviderRequestSpec` timeout to 120.0 seconds.
- Implement a string buffer in `api.ts` `sendMessageStream` to handle incomplete SSE chunks.

## Impact
- Affected code: `backend/billing/models.py`, `backend/billing/pricing_manager.py`, `backend/api/schemas.py`, `backend/core/executor.py`, `backend/core/model_service.py`, `frontend/src/shared/api/api.ts`, `frontend/src/features/settings/SettingsPage.tsx`, `frontend/src/features/settings/modelsApi.ts`.