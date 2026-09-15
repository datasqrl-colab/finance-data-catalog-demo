# Transactions Team

The Transactions team owns transaction data across all payment channels including core ledger transactions, card payments, ACH, wire transfers, and instant payments (RTP, FedNow, Zelle and push-to-card), along with enriched transaction analytics.

## Team Responsibilities

- Core transaction ledger and posting
- Card authorization and settlement processing
- ACH and wire transfer processing
- Instant payment processing across RTP, FedNow, Zelle and push-to-card, including requests for payment and return requests
- Transaction enrichment and categorization
- Recurring payment detection

## Datasets

| Dataset | Layer | Description |
|---------|-------|-------------|
| [core_transactions.sqrl](core_transactions.sqrl) | Bronze | Primary transaction ledger, transaction types, and reversals |
| [card_transactions.sqrl](card_transactions.sqrl) | Bronze | Card authorizations, settlements, chargebacks, and MCC reference |
| [wire_ach_transactions.sqrl](wire_ach_transactions.sqrl) | Bronze | ACH transactions, wire transfers, and payment returns |
| [instant_payments.sqrl](instant_payments.sqrl) | Bronze | Instant payment participants, payments, requests for payment, and return requests |
| [enriched_transactions.sqrl](enriched_transactions.sqrl) | Silver | Unified transactions, merchant enrichment, categories, and recurring payments |

## Key Entities

- **Account_Transaction**: Primary ledger record for all account movements. Named `Account_Transaction` rather than `Transaction` because `Transaction` is a reserved Flink SQL keyword and fails to parse as a standalone table name.
- **Card_Authorization / Card_Settlement**: Card payment lifecycle from authorization through settlement
- **Wire_Transfer / Ach_Transaction**: Electronic funds transfer records
- **Instant_Payment / Request_For_Payment / Instant_Payment_Return**: Instant push payments on RTP, FedNow, Zelle and push-to-card (`payment_rail`), the requests for payment they pay, and the return requests raised against them. ISO 20022 fields such as `iso_status_code` and `uetr` apply to RTP and FedNow only; requests for payment exist only on those two rails. Instant payments post to the ledger and the unified view with channel `INSTANT`. The payments hub publishes each payment when it is initiated, before release (`payment_status` `PENDING`), and again at every status change; the record with the latest `source_updated_at` is the payment's current state
- **Instant_Payment_Participant**: Institutions reachable on each rail, keyed by routing number (issuer BIN for push-to-card), with their published transaction limits
- **Unified_Transaction**: Consolidated view across all transaction types
- **Recurring_Payment**: Detected recurring payment patterns

## Data Governance

- **Classification**: Restricted
- **Regulatory Scope**: GLBA, GDPR, CCPA, Regulation E, Regulation J, UCC Article 4A, BSA, OFAC, PCI-DSS
- **Data Steward**: Payment Operations
- **Refresh Frequency**: Real-time for bronze, hourly for silver

## Environments

- **-test**: Local data for testing
- **-prod**: Production data (Kafka or Iceberg)

## Test Data

Test fixtures for every table in this folder's datasets live under [`testdata/`](testdata/), one `.jsonl` file per table named `{dataset}-{table}.jsonl`.
