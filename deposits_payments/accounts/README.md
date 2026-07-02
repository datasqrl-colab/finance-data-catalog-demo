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
- **Account_Balance_Daily**: Point-in-time balance snapshots
- **Dormancy_Signal**: Regulatory compliance for dormant account monitoring

## Data Governance

- **Classification**: Restricted
- **Regulatory Scope**: GLBA, GDPR, CCPA, Regulation E, Regulation DD
- **Data Steward**: Deposit Operations
- **Refresh Frequency**: Daily for bronze, daily for silver

## Environments

- **-test**: Local filesystem data for testing. Connector files: [deposit_accounts-test.sqrl](deposit_accounts-test.sqrl), [account_balances-test.sqrl](account_balances-test.sqrl), [account_analytics-test.sqrl](account_analytics-test.sqrl)
- **-prod**: Production data — Kafka for bronze tables (Account, Account_Holder, Account_Status_History, Account_Product, Account_Balance_Daily, Interest_Accrual, Account_Hold), Apache Iceberg for silver tables (Account_Activity_Summary, Account_Balance_Trend, Dormancy_Signal). Connector files: [deposit_accounts-prod.sqrl](deposit_accounts-prod.sqrl), [account_balances-prod.sqrl](account_balances-prod.sqrl), [account_analytics-prod.sqrl](account_analytics-prod.sqrl)
