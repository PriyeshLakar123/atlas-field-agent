# Runbook: deploy rollback

Use this when an alert starts within 30 minutes of a deploy.

## Steps

1. Confirm the timing: `kubectl rollout history deploy/<service> -n shipping`.
2. Roll back: `kubectl rollout undo deploy/<service> -n shipping`.
3. Watch the service dashboard for 10 minutes to confirm recovery.
4. Open a ticket linking the bad release and the alert, and tag the owning team.

Database schema migrations are never rolled back automatically. If the release included a migration, page the owning team before rolling back.
