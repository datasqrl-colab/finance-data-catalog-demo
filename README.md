# Retail Bank Data Catalog

A data catalog covering the **bronze** (source) and **silver** (enriched/conformed) layers of a retail bank's data mesh. Tables are documented as SQRL `CREATE TABLE` definitions using Flink SQL syntax, organized by line of business and team.

## Catalog Index

| Line of Business | Team | Folder | Key Datasets |
|---|---|---|---|
| Customer | Customer Data | [customer/customer_data/](customer/customer_data/) | Customer master, KYC/AML, Customer profiles |
| Deposits & Payments | Accounts | [deposits_payments/accounts/](deposits_payments/accounts/) | Deposit accounts, Balances, Account analytics |
| Deposits & Payments | Transactions | [deposits_payments/transactions/](deposits_payments/transactions/) | Core transactions, Card/Wire/ACH, Enriched transactions |
| Lending | Mortgages | [lending/mortgages/](lending/mortgages/) | Originations, Servicing, Performance analytics |
| Lending | Cards & Consumer Credit | [lending/cards_consumer_credit/](lending/cards_consumer_credit/) | Credit cards, Consumer loans, Credit risk signals |

## Classification Levels

| Level | Description |
|---|---|
| **Public** | Disclosed publicly or intended for public use |
| **Internal** | Internal-by-default, low harm if disclosed |
| **Confidential** | Disclosure causes material harm or competitive damage |
| **Restricted** | Disclosure causes regulatory, legal, or significant customer harm (PII, NPI, PCI) |

## Sensitivity Tags

