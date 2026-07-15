# Transactions — Deposits & Payments

**Team**: Payments & Transaction Services
**Domain**: Retail Banking — Transactions

## Responsibilities

- Core transaction processing and ledger management
- Card authorization, settlement, and chargeback lifecycle
- ACH and wire transfer processing
- Transaction enrichment, categorization, and recurring payment detection

## Datasets

| Dataset | Layer | Description |
|---------|-------|-------------|
| `core_transactions` | Bronze | Transaction ledger, type reference data, and reversal records |
| `card_transactions` | Bronze | Card authorizations, settlements, chargebacks, and MCC reference data |
| `wire_ach_transactions` | Bronze | ACH transactions, wire transfers, and payment returns |
| `enriched_transactions` | Silver | Unified transaction view, merchant enrichment, categorization, and recurring payments |

## Key Entities

- **Transaction** — Primary transaction ledger recording all account monetary movements
- **Card_Authorization** — Real-time card authorization requests and responses
- **Unified_Transaction** — Enriched transaction view combining all payment types with merchant and category data

## Data Governance

- **Classification**: Restricted
- **Regulatory Scope**: GLBA, GDPR, CCPA, Regulation E, BSA, OFAC, PCI-DSS
- **Data Steward**: Payments & Transaction Services Team
- **Refresh Frequency**: Near real-time (bronze), Daily (silver)

## Environment Connectors

- `-test`: Local filesystem (JSONL test data)
- `-prod`: Kafka (bronze tables), Iceberg (silver tables)
