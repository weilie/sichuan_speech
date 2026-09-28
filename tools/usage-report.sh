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
# Optional: ALIYUN_PROFILE (default glasses-deploy), PI (default the device).
#
# Billing lags a few hours, so today's usage appears later in the day. The
# device-side section below is live, and is the one to look at for "what did it
# do in the last hour".

set -euo pipefail

CYCLE="${1:-$(date -u +%Y-%m)}"
PROFILE="${ALIYUN_PROFILE:-glasses-deploy}"
PI="${PI:-weilie@sichuan-pi.local}"

echo "== Bill overview $CYCLE (USD, pre-tax)"
aliyun bssopenapi QueryBillOverview --BillingCycle "$CYCLE" \
  --profile "$PROFILE" --region ap-southeast-1 |
  node -e '
    let s = ""; process.stdin.on("data", d => s += d).on("end", () => {
      for (const i of JSON.parse(s).Data?.Items?.Item ?? [])
        console.log(`  ${i.ProductName} / ${i.ProductDetail}: ${Number(i.PretaxAmount).toFixed(4)}`);
    });'

echo "== Model Studio by workspace / model"
TOKEN=""; PAGES=""
while :; do
  PAGE=$(aliyun bssopenapi DescribeInstanceBill --BillingCycle "$CYCLE" --ProductCode sfm \
    --IsBillingItem true --MaxResults 300 ${TOKEN:+--NextToken "$TOKEN"} \
    --profile "$PROFILE" --region ap-southeast-1)
  PAGES+="$PAGE"$'\n'
  TOKEN=$(printf '%s' "$PAGE" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>process.stdout.write(JSON.parse(s).Data?.NextToken ?? ""))')
  [ -z "$TOKEN" ] && break
done
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
    console.log(`  --- Model Studio total: ${total.toFixed(4)}`);
  });'

# Web search is billed per call and has been the MAJORITY of this project's
# spend (~$0.0115 a search against ~$0.0015 per 1K tokens), so a turn that
# searches costs roughly as much as 8000 tokens. Worth watching directly.
echo "== Device, from the Pi's journal (live, no billing lag)"
ssh -o ConnectTimeout=8 "$PI" '
  journalctl --user -u sichuan.service --since "'"${CYCLE}"'-01" --no-pager 2>/dev/null |
  awk "
    /\[turn\] .* sources\./ { turns++; if (\$0 !~ /, 0 sources/) searched++ }
    /\[session\] done/      { sessions++ }
    /treating as noise/     { dead++ }
    END {
      printf \"  cloud turns: %d\n  of which searched: %d\n\", turns, searched
      printf \"  sessions: %d\n  turns rejected as noise (no cloud call): %d\n\", sessions, dead
    }"' 2>/dev/null || echo "  (Pi unreachable)"
