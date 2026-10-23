# Data Model

## shipments collection

One document per shipment in the `shipping` database. Key fields: `shipmentId` (string, unique), `status` (created, in_transit, delivered, exception), `carrierId`, `origin`, `destination`, `events` (embedded array capped at the 50 most recent events), and `updatedAt`.

Indexes: unique index on `shipmentId`; compound index `{ carrierId: 1, status: 1, updatedAt: -1 }` used by the carrier dashboard; TTL is not used on shipments.

## Why events are embedded and capped

Tracking pages read a shipment and its latest events in a single query. Embedding the 50 most recent events avoids a join on the hot path. The full event history lives in the `events` collection, which has a 30 day TTL index on `receivedAt`.

## routes collection

Written by route-optimizer. One document per shipment route with `shipmentId`, `stops` (ordered array), `etaMinutes`, and `computedAt`. Index on `shipmentId`.
