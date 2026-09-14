# Accounts Team

The Accounts team owns deposit account data including account lifecycle management, balance tracking, and account-level analytics for the bank's deposit product portfolio.

## Team Responsibilities

- Deposit account master data (checking, savings, money market, CDs)
- Account ownership and holder management
- Daily balance snapshots and interest accruals
- Account dormancy monitoring and escheatment compliance

## Datasets

| Dataset | Layer | Description |
|---------|-------|-------------|
| [deposit_accounts.sqrl](deposit_accounts.sqrl) | Bronze | Account records, holders, status history, and product configuration |
| [account_balances.sqrl](account_balances.sqrl) | Bronze | Daily balance snapshots, interest accruals, and account holds |
| [account_analytics.sqrl](account_analytics.sqrl) | Silver | Activity summaries, balance trends, and dormancy signals |

## Key Entities

- **Account**: Primary deposit account record
- **Account_Holder**: Links customers to the accounts they own
- **Account_Product**: Deposit product configuration and terms
- **Account_Balance_Daily**: Point-in-time balance snapshots
- **Account_Hold**: Holds placed on funds reducing available balance
- **Dormancy_Signal**: Regulatory compliance for dormant account monitoring

## Data Governance

- **Classification**: Restricted
- **Regulatory Scope**: GLBA, GDPR, CCPA, Regulation E, Regulation DD
- **Data Steward**: Deposit Operations
- **Refresh Frequency**: Daily for bronze, daily for silver

## Environments

- **-test**: Local data for testing
- **-prod**: Production data (Kafka or Iceberg)

## Test Data

Test fixtures for every table in this folder's datasets live under [`testdata/`](testdata/), one `.jsonl` file per table named `{dataset}-{table}.jsonl`.
