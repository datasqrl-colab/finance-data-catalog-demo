# Retail Bank Data Catalog — Requirements

## 1. Purpose and Scope

Build a data catalog covering the **bronze** (source) and **silver** (enriched / conformed) layers of a retail bank's medallion architecture. The catalog documents tables as SQRL `CREATE TABLE` definitions which uses Flink SQL syntax, organized by line of business and team. It is the authoritative reference for what data exists, what each table contains, how datasets relate, and how each column is classified for compliance purposes.

## 2. Folder Structure

```
catalog/
├── customer/
│   └── customer_data/
│       ├── README.md
│       ├── customer_master.sqrl
│       ├── kyc_aml.sqrl
│       └── customer_enriched.sqrl
├── deposits_payments/
│   ├── accounts/
│   │   ├── README.md
│   │   ├── deposit_accounts.sqrl
│   │   ├── account_balances.sqrl
│   │   └── account_analytics.sqrl
│   └── transactions/
│       ├── README.md
│       ├── core_transactions.sqrl
│       ├── card_transactions.sqrl
│       ├── wire_ach_transactions.sqrl
│       └── enriched_transactions.sqrl
└── lending/
    ├── mortgages/
    │   ├── README.md
    │   ├── mortgage_originations.sqrl
    │   ├── mortgage_servicing.sqrl
    │   └── mortgage_performance.sqrl
    └── cards_consumer_credit/
        ├── README.md
        ├── credit_cards.sqrl
        ├── consumer_loans.sqrl
        └── credit_risk_signals.sqrl
```

## 3. File Conventions

### 3.1 .sqrl file layout

Each `.sqrl` file opens with a header comment block, then contains one or more `CREATE TABLE` statements that belong together. Tables in the same file should share a clear logical theme (one source system, one event family, or one conformed view).

```sql
-- ## <Dataset Name>
--
-- <2-5 sentence description of what this dataset contains, the
-- system of record, the grain of the data, and any important
-- caveats about freshness or completeness.>
--
-- Layer:            bronze | silver
-- Classification:   Public | Internal | Confidential | Restricted
-- Regulatory scope: <comma-separated regulations, e.g. GLBA, GDPR, CCPA, PCI-DSS>

/** <One- or two-sentence table description.> */
CREATE TABLE <table_name> (
  /** <prose comment> <@tags> */
  <column_name> <TYPE> [PRIMARY KEY],   
  ...
);
```

### 3.2 Header block (`-- ##`)

