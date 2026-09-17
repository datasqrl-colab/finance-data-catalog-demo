"""Shared constants, time helpers and table plumbing for the synthetic test data generator."""
import datetime as dt
import json
import os
import random
import zlib

UTC = dt.timezone.utc
SEED = 20260915

# The data set is current as of this instant; nothing generated happens after it.
AS_OF = dt.datetime(2026, 9, 15, 17, 0, 0, tzinfo=UTC)
AS_OF_DATE = AS_OF.date()
# Generated activity history starts here.
WINDOW_START = dt.datetime(2023, 2, 1, tzinfo=UTC)
WINDOW_START_DATE = WINDOW_START.date()
# Monthly lending tables (statements, loan payments, performance) cover only the last 12 months.
LAST12_START = dt.date(2025, 10, 1)

HERE = os.path.dirname(os.path.abspath(__file__))
SEED_DIR = os.path.join(HERE, "seed")
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))


def rng_for(name):
    return random.Random(SEED ^ zlib.crc32(name.encode()))


# ---------------------------------------------------------------------------
# Formatting and date arithmetic
# ---------------------------------------------------------------------------

def ts(value):
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ds(value):
    return value.isoformat() if value is not None else None


def parse_ts(text):
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def at(day, hour=0, minute=0, second=0):
    return dt.datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def rand_date(rng, start, end):
    if end <= start:
        return start
    return start + dt.timedelta(days=rng.randint(0, (end - start).days))


def rand_dt(rng, start, end):
    if end <= start:
        return start
    return start + dt.timedelta(seconds=rng.randint(0, int((end - start).total_seconds())))


def business_time(rng, day, first_hour=7, last_hour=21):
    return at(day, rng.randint(first_hour, last_hour - 1), rng.randint(0, 59), rng.randint(0, 59))


def add_months(day, months):
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return dt.date(year, month, min(day.day, days_in_month(year, month)))


def days_in_month(year, month):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - dt.timedelta(days=1)).day


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=days_in_month(day.year, day.month))


def months_between(start, end):
    """Month starts from start's month through end's month, inclusive."""
    out, cur = [], month_start(start)
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def quarter_ends(start, end):
    out = []
    for m in months_between(start, end):
        if m.month in (3, 6, 9, 12):
            qe = month_end(m)
            if start <= qe <= end:
                out.append(qe)
    return out


