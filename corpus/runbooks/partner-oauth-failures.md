# Runbook: partner-gateway OAuth failures

Symptoms: partner-gateway logs `401 invalid_token` or `invalid_client` from a carrier API, and tracking updates for that carrier stop.

## Diagnosis

- `invalid_client` means the client id or secret is wrong or was rotated by the carrier. Check the secret `partner-gateway/<carrier>` in the vault and compare its last rotation date with the carrier's notice.
- `invalid_token` on a request that used a fresh token usually means clock skew or a token cached past expiry. partner-gateway refreshes tokens 30 seconds before `expires_in`; confirm pod clocks with `kubectl exec ... -- date -u`.
- 429 responses mean the carrier's rate limit (most allow 60 requests per minute). partner-gateway backs off and honors `Retry-After`.

## Steps

1. Find the failing request in OpenSearch using its `X-Correlation-ID`.
2. If the secret was rotated, update the vault secret and restart: `kubectl rollout restart deploy/partner-gateway -n shipping`.
3. Send the carrier the correlation id and UTC timestamp if their side rejects a valid secret.

## Escalation

Sev 3 unless more than one carrier is affected, then Sev 2.
