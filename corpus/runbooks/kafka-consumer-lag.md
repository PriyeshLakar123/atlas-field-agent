# Runbook: events-pipeline consumer lag

Alert: `EventsPipelineLagHigh` fires when consumer group `events-sink` lag exceeds 50,000 messages on topic `shipment-events`.

## Triage

1. Check Kafka Connect worker status: `curl -s connect:8083/connectors/mongo-sink/status`. A task in FAILED state shows the stack trace.
2. The most common failure is a document over 16 MB or a schema change that breaks the sink's write model. Look for `BsonMaximumSizeExceededException` in the trace.
3. Check Atlas write latency for the `events.raw` namespace. Write latency above 50 ms usually means the sink is throttled by an index build.

## Mitigation

- Failed task: restart it with `curl -X POST connect:8083/connectors/mongo-sink/tasks/0/restart`.
- Poison message: the sink is configured with `errors.tolerance=all` and a dead letter topic `shipment-events-dlq`. Confirm the bad record landed there, then restart the task.
- Throughput: raise `tasks.max` from 4 to 8. The topic has 8 partitions, so more than 8 tasks adds nothing.

## Escalation

Lag above 500,000 messages means tracking pages are more than about 20 minutes stale. Page the Data team (Sev 2).