def cents(rng, low, high, step=100):
    return rng.randint(low // step, high // step) * step


def lognormal_cents(rng, median, sigma, low, high, step=100):
    value = median * (2.718281828 ** rng.gauss(0, sigma))
    return max(low, min(high, int(value / step) * step))


def weighted(rng, pairs):
    total = sum(w for _, w in pairs)
    pick = rng.uniform(0, total)
    for value, weight in pairs:
        pick -= weight
        if pick <= 0:
            return value
    return pairs[-1][0]


def clamp_dt(value, low=None, high=AS_OF):
    if low is not None and value < low:
        value = low
    return min(value, high)


# ---------------------------------------------------------------------------
# Ingestion and computation timestamps
# ---------------------------------------------------------------------------

# Ingestion lag windows, in seconds. A bronze feed lands close behind the event it reports: the
# streaming rails within a minute, a batch extract within a few minutes. The connectors declare a
# watermark of `ingested_at` minus 10 seconds in test and 30 in prod, and those offsets are only
# sufficient while this stays small — at an hours-long lag the watermark jumps to
# max(ingested_at) - 10s and every row behind it is silently dropped from windowed reads.
STREAM_LAG = (2, 45)
BATCH_LAG = (20, 240)


def stamp_bronze(rng, row, event, lag=BATCH_LAG):
    """Set source_updated_at just after the event, and ingested_at just after that.

    Ordering by ingested_at therefore matches ordering by business time, which is what the
    connectors' declared rowtime assumes. A record that predates the activity window is still
    stamped against its own event rather than being relocated into a backfill load: pretending an
    old record arrived recently is exactly what breaks that ordering.
    """
    event = min(event, AS_OF)
    updated = min(event + dt.timedelta(seconds=rng.randint(0, 20)), AS_OF)
    ingested = min(updated + dt.timedelta(seconds=rng.randint(*lag)), AS_OF)
    row["source_updated_at"] = ts(updated)
    row["ingested_at"] = ts(ingested)
    return row


def stamp_stream(rng, row, event):
    """A bronze row from a streaming rail, where ingestion is seconds behind the event."""
    return stamp_bronze(rng, row, event, lag=STREAM_LAG)


def stamp_silver(rng, row, after, min_seconds=60, max_seconds=6 * 3600):
    computed = min(after + dt.timedelta(seconds=rng.randint(min_seconds, max_seconds)), AS_OF)
    row["computed_at"] = ts(computed)
    return row


def stamp_current(rng, row):
    """Current-state silver rows are recomputed on the as-of day."""
    row["computed_at"] = ts(rand_dt(rng, at(AS_OF_DATE, 0, 5), AS_OF - dt.timedelta(minutes=1)))
    return row


def stamp_period(rng, row, period_last_day):
    """Periodic silver rows are computed within 3 days after their period closes."""
    after = at(period_last_day + dt.timedelta(days=1))
    if after >= AS_OF:
        return stamp_current(rng, row)
    row["computed_at"] = ts(min(rand_dt(rng, after, after + dt.timedelta(days=3)), AS_OF))
    return row


# ---------------------------------------------------------------------------
# Tables: anchors from the seed folder plus generated rows
# ---------------------------------------------------------------------------

def seed_files():
    found = {}
    for dirpath, _, filenames in os.walk(SEED_DIR):
        for name in filenames:
            if name.endswith(".jsonl"):
                rel = os.path.relpath(os.path.join(dirpath, name), SEED_DIR)
                found[name[:-6]] = rel
    return dict(sorted(found.items()))


class Tables:
    def __init__(self):
        self.paths = seed_files()
        self.anchors = {}
        for stem, rel in self.paths.items():
            with open(os.path.join(SEED_DIR, rel)) as handle:
                lines = [line.rstrip("\n") for line in handle if line.strip()]
            self.anchors[stem] = [(line, json.loads(line)) for line in lines]
        self.generated = {stem: [] for stem in self.paths}

    def template(self, stem, index=0):
        return self.anchors[stem][index][1]

    def add(self, stem, template=None, **fields):
        row = dict(template if template is not None else self.template(stem))
        for key, value in fields.items():
            if key not in row:
                raise KeyError(f"{stem}: unknown column {key}")
            row[key] = value
        self.generated[stem].append(row)
        return row

    def time_column(self, stem):
        first = self.anchors[stem][0][1]
        return "ingested_at" if "ingested_at" in first else "computed_at"

    def ordered_lines(self, stem):
        """Anchors verbatim plus generated rows, strictly ascending and unique by the time column."""
        col = self.time_column(stem)
        items = [[parse_ts(r[col]), False, i, line, r] for i, (line, r) in enumerate(self.anchors[stem])]
        items += [[parse_ts(r[col]), True, i, None, r] for i, r in enumerate(self.generated[stem])]
        items.sort(key=lambda it: (it[0], it[1], it[2]))
        second = dt.timedelta(seconds=1)
        out = []
        for item in items:
            if out and item[0] <= out[-1][0]:
                if item[1]:
                    item[0] = out[-1][0] + second
                else:
                    # An anchor keeps its timestamp; move the generated rows ahead of it back.
                    t, j = item[0], len(out) - 1
                    while j >= 0 and out[j][0] >= t:
                        if not out[j][1]:
                            raise ValueError(f"{stem}: anchor timestamps collide at {ts(t)}")
                        t -= second
                        out[j][0] = t
                        j -= 1
            out.append(item)
        lines = []
        for t, is_generated, _, line, row in out:
            if is_generated:
                row[col] = ts(t)
                lines.append(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
            else:
                lines.append(line)
        return lines

    def write(self, root=PROJECT_ROOT):
        for stem, rel in self.paths.items():
            lines = self.ordered_lines(stem)
            with open(os.path.join(root, rel), "w") as handle:
                handle.write("\n".join(lines) + "\n")


def ident(prefix, number, width=3):
    return f"{prefix}-{number:0{width}d}"


# ---------------------------------------------------------------------------
# Loan amortization
# ---------------------------------------------------------------------------

def amortized_payment(principal, annual_rate, months):
    rate = annual_rate / 12
    if rate == 0:
        return principal // months
    return int(principal * rate / (1 - (1 + rate) ** -months))


def amortized_balance(principal, annual_rate, payment, payments_made):
    rate = annual_rate / 12
    if rate == 0:
        return max(0, principal - payment * payments_made)
    growth = (1 + rate) ** payments_made
    return max(0, int(principal * growth - payment * (growth - 1) / rate))


def due_dates(first_payment, last_day):
    """Monthly due dates from the first payment date through last_day."""
    out, k = [], 0
    while True:
        day = add_months(first_payment, k)
        if day > last_day:
            return out
        out.append(day)
        k += 1
