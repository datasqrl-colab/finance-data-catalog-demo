# Accounts — Deposits & Payments

**Team**: Deposit Products & Account Services
**Domain**: Retail Banking — Deposits

## Responsibilities

- Deposit account lifecycle management (checking, savings, money market, CDs, IRAs)
- Daily balance snapshots and interest accrual
- Account activity analytics and dormancy monitoring
- Account hold management

## Datasets

| Dataset | Layer | Description |
|---------|-------|-------------|
| `deposit_accounts` | Bronze | Core account records, holders, status history, and product configuration |
| `account_balances` | Bronze | Daily balance snapshots, interest accrual tracking, and account holds |
| `account_analytics` | Silver | Activity summaries, balance trends, and dormancy risk signals |

## Key Entities

- **Account** — Primary deposit account record with status, type, and product reference
- **Account_Holder** — Links customers to accounts with ownership type and signing authority
- **Account_Balance_Daily** — End-of-day balance snapshot with ledger, available, and collected balances

## Data Governance

- **Classification**: Restricted
- **Regulatory Scope**: GLBA, GDPR, CCPA, Regulation E, Regulation DD
- **Data Steward**: Deposit Products Team
- **Refresh Frequency**: Daily (bronze), Monthly (silver)

## Environment Connectors

- `-test`: Local filesystem (JSONL test data)
- `-prod`: Kafka (bronze tables), Iceberg (silver tables)