Every `.sqrl` file **must** begin with a `-- ##` block that includes:
- 2–5 sentence prose description (what's in it, the grain, any caveats).
- `Layer:` line (`bronze` or `silver`).
- `Classification:` line (see Section 7.1) — the highest classification of any column in the file.
- `Regulatory scope:` line (see Section 7.3) — union of regulations any column in the file is subject to.

### 3.3 Table descriptions (`/** ... */`)

Every `CREATE TABLE` **must** be preceded by a `/** ... */` block describing:
- What the table represents (entity, event, snapshot, etc.).
- The grain ("one row per …").
- Any non-obvious filtering or scope.

### 3.4 Column comments (`/** ... */`)

- In a separate line before the column definition.
- brief comment first (omit if the column is self-explanatory), then any `@tags` separated by spaces.
- Tags are required whenever a column carries PII, NPI, PCI, or other sensitive content (see Section 7).
- Self-explanatory columns with no sensitive content need no comment at all.

```sql
/** US Social Security Number 
    @spii @glba @encrypt @tokenize */
ssn STRING,
/** Primary email 
    @pii @gdpr @ccpa @mask @erasable */
email STRING,
/** Ledger balance in minor units 
    @npi @glba */
balance_cents BIGINT,
posted_at TIMESTAMP,
```

### 3.5 Naming

- Uppercase `Snake_case` for tables and lowercase for columns.
- Singular table names (`Customer`, not `Customers`).
- Surrogate keys named `<entity>_id`.
- Timestamps named `<event>_at` (e.g. `posted_at`); dates named `<event>_date`.
- Currency amounts stored in minor units (cents) unless noted in the column comment. Pair with a currency-code column where multi-currency is possible.

### 3.6 Required audit columns (bronze)

Bronze tables should include:
- `source_system` — upstream system identifier.
- `ingested_at` — when the row was loaded into the platform.
- `source_updated_at` — last-modified timestamp from the source, where available.

Silver tables do not repeat audit columns unless materially useful; lineage is captured in the file header.

### 3.7 README.md at the team level

Each team folder contains a `README.md` with:
- One-paragraph description of the team's data scope.
- A table listing each dataset in the folder: filename, layer, one-sentence purpose, source, classification.
- Notes on cross-team dependencies (e.g. "customer_360 joins transactions from `deposits_payments/transactions/`").
- The highest classification present in the folder, called out at the top.

### 3.8 Classification and tagging discipline

- Every column carrying PII, NPI, PCI, or otherwise restricted content **must** be tagged. Default (no tag) means non-sensitive / internal-by-default.
- The file-level `Classification` line is the highest classification of any column in the file.
- Silver tables inherit the highest classification of their bronze inputs unless the silver projection explicitly drops or tokenizes the sensitive columns; in that case the silver header should note "Derives from Restricted sources; sensitive columns dropped/tokenized."
- Tag vocabulary is closed (Section 7). New tags require updating this document.

## 4. Lines of Business and Teams

| Line of Business | Team | Folder |
|---|---|---|
| Customer | Customer Data | `customer/customer_data/` |
| Deposits & Payments | Accounts | `deposits_payments/accounts/` |
| Deposits & Payments | Transactions | `deposits_payments/transactions/` |
| Lending | Mortgages | `lending/mortgages/` |
| Lending | Cards & Consumer Credit | `lending/cards_consumer_credit/` |

## 5. Datasets

Each subsection enumerates the `.sqrl` files to be created, the layer, the source(s), and the tables in each file. Table lists are required. Column lists are illustrative — implementers should include all columns standard for retail banking source systems and conformed views, and must tag every sensitive column per Section 7.

Bronze datasets have been scoped to ensure every silver product in this catalog can be constructed from them; see Section 6 for the coverage matrix.

### 5.1 Customer / Customer Data

**`customer_master.sqrl`** — bronze, sourced from the Customer Information File (CIF) / core banking customer module.
- `customer` — one row per legal entity (person or organization) known to the bank: demographics, identification numbers, status, open date, primary segment hint.
- `customer_address` — multiple addresses per customer with type (mailing, residential, work) and effective date range.
- `customer_contact` — phone numbers and email addresses with type and verification status.
- `customer_employment` — current and historical employment records for income and affordability analysis.
- `customer_relationship` — relationships between customers (joint, beneficiary, authorized signer, business owner).

**`kyc_aml.sqrl`** — bronze, sourced from the KYC/AML compliance platform.
- `kyc_verification` — one row per identity-verification event: documents captured, verifier, outcome.
- `sanctions_screening` — one row per screening against sanctions lists (OFAC, EU, UN) with match status.
- `pep_screening` — politically exposed person screening results.
- `customer_risk_rating` — current and historical AML risk rating per customer.

**`customer_enriched.sqrl`** — silver, derived from `customer_master`, `kyc_aml`, and aggregates from `deposits_payments/` and `lending/`.
- `customer_profile` — one row per customer with conformed identity, current address and contact, current risk rating, primary segment, tenure, household link.
- `customer_segment` — one row per customer per segment assignment (mass-market, mass-affluent, affluent, private, small business) with effective dates.
- `customer_household` — household grouping based on shared address and relationships.
- `customer_lifetime_value` — modeled CLV with components (current balances, fee revenue, interest revenue, projected value).

### 5.2 Deposits & Payments / Accounts

**`deposit_accounts.sqrl`** — bronze, sourced from the core banking deposit module.
- `account` — one row per deposit account (checking, savings, money market, CD) with product, open and close dates, status, branch, currency.
- `account_holder` — many-to-many link between accounts and customers with role (primary, joint, signer, beneficiary). **Required for joining account-level data to customer in all silver products.**
- `account_status_history` — historical changes to account status (active, dormant, restricted, closed).
- `account_product` — reference table of deposit products with terms, rates, fee schedules.

**`account_balances.sqrl`** — bronze, end-of-day snapshots and intraday positions from the core.
- `account_balance_daily` — one row per account per business day: ledger balance, available balance, holds, accrued interest.
- `interest_accrual` — daily interest accrual entries (used for CLV interest-revenue component).
- `account_hold` — current and historical holds on funds with reason and release date.

**`account_analytics.sqrl`** — silver, derived from `deposit_accounts`, `account_balances`, and `deposits_payments/transactions/`.
- `account_activity_summary` — one row per account per month: transaction counts by channel, deposit/withdrawal totals, fees, average balance.
- `account_balance_trend` — rolling 30/90/365-day balance averages and volatility per account.
- `dormancy_signal` — flags and time-to-dormancy estimates per account.

### 5.3 Deposits & Payments / Transactions

**`core_transactions.sqrl`** — bronze, the unified posted-transaction ledger from the core banking system.
- `transaction` — one row per posted ledger entry: account, amount, direction, posting date, value date, channel, transaction code, description, counterparty where available. **Channel and transaction code are required for account_activity_summary; fee-category transaction codes feed CLV fee revenue.**
- `transaction_type` — reference of transaction codes with category (deposit, withdrawal, fee, interest, transfer, etc.) and description.
- `transaction_reversal` — links between original transactions and their reversals.

**`card_transactions.sqrl`** — bronze, sourced from the card processor / payment switch.
- `card_authorization` — one row per authorization request (approved or declined): card, **merchant_name (raw descriptor), merchant_city, merchant_country, merchant_id (acquirer-assigned), mcc**, amount, decision, response code. Merchant descriptor fields are required for `merchant_enrichment`.
- `card_settlement` — one row per cleared/settled card transaction; joins to authorization where applicable.
- `card_chargeback` — chargeback and dispute events with stage and outcome.
- `mcc_reference` — reference table of Merchant Category Codes with category labels, used by `transaction_category`.

**`wire_ach_transactions.sqrl`** — bronze, sourced from the payments platform(s).
- `ach_transaction` — one row per ACH credit or debit: originator name and ID, receiver name and ID, SEC code, amount, settlement date, return status. Originator/receiver names are required for `merchant_enrichment` and `recurring_payment` detection.
- `wire_transfer` — one row per domestic or international wire: sender, beneficiary, correspondent banks, amount, currency, status.
- `payment_return` — returns and reversals across ACH and wire flows.

**`enriched_transactions.sqrl`** — silver, derived from `core_transactions`, `card_transactions`, `wire_ach_transactions`, and `customer/customer_data/` (for customer linkage via `account_holder`).
- `unified_transaction` — one row per economic transaction, normalized across channels: common amount, currency, direction, account, customer, channel, category, merchant.
- `merchant_enrichment` — merchant master with normalized name, category, brand, and location, derived from raw card and ACH descriptors.
- `transaction_category` — taxonomy and category assignment (groceries, gas, dining, payroll, transfer, etc.) per unified transaction, using MCC reference and transaction type codes.
- `recurring_payment` — detected recurring payment series per customer (subscriptions, utilities, payroll deposits).

### 5.4 Lending / Mortgages

**`mortgage_originations.sqrl`** — bronze, sourced from the loan origination system (LOS).
- `mortgage_application` — one row per application: applicant(s), property, requested terms, decisioning outcome.
- `mortgage_loan` — one row per booked loan: terms, rate, amortization schedule reference, lien position, investor (held or sold), MERS MIN where applicable, **open_date, close_date, close_reason (paid-off, refinanced-out, foreclosed, sold-servicing). close_date / close_reason are required to detect prepayments in `prepayment_signal`.**
- `property_collateral` — property details: address, type, appraised value at origination, LTV at origination.
- `mortgage_borrower` — many-to-many link between loans and customers with role (borrower, co-borrower, guarantor).

**`mortgage_servicing.sqrl`** — bronze, sourced from the loan servicing system.
- `mortgage_payment` — one row per scheduled and actual payment: due date, paid date, principal, interest, escrow, fees. Due-vs-paid date drives `payment_behavior`.
- `escrow_account` — escrow balances and disbursements (taxes, insurance, PMI).
- `delinquency_event` — one row per delinquency milestone (30 / 60 / 90 / 120+ DPD, default, foreclosure, cure). Drives delinquency rollforward and current DPD in `loan_performance_monthly`.
- `loan_modification` — modifications, forbearance, and payment-deferral events.
- `property_valuation` — one row per property valuation event (origination appraisal, periodic AVM update, refinance appraisal, broker price opinion): property, valuation_date, value, valuation_source. **Required for current LTV in `loan_performance_monthly`.**

**`mortgage_performance.sqrl`** — silver, derived from `mortgage_originations` and `mortgage_servicing`.
- `loan_performance_monthly` — one row per loan per month: balance, status, days delinquent, current LTV, current rate.
- `prepayment_signal` — modeled prepayment probability and contributing factors per loan.
- `vintage_performance` — aggregated performance by origination vintage and product.

### 5.5 Lending / Cards & Consumer Credit

**`credit_cards.sqrl`** — bronze, sourced from the card issuing platform.
- `credit_card_account` — one row per card account: customer, product, open date, credit limit, status, cycle day.
- `credit_card` — one row per physical or virtual card on an account: status, expiration, plastic events.
- `credit_card_statement` — one row per billing cycle: balance, minimum due, due date, interest charged, fees.
- `credit_card_payment` — one row per payment received on a card account: posted date, amount, source of funds, on-time-vs-due-date flag. **Required for `payment_behavior` on card products.**
- `credit_limit_history` — credit limit changes with reason (CLI/CLD, customer-requested, risk-driven).
- `card_delinquency_event` — one row per delinquency milestone per card account (30 / 60 / 90 / 120+ DPD, charge-off, cure). **Required for `delinquency_rollforward`.**

**`consumer_loans.sqrl`** — bronze, sourced from the consumer lending platform.
- `personal_loan` — unsecured installment loans: terms, rate, balance, status, open_date, close_date, close_reason.
- `auto_loan` — secured auto loans with collateral reference, open_date, close_date, close_reason.
- `loan_payment` — payment events across personal and auto loans with due date and paid date.
- `loan_application` — one row per consumer credit application with bureau pull and decisioning outcome.
- `consumer_loan_delinquency_event` — one row per delinquency milestone per consumer loan (30 / 60 / 90 / 120+ DPD, charge-off, cure). **Required for `delinquency_rollforward` and `payment_behavior` on consumer loans.**

**`credit_risk_signals.sqrl`** — silver, derived from `credit_cards`, `consumer_loans`, `lending/mortgages/` (for cross-product exposure), and `deposits_payments/transactions/`.
- `customer_credit_exposure` — total exposure per customer across all credit products: balances, limits, utilization, weighted rate.
- `payment_behavior` — rolling on-time and late-payment metrics per customer and product, across cards, consumer loans, and mortgages.
- `delinquency_rollforward` — month-over-month delinquency state transitions across cards and consumer loans (and mortgages where applicable).
- `credit_utilization` — current utilization per card account and aggregated per customer.

## 6. Bronze-to-Silver Coverage

This matrix is the verification that Section 5's silver datasets are fully buildable from bronze. Every silver dataset must list its complete bronze provenance in its `.sqrl` header.

| Silver dataset | Required bronze inputs |
|---|---|
| `customer/customer_data/customer_360.customer_profile` | `customer_master.customer`, `customer_master.customer_address`, `customer_master.customer_contact`, `kyc_aml.customer_risk_rating` |
| `customer/customer_data/customer_360.customer_segment` | `customer_master.customer`, `account_balances.account_balance_daily`, `credit_cards.credit_card_account`, `consumer_loans.personal_loan`, `consumer_loans.auto_loan`, `mortgage_originations.mortgage_loan` |
| `customer/customer_data/customer_360.customer_household` | `customer_master.customer_address`, `customer_master.customer_relationship` |
| `customer/customer_data/customer_360.customer_lifetime_value` | `account_balances.account_balance_daily`, `account_balances.interest_accrual`, `core_transactions.transaction` (fee codes), `credit_card_statement.interest_charged`, `loan_payment` (interest split) |
| `deposits_payments/accounts/account_analytics.account_activity_summary` | `core_transactions.transaction` (channel, fee codes), `account_balances.account_balance_daily` |
| `deposits_payments/accounts/account_analytics.account_balance_trend` | `account_balances.account_balance_daily` |
| `deposits_payments/accounts/account_analytics.dormancy_signal` | `core_transactions.transaction` (posting_date), `account_status_history` |
| `deposits_payments/transactions/enriched_transactions.unified_transaction` | `core_transactions.transaction`, `card_settlement`, `ach_transaction`, `wire_transfer`, `deposit_accounts.account_holder` |
| `deposits_payments/transactions/enriched_transactions.merchant_enrichment` | `card_authorization` (merchant_name, merchant_city, merchant_country, merchant_id, mcc), `ach_transaction` (originator/receiver names) |
| `deposits_payments/transactions/enriched_transactions.transaction_category` | `unified_transaction`, `card_transactions.mcc_reference`, `core_transactions.transaction_type` |
| `deposits_payments/transactions/enriched_transactions.recurring_payment` | `unified_transaction`, `deposit_accounts.account_holder` |
| `lending/mortgages/mortgage_performance.loan_performance_monthly` | `mortgage_loan`, `mortgage_payment`, `delinquency_event`, `property_valuation` |
| `lending/mortgages/mortgage_performance.prepayment_signal` | `mortgage_loan` (incl. close_date / close_reason), `mortgage_payment` |
| `lending/mortgages/mortgage_performance.vintage_performance` | `mortgage_loan`, `loan_performance_monthly` |
| `lending/cards_consumer_credit/credit_risk_signals.customer_credit_exposure` | `credit_card_account`, `credit_card_statement`, `credit_limit_history`, `personal_loan`, `auto_loan`, `mortgage_loan` |
| `lending/cards_consumer_credit/credit_risk_signals.payment_behavior` | `credit_card_statement`, `credit_card_payment`, `loan_payment`, `mortgage_payment` |
| `lending/cards_consumer_credit/credit_risk_signals.delinquency_rollforward` | `card_delinquency_event`, `consumer_loan_delinquency_event`, `delinquency_event` (mortgages) |
| `lending/cards_consumer_credit/credit_risk_signals.credit_utilization` | `credit_card_statement`, `credit_limit_history` |

Implementers must add an entry to this table for any new silver dataset.

## 7. Data Classification and PII Tagging Vocabulary

The catalog tags every sensitive column inline. Tags are closed-vocabulary; new tags require updating this section.

### 7.1 Classification levels (file-level)

| Level | Meaning | Examples |
|---|---|---|
| `Public` | Disclosed publicly or intended for public use. | Branch locations, product catalogs. |
| `Internal` | Internal-by-default, low harm if disclosed. | Operational reference data, internal codes. |
| `Confidential` | Disclosure causes material harm or competitive damage. | Pricing models, internal risk scores, segment definitions. |
| `Restricted` | Disclosure causes regulatory, legal, or significant customer harm. | Any PII, NPI, PCI, KYC details, account balances, transaction history. |

Almost every dataset in this catalog is `Restricted`. `account_product`, `transaction_type`, and `mcc_reference` are `Internal`.

### 7.2 Sensitivity category tags (column-level)

| Tag | Meaning |
|---|---|
| `@pii` | Personally Identifiable Information: name, address, phone, email, DOB, employer. |
| `@spii` | Sensitive PII: government identifiers (SSN, ITIN, passport, driver's license), biometric data. |
| `@npi` | GLBA Non-public Personal Information: account numbers, balances, transaction history, credit information. |
| `@pci` | Payment Card Industry data: full PAN, expiration date, service code, cardholder name when paired with PAN. CVV/CVC must never appear. |
| `@confidential` | Internal sensitive but not personal: internal risk scores, pricing models, credit decisions. |

A column may carry more than one category tag (e.g. `@pii @npi` for customer name on an account record).

### 7.3 Regulatory scope tags (column-level)

| Tag | Scope |
|---|---|
| `@glba` | US Gramm-Leach-Bliley Act NPI safeguards. |
| `@gdpr` | EU General Data Protection Regulation. |
| `@ccpa` | California Consumer Privacy Act / CPRA. |
| `@pci-dss` | PCI Data Security Standard. |
| `@bsa` | Bank Secrecy Act / AML reporting scope. |
| `@sox` | Sarbanes-Oxley financial-reporting scope. |

Multiple regulatory tags are common (e.g. `@glba @gdpr @ccpa` on customer identifiers).

### 7.4 Handling tags (column-level)

| Tag | Required handling |
|---|---|
| `@encrypt` | Must be encrypted at rest using platform key management. |
| `@tokenize` | Original value replaced by a token; raw value in vault only. Required for full PAN and SSN. |
| `@mask` | Display masked outside production and to non-privileged consumers (e.g. `***-**-1234`). |
| `@erasable` | Subject to right-to-erasure (GDPR Art. 17, CCPA delete). Must be removable without breaking referential integrity (typically via tokenization or null-on-erase). |

### 7.5 Standard taggings to apply consistently

| Field pattern | Required tags |
|---|---|
| `customer_id` (surrogate key, not the natural ID) | none (internal identifier, not directly identifying) |
| Full name (`first_name`, `last_name`, `middle_name`) | `@pii @glba @gdpr @ccpa @erasable` |
| `date_of_birth` | `@pii @glba @gdpr @ccpa @mask @erasable` |
| `ssn` / national ID | `@spii @glba @encrypt @tokenize @retain:long` |
| Address fields | `@pii @glba @gdpr @ccpa @mask @erasable` |
| Phone, email | `@pii @glba @gdpr @ccpa @mask @erasable` |
| Account number (external-facing) | `@npi @glba @mask @encrypt` |
| Card PAN | `@pci @pci-dss @encrypt @tokenize` |
| Card expiration, cardholder name when on a card record | `@pci @pci-dss @mask` |
| Balances, statement amounts, transaction amounts | `@npi @glba` |
| KYC documents, verification details | `@spii @glba @bsa @encrypt @retain:long` |
| Sanctions / PEP match details | `@confidential @bsa @retain:long` |
| Internal risk ratings, credit scores derived in-house | `@confidential @glba` |
| Bureau scores ingested from external bureaus | `@npi @glba @confidential` |
| Merchant name and MCC on a transaction | `@npi @glba` (identifies the cardholder's activity) |
| Property address on collateral | `@pii @glba @gdpr @ccpa @erasable` |

### 7.6 Silver layer handling

- Silver tables inherit the highest classification of any retained sensitive column.
- Where a silver projection drops, hashes, or tokenizes sensitive columns to lower exposure, the file header must state which sensitive columns were dropped or transformed and what the resulting classification is.
- Aggregations that reach k-anonymity thresholds (e.g. `vintage_performance` aggregated by origination month and product) may be classified `Confidential` rather than `Restricted`; this must be justified in the file header.

## 8. Cross-Team Dependencies

Silver datasets join across teams. File headers must list upstream tables by fully qualified path. Known cross-team links:

- `customer/customer_data/customer_360.sqrl` depends on `deposits_payments/accounts/account_balances.sqrl`, `deposits_payments/accounts/deposit_accounts.sqrl`, `lending/mortgages/mortgage_originations.sqrl`, `lending/cards_consumer_credit/credit_cards.sqrl`, and `lending/cards_consumer_credit/consumer_loans.sqrl`.
- `deposits_payments/accounts/account_analytics.sqrl` depends on `deposits_payments/transactions/core_transactions.sqrl`.
- `deposits_payments/transactions/enriched_transactions.sqrl` depends on `deposits_payments/accounts/deposit_accounts.sqrl` (for the `account_holder` link to customer).
- `lending/cards_consumer_credit/credit_risk_signals.sqrl` depends on `lending/mortgages/mortgage_servicing.sqrl` and `lending/mortgages/mortgage_originations.sqrl` for cross-product exposure and payment behavior.
- `lending/mortgages/mortgage_performance.sqrl` joins to `customer/customer_data/customer_master.sqrl` for borrower attributes.

## 9. Deliverable Checklist

For each of the five teams:

- [ ] `README.md` present, listing every `.sqrl` file with layer, purpose, source, and classification.
- [ ] All `.sqrl` files listed in Section 5 are present.
- [ ] Every `.sqrl` file opens with a `-- ##` header including Layer, Source, Classification, Regulatory scope, and Data subject lines.
- [ ] Every `CREATE TABLE` is preceded by a `/** ... */` description that names the grain.
- [ ] Non-obvious columns carry `--` end-of-line comments.
- [ ] Bronze tables include `source_system`, `ingested_at`, and `source_updated_at`.
- [ ] Naming follows Section 3.5.
- [ ] Silver file headers list upstream `.sqrl` files by full path.
- [ ] Every silver dataset can be built from the bronze inputs listed in Section 6; any new silver dataset adds an entry to Section 6.
- [ ] Every PII / SPII / NPI / PCI / confidential column carries the appropriate category tag from Section 7.2, regulatory scope tags from 7.3, and handling tags from 7.4.
- [ ] Standard tag patterns from Section 7.5 are applied consistently across all files.
- [ ] Where silver tables drop or transform sensitive columns, the file header states what was dropped and the resulting classification.

## 10. Critical Rules

- All .sqrl files contain Flink SQL CREATE TABLE statements with comments