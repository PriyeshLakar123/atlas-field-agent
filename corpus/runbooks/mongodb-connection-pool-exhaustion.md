# Runbook: MongoDB connection pool exhaustion

Symptoms: services log `MongoWaitQueueTimeoutError` or `connection pool cleared`, and requests fail with 503s. Atlas shows connections near the cluster limit (M50 limit is 16,000).

## Common causes

- A deploy raised `maxPoolSize` per pod and the replica count was also increased, so total connections = replicas x maxPoolSize grew past the limit.
- A slow query holds connections longer than usual, so the pool drains even though traffic is normal.
- Connection leaks in route-optimizer when a worker crashes without closing its client.

## Steps

1. In Atlas Metrics, check the Connections chart for the last 6 hours and note when the climb started.
2. Compare with deploy history: `kubectl rollout history deploy -n shipping`.
3. Check the configured pool size. Northwind standard is `maxPoolSize=50` and `waitQueueTimeoutMS=2000` for shipment-api. Any value above 100 must be reverted.
4. If route-optimizer is the source, restart it with `kubectl rollout restart deploy/route-optimizer -n shipping`.
5. Do not raise the Atlas tier as a first response. It hides the leak and costs more.

## Escalation

Sev 1 if checkout of new shipments is failing for more than 5 minutes.
