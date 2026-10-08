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
# Each section degrades on its own: a billing call that fails prints a note
# and the script moves on, so the live device section is always reached.

set -euo pipefail

CYCLE="${1:-$(date -u +%Y-%m)}"
PROFILE="${ALIYUN_PROFILE:-glasses-deploy}"
PI="${PI:-weilie@sichuan-pi.local}"
ALERT_USD="${ALERT_USD:-1}"
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
    page=$(aliyun bssopenapi DescribeInstanceBill --BillingCycle "$CYCLE" --ProductCode sfm \
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

# Last three days, by workspace and model. DAILY is the finest granularity the
# billing API has. Flags any day over ALERT_USD (a normal day here is cents,
# so anything near a dollar is worth a look).
echo "== Daily, last 3 days (flag if a day exceeds \$$ALERT_USD)"
for back in 2 1 0; do
  DAY=$(date -u -v-${back}d +%Y-%m-%d 2>/dev/null || date -u -d "-$back day" +%Y-%m-%d)
  [ "${DAY%-*}" = "$CYCLE" ] || continue
  if PAGES=$(bill_pages --Granularity DAILY --BillingDate "$DAY"); then
    printf '%s' "$PAGES" | DAY="$DAY" LIMIT="$ALERT_USD" node -e '
      let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
        const rows = {}; let total = 0;
        for (const line of s.split("\n").filter(Boolean))
          for (const i of JSON.parse(line).Data?.Items ?? []) {
            const [, ws = "?", model = "?"] = (i.InstanceID ?? "").split(";");
            const k = `${ws}  ${model}  ${i.BillingItem}`;
            rows[k] = (rows[k] ?? 0) + (Number(i.PretaxAmount) || 0);
            total += Number(i.PretaxAmount) || 0;
          }
        const flag = total > Number(process.env.LIMIT) ? "  <-- OVER THRESHOLD" : "";
        console.log(`  ${process.env.DAY}: ${total.toFixed(4)}${flag}`);
        for (const [k, c] of Object.entries(rows).sort()) if (c > 0) console.log(`    ${k}: ${c.toFixed(4)}`);
      });' || echo "  $DAY: (could not parse billing data)"
  else
    echo "  $DAY: (billing API unavailable)"
  fi
done

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