| Tag | Category |
|---|---|
| `@pii` | Personally Identifiable Information (name, address, phone, email, DOB) |
| `@spii` | Sensitive PII (SSN, passport, driver's license, biometrics) |
| `@npi` | GLBA Non-public Personal Information (account numbers, balances, transactions) |
| `@pci` | Payment Card Industry data (PAN, expiration, cardholder name) |
| `@confidential` | Internal sensitive but not personal (risk scores, pricing models) |

## Regulatory Scope Tags

`@glba` (Gramm-Leach-Bliley) | `@gdpr` (EU GDPR) | `@ccpa` (California CCPA/CPRA) | `@pci-dss` (PCI DSS) | `@bsa` (Bank Secrecy Act) | `@sox` (Sarbanes-Oxley)

## Handling Tags

| Tag | Required Handling |
|---|---|
| `@encrypt` | Encrypted at rest using platform key management |
| `@tokenize` | Original value replaced by token; raw value in vault only |
| `@mask` | Display masked outside production and to non-privileged consumers |
| `@erasable` | Subject to right-to-erasure (GDPR Art. 17, CCPA delete) |

## File Structure

Each dataset is split into a schema file and one connector file per environment:
- **`{dataset}.sqrl`** — header comment with layer, classification, and regulatory scope, followed
  by `_schema`-suffixed `CREATE TABLE` statements. Each table carries a single table-level
  doc-string that states its grain and a `# Columns:` section documenting every column in
  declaration order, with its sensitivity tags (`@pii`, `@npi`, `@pci`, `@confidential`, …). The
  `CREATE TABLE` body itself holds only bare `column TYPE [NOT NULL]` definitions — no inline
  column comments.
- **`{dataset}-test.sqrl`** and **`{dataset}-prod.sqrl`** — one connector file per environment,
  each importing the schema file and extending its tables with `LIKE`. The connector table owns
  the environment-specific pieces the schema table does not: the watermark, the ingestion column
  (`ingested_at` for bronze sources, `computed_at` for silver), and the `WITH (...)` connector
  configuration (`filesystem` in test, `kafka-safe`/`iceberg` in prod).
- **`testdata/`** — one `.jsonl` file per table, named `{dataset}-{table}.jsonl`, read by the
  `-test.sqrl` connectors.

Bronze tables carry the audit columns `source_system` and `source_updated_at` in their schema, and
`ingested_at` in their connector table. Silver tables carry `computed_at` in their connector table
instead.

**Watermarks are intentionally asymmetric between environments.** Every bronze `-test.sqrl`
watermarks its ingestion column 10 seconds back; every bronze `-prod.sqrl` watermarks the same
column 30 seconds back. This is not a mismatch to reconcile — test data is small, ordered and
replayed once, so a short offset is enough to close out windows quickly, while production Kafka
delivery is genuinely out of order and needs the wider tolerance. What must match between the two
(and does, everywhere in this catalog) is the watermark **column name**, so a table's event-time
semantics don't change shape across environments. Likewise, a bronze test connector declares its
`ingested_at` as a plain physical `TIMESTAMP_LTZ(3)` column while the prod connector sources the
same-named column via Kafka `METADATA FROM 'timestamp'` — the filesystem connector used in test has
no record metadata to read, so a physical column populated by the test data is the closest
equivalent. Silver connector tables carry `computed_at` with **no watermark** in either environment,
because they are recomputed upsert snapshots (keyed on the table's grain), not event streams.

## Ontology Layer & Environment Model

Each line of business has a `{lob}-ontology.sqrl` file that imports its datasets, defines the
relationships between them, and ends with its data-quality assertions:

- [`customer/customer-ontology.sqrl`](customer/customer-ontology.sqrl) — Customer line of business
- [`lending/lending-ontology.sqrl`](lending/lending-ontology.sqrl) — Lending line of business
- [`deposits_payments/deposits_payments-ontology.sqrl`](deposits_payments/deposits_payments-ontology.sqrl) — Deposits & Payments line of business

[`ontology.sqrl`](ontology.sqrl) at the catalog root imports all three unit ontologies, defines the
relationships that cross line-of-business boundaries (e.g. a lending account's borrower back to
`Customer`, a deposit account's holder back to `Customer`), and carries the cross-domain
referential-integrity assertions and snapshot tests described below.

Every dataset and ontology import is written with a `{{environment}}` template variable
(`IMPORT dataset-{{environment}}.*;`), which `script.config.environment` resolves at compile time
to select the `-test` or `-prod` connector set for every table in the import chain at once.

## Data Quality

Every unit and the root ontology end with `/*+test(no_rows) */` assertions: each selects the rows
that violate a rule and the assertion passes when the query returns zero rows. The catalog covers
referential integrity (mandatory for every foreign key), enum validity, mandatory-field,
numeric-sanity, date-ordering, cross-field-consistency and self-reference checks.

- **Intra-unit foreign keys** (child and parent both live in the same line of business) are
  asserted in that unit's `{lob}-ontology.sqrl` — e.g. `Account_Holder.account_id` against
  `Account.account_id` in the Deposits & Payments ontology.
- **Cross-domain foreign keys** (child and parent live in different lines of business — e.g. a
  `Credit_Card_Account.primary_customer_id` referencing `Customer`) can only be asserted in the
  root `ontology.sqrl`, since it is the only file that imports every unit.

The root `ontology.sqrl` also carries one `/*+test */` snapshot query per imported dataset,
filtered on a known identifier from that dataset's test data, so a change to a schema, connector or
test-data file that alters what the catalog serves shows up as a snapshot diff.

## Compile and Test

Configuration is split into a shared base plus a thin test overlay:
`ontology-shared-package.json` and `ontology-test-package.json`. Compile and test by layering the
base then the overlay (last one wins):

```bash
docker run -it --rm -p 8888:8888 -p 8081:8081 -v $PWD:/build datasqrl/cmd \
  compile ontology-shared-package.json ontology-test-package.json

docker run -it --rm -p 8888:8888 -p 8081:8081 -v $PWD:/build datasqrl/cmd \
  test ontology-shared-package.json ontology-test-package.json
```

[`run-tests.sh`](run-tests.sh) at the catalog root is the single entry point for the catalog's
tests (`./run-tests.sh` runs every suite against `test`; `./run-tests.sh --compile` compiles it
without running the tests). It is what the code agent, CI and a developer all run —
see `./run-tests.sh --list-invocations` for what a given flag combination would execute.

## Test Data

Every `testdata/*.jsonl` file is generated, not hand-maintained:

```bash
python3 scripts/generate_testdata.py           # rewrite every */testdata/*.jsonl file
python3 scripts/generate_testdata.py --check   # verify the files on disk match the generator
python3 scripts/generate_testdata.py --verify  # run the fixture quality gates
```

The generator needs only the Python standard library and is deterministic — the seed in
[`scripts/testdata_gen/common.py`](scripts/testdata_gen/common.py) fixes every random draw, so two
runs produce byte-identical files and a re-run shows up in `git diff` only when a generator module
actually changed.

`--check` answers *do the committed files match the generator*; `--verify`
([`fixture_checks.py`](scripts/testdata_gen/fixture_checks.py)) answers *is what the generator
produces fit to consume*, asserting what the SQRL assertions cannot: that `ingested_at` tracks
business time closely enough for the watermark offsets the connectors declare, that
verification-result columns carry a realistic distribution rather than a single value, and that
coded columns hold codes from their real vocabulary.

The original hand-authored rows live in `scripts/testdata_gen/seed/` and are copied verbatim into
the output, keeping the identifiers the root ontology's snapshot tests are filtered on (`CUST-001`,
`ML-001`, `ACCT-001`, …). Generated rows number upward from the highest seeded key in each table, so
they add volume without moving any snapshot.

One module per subject area builds the book in dependency order — `customers`, `accounts`, `ledger`,
`deposit_rows`, `balances`, `cards_loans`, `mortgages`, then `enriched` for the silver profiles,
segments, households and credit-risk signals that aggregate everything before them.

## Known Gaps

- **No debit-card master dataset.** `Card_Authorization.card_id`, `Card_Settlement.card_id` and
  `Card_Chargeback.card_id` in `deposits_payments/transactions/card_transactions.sqrl` have no
  parent table anywhere in this catalog, so no referential-integrity assertion is written for
  them. A future card-issuing dataset would need to add one.
