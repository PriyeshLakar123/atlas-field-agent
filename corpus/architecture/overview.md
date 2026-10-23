# Northwind Platform Architecture Overview

Northwind Logistics is a fictional freight company used as the sample customer for this project. All names, hosts, and numbers in this corpus are invented.

## Services

The platform has four production services:

- **shipment-api**: Node.js REST API that carriers and shippers call to create and track shipments. Runs on Kubernetes in the `shipping` namespace with 6 replicas behind the public API gateway.
- **route-optimizer**: Python service that computes delivery routes. Consumes `shipment.created` events and writes routes back to MongoDB.
- **events-pipeline**: Kafka Connect workers that stream shipment events from Kafka topics into the `events` collection in MongoDB Atlas.
- **partner-gateway**: Calls external carrier APIs (OAuth2 client credentials) to fetch tracking updates every 5 minutes.

## Data stores

All operational data lives in one MongoDB Atlas cluster, `northwind-prod` (M50, 3 node replica set, us-east-1). Databases: `shipping` (shipments, routes), `events` (raw events, 30 day TTL), and `support` (runbook embeddings for this agent).

## Observability

Metrics go to Prometheus and dashboards live in Grafana under the folder "Northwind Prod". Logs are shipped to OpenSearch with a 14 day retention. Every request carries an `X-Correlation-ID` header that is logged by all services.
