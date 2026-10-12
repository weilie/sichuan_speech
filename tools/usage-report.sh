#!/usr/bin/env bash
# Month-to-date cost and usage for the Sichuan speaker.
#
#   tools/usage-report.sh [YYYY-MM]
#
# Model Studio spend is broken down by workspace and model. Once the device has
# its own workspace-scoped key, its line is the device's cost -- Alibaba bills
# Model Studio per WORKSPACE, not per key, so a key created in the shared
# workspace is indistinguishable from any other Qwen usage on the account.
#
# Needs a profile with AliyunBSSReadOnlyAccess (account-wide, so the existing
# glasses-deploy profile already covers this project).
# Optional: ALIYUN_PROFILE (default glasses-deploy), PI (default the device),
# ALERT_USD (default 1: a day above this is flagged in the daily section).
#
# Billing lags a few hours, so today's usage appears later in the day. The
# device-side section below is live, and is the one to look at for "what did it
# do in the last hour".
#
# The daily section shows the month to date when it is at least 14 days old,
# otherwise the last 14 days (into the previous month), with a projection.
#
# Each section degrades on its own: a billing call that fails prints a note
# and the script moves on, so the live device section is always reached.

set -euo pipefail

CYCLE="${1:-$(date -u +%Y-%m)}"
PROFILE="${ALIYUN_PROFILE:-glasses-deploy}"
PI="${PI:-weilie@sichuan-pi.local}"
ALERT_USD="${ALERT_USD:-1}"
# Workspace ids, so the report can say "device" and "shared" instead of hex.
DEVICE_WS="${DEVICE_WS:-ws-mjroku2rz092jog3}"
SHARED_WS="${SHARED_WS:-ws-1e6aupoqlzcrth3l}"
# First day of the month after CYCLE, so the journal section covers the same
# month as the billing sections when CYCLE is a past month.
CY="${CYCLE%-*}"; CM="${CYCLE#*-}"
NEXT=$(printf '%04d-%02d' $(( 10#$CM == 12 ? CY + 1 : CY )) $(( 10#$CM % 12 + 1 )))

# Every page of one DescribeInstanceBill query, ONE JSON document PER LINE.
# Extra arguments narrow the query (e.g. --Granularity DAILY --BillingDate).
# The CLI pretty-prints its JSON across many lines, so each page is
# re-serialised compact before it is emitted; the parsers below split on
# newlines and would otherwise choke on the first "{".
bill_pages() {
  local token="" page compact
  while :; do
    page=$(aliyun bssopenapi DescribeInstanceBill --BillingCycle "${BILL_CYCLE:-$CYCLE}" --ProductCode sfm \
      --IsBillingItem true --MaxResults 300 ${token:+--NextToken "$token"} "$@" \
      --profile "$PROFILE" --region ap-southeast-1) || return 1
    compact=$(printf '%s' "$page" | node -e '
      let s = ""; process.stdin.on("data", d => s += d).on("end", () =>
        process.stdout.write(JSON.stringify(JSON.parse(s))))') || return 1
    printf '%s\n' "$compact"
    token=$(printf '%s' "$compact" | node -e '
      let s = ""; process.stdin.on("data", d => s += d).on("end", () =>
        process.stdout.write(JSON.parse(s).Data?.NextToken ?? ""))') || return 1
    [ -n "$token" ] || break
  done
}

echo "== Bill overview $CYCLE (USD, pre-tax)"
aliyun bssopenapi QueryBillOverview --BillingCycle "$CYCLE" \
  --profile "$PROFILE" --region ap-southeast-1 |
  node -e '
    let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
      for (const i of JSON.parse(s).Data?.Items?.Item ?? [])
        console.log(`  ${i.ProductName} / ${i.ProductDetail}: ${Number(i.PretaxAmount).toFixed(4)}`);
    });' || echo "  (billing API unavailable)"

echo "== Model Studio by workspace / model"
if PAGES=$(bill_pages); then
  printf '%s' "$PAGES" | node -e '
    let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
      const rows = {}; let total = 0;
      for (const line of s.split("\n").filter(Boolean))
        for (const i of JSON.parse(line).Data?.Items ?? []) {
          // InstanceID: "<n>;<workspace>;<model>;<billing item>;;<n>"
          const [, ws = "?", model = "?"] = (i.InstanceID ?? "").split(";");
          const key = `${ws}  ${model}  ${i.BillingItem}`;
          const r = (rows[key] ??= { usage: 0, unit: i.UsageUnit, cost: 0 });
          r.usage += Number(i.Usage) || 0;
          r.cost += Number(i.PretaxAmount) || 0;
          total += Number(i.PretaxAmount) || 0;
        }
      for (const [k, r] of Object.entries(rows).sort())
        console.log(`  ${k}: ${r.usage.toFixed(3)} ${r.unit}, ${r.cost.toFixed(4)}`);
      const byWs = {};
      for (const [k, r] of Object.entries(rows)) byWs[k.split("  ")[0]] = (byWs[k.split("  ")[0]] ?? 0) + r.cost;
      for (const [w, c] of Object.entries(byWs).sort()) console.log(`  workspace ${w} subtotal: ${c.toFixed(4)}`);
      console.log(`  --- Model Studio total: ${total.toFixed(4)}`);
    });' || echo "  (could not parse billing data)"
else
  echo "  (billing API unavailable)"
fi

# Daily window: the month to date when that is at least 14 days, otherwise the
# last 14 days (reaching back into the previous month). DAILY is the finest
# granularity the billing API has, and it is queried per day and per billing
# cycle, so a window that crosses a month boundary uses two cycles. Flags any
# day over ALERT_USD (a normal day here is cents, so near a dollar is worth a look).
DAYS=$(CYCLE="$CYCLE" node -e '
  const [y, m] = process.env.CYCLE.split("-").map(Number);
  const now = new Date();
  const cur = now.getUTCFullYear() === y && now.getUTCMonth() + 1 === m;
  const end = cur ? new Date(Date.UTC(y, m - 1, now.getUTCDate())) : new Date(Date.UTC(y, m, 0));
  const start = end.getUTCDate() >= 14 ? new Date(Date.UTC(y, m - 1, 1)) : new Date(end - 13 * 864e5);
  for (let d = start; d <= end; d = new Date(+d + 864e5)) console.log(d.toISOString().slice(0, 10));')
echo "== Daily spend, $(echo "$DAYS" | head -1) .. $(echo "$DAYS" | tail -1) (USD; a day over \$$ALERT_USD is flagged)"
DAILY_FILE=$(mktemp); trap 'rm -f "$DAILY_FILE"' EXIT
for DAY in $DAYS; do
  if PAGES=$(BILL_CYCLE="${DAY%-*}" bill_pages --Granularity DAILY --BillingDate "$DAY"); then
    printf '%s\n' "$PAGES" | sed "s/^/$DAY\t/" >> "$DAILY_FILE"
  else
    printf '%s\tERR\n' "$DAY" >> "$DAILY_FILE"
  fi
done
CYCLE="$CYCLE" LIMIT="$ALERT_USD" DEVICE_WS="$DEVICE_WS" SHARED_WS="$SHARED_WS" node -e '
  const fs = require("fs"), env = process.env;
  const days = {}, items = {}, wss = new Set(), bad = new Set();
  for (const line of fs.readFileSync(process.argv[1], "utf8").split("\n").filter(Boolean)) {
    const [day, json] = line.split("\t");
    const d = (days[day] ??= {});
    if (json === "ERR") { bad.add(day); continue; }
    for (const i of JSON.parse(json).Data?.Items ?? []) {
      const [, ws = "?", model = "?"] = (i.InstanceID ?? "").split(";");
      const c = Number(i.PretaxAmount) || 0;
      wss.add(ws);
      d[ws] = (d[ws] ?? 0) + c;
      const it = (items[`${model} - ${i.BillingItem}`] ??= {});
      const w = (it[day] ??= {});
      w[ws] = (w[ws] ?? 0) + c;
    }
  }
  const label = w => w === env.DEVICE_WS ? "device" : w === env.SHARED_WS ? "shared" : `other:${w.slice(-6)}`;
  const wsList = [...wss].sort((a, b) => label(a).localeCompare(label(b)));
  const dayList = Object.keys(days).sort();
  const num = n => Math.abs(n) < 5e-5 ? "-" : n.toFixed(4);
  const tot = d => Object.values(d).reduce((a, b) => a + b, 0);
  // Left-align the first column, right-align the rest, one shared width per column.
  const table = (head, rows, rule = [], left = [0]) => {
    const all = [head, ...rows];
    const w = head.map((_, c) => Math.max(...all.map(r => String(r[c]).length)));
    const fmt = r => "  " + r.map((x, c) => left.includes(c) ? String(x).padEnd(w[c]) : String(x).padStart(w[c])).join("   ");
    const bar = "  " + w.map(n => "-".repeat(n)).join("   ");
    const out = [fmt(head), bar];
    rows.forEach((r, i) => { if (rule.includes(i)) out.push(bar); out.push(fmt(r)); });
    return out.join("\n");
  };
  const inCycle = day => day.startsWith(env.CYCLE);
  const last = dayList[dayList.length - 1];

  const colTot = w => dayList.reduce((a, day) => a + (days[day][w] ?? 0), 0);
  const rows = dayList.map(day => bad.has(day)
    ? [day, ...wsList.map(() => "?"), "billing API unavailable"]
    : [day, ...wsList.map(w => num(days[day][w] ?? 0)), num(tot(days[day]))]);
  rows.push(["Total", ...wsList.map(w => num(colTot(w))), num(dayList.reduce((a, day) => a + tot(days[day]), 0))]);
  const flags = dayList.map(day => tot(days[day]) > Number(env.LIMIT) ? "  <-- OVER THRESHOLD" : "");
  const t = table(["Date", ...wsList.map(label), "Day total"], rows, [rows.length - 1]).split("\n");
  t.forEach((l, i) => console.log(l + (flags[i - 2] ?? "")));

  const windowTotal = dayList.reduce((a, day) => a + tot(days[day]), 0);
  const mtd = dayList.filter(inCycle).reduce((a, day) => a + tot(days[day]), 0);
  console.log(`\n  Month to date: $${mtd.toFixed(2)}   Window: $${windowTotal.toFixed(2)}`);
  if (new Date().toISOString().slice(0, 7) === env.CYCLE) {
    const mdays = new Date(Date.UTC(+env.CYCLE.slice(0, 4), +env.CYCLE.slice(5), 0)).getUTCDate();
    const l3 = dayList.slice(-3), avg = l3.reduce((a, day) => a + tot(days[day]), 0) / l3.length, left = mdays - Number(last.slice(8));
    console.log(`  Last-3-day average: $${avg.toFixed(2)}/day   Projected month total: $${(mtd + avg * left).toFixed(2)} (${left} days left)`);
  }

  const sum = (it, pred) => dayList.filter(pred).reduce((a, day) => a + tot(items[it][day] ?? {}), 0);
  const li = Object.keys(items).map(it => ({ it, d: sum(it, x => x === last), w: sum(it, () => true), m: sum(it, inCycle) }))
    .filter(r => r.w > 0).sort((a, b) => b.m - a.m || b.w - a.w);
  console.log("\n== Line items (USD, biggest month-to-date first)");
  console.log(table(["Model - billing item", last, "Window", "Month to date"],
    [...li.map(r => [r.it, num(r.d), num(r.w), num(r.m)]),
     ["Total", num(li.reduce((a, r) => a + r.d, 0)), num(li.reduce((a, r) => a + r.w, 0)), num(li.reduce((a, r) => a + r.m, 0))]],
    [li.length]));

  console.log("\n== Last three days, by workspace and line item (USD)");
  for (const day of dayList.slice(-3)) {
    const r = [];
    for (const w of wsList) for (const it of Object.keys(items).sort()) {
      const c = items[it][day]?.[w] ?? 0;
      if (c > 0) r.push([label(w), it, num(c)]);
    }
    console.log(`  ${day}  total ${num(tot(days[day]))}`);
    if (r.length) console.log(table(["Workspace", "Model - billing item", "USD"], r, [], [0, 1]).replace(/^/gm, "  "));
  }' "$DAILY_FILE" || echo "  (could not parse billing data)"

# Web search is billed per call and has been the MAJORITY of this project's
# spend (~$0.0115 a search against ~$0.0015 per 1K tokens), so a turn that
# searches costs roughly as much as 8000 tokens. Worth watching directly.
echo "== Device, from the Pi's journal (live, no billing lag)"
ssh -o ConnectTimeout=8 "$PI" '
  journalctl --user -u sichuan.service --since "'"${CYCLE}"'-01" --until "'"${NEXT}"'-01" --no-pager 2>/dev/null |
  awk "
    /\[turn\] .* sources\./ { turns++; if (\$0 !~ /, 0 sources/) searched++ }
    /\[session\] done/      { sessions++ }
    /treating as noise/     { dead++ }
    END {
      printf \"  cloud turns: %d\n  of which searched: %d\n\", turns, searched
      printf \"  sessions: %d\n  turns rejected as noise (no cloud call): %d\n\", sessions, dead
    }"' 2>/dev/null || echo "  (Pi unreachable)"
