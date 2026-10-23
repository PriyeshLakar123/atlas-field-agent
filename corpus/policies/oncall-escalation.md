# On call and escalation policy

## Severity levels

- **Sev 1**: customer facing outage or data loss. Page the incident commander immediately and open a bridge. Status page update within 15 minutes.
- **Sev 2**: major degradation with a workaround. Page the owning team. Update the ticket every 30 minutes.
- **Sev 3**: minor issue, single customer or carrier. Handle in business hours.

## Owning teams

- Platform team: shipment-api, Kubernetes, the API gateway.
- Data team: events-pipeline, MongoDB Atlas cluster, route-optimizer data.
- Integrations team: partner-gateway and carrier relationships.

## Handoff

Every open Sev 1 or Sev 2 ticket must have a handoff note before the on call shift ends at 17:00 UTC.
