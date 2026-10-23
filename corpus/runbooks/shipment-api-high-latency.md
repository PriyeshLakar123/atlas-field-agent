# Runbook: shipment-api high latency

Alert: `ShipmentApiP99High` fires when p99 latency on shipment-api is above 800 ms for 10 minutes.

## Triage

1. Open the Grafana dashboard "shipment-api / Latency" and check whether latency is high on all routes or only `GET /shipments/{id}/tracking`.
2. If only the tracking route is slow, check MongoDB first: in Atlas, open Query Insights for the `shipping.shipments` namespace and look for queries with a `COLLSCAN` plan or examined to returned ratio above 100.
3. If all routes are slow, check pod CPU with `kubectl top pods -n shipping`. Sustained CPU above 85% means the deployment needs to scale.

## Mitigation

- Missing index: a query on `carrierId` and `status` without `updatedAt` sort can fall back to a collection scan. Confirm with `explain("executionStats")` and add the index during low traffic; do not build indexes on prod during peak hours (14:00 to 18:00 UTC).
- CPU saturation: scale with `kubectl scale deploy/shipment-api -n shipping --replicas=10`. The HPA maximum is 12 replicas.
- If latency started right after a deploy, follow the deploy rollback runbook instead of tuning.

## Escalation

If p99 stays above 800 ms for 30 minutes after mitigation, page the Platform team (Sev 2).
