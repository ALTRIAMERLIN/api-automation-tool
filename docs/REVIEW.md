# REVIEW — Entire review wiring and publishing (executor instructions)

You (the executor) run this process yourself. Use only the facts and commands in this file. Do not explore the `entire` CLI, do not run `--help`, do not run any other subcommand, and do not inspect the Entire service in any other way. If something here does not work as described, stop and escalate (PLAN.md, "How to escalate").

---

## 1. Verified facts (do not re-check them)

- Entire project: `et/altria`.
- Repository URI: `entire://aws-us-east-2.entire.io/et/altria/api-automation-tool`.
- Three review agents are already attached to every repo in the project: **Code review** (Claude Opus 5.5), **Security review** and **Slop**. All three fire on every push to a branch that is covered by a trail.
- A review is triggered by a **trail** (a change object), never by pushes alone. Without a trail, pushes are not reviewed.
- The base branch `baseline` may contain only the spec documents plus an empty project skeleton, and it must be the root ancestor of the review branch `review/v1`. Otherwise trail creation fails with a "no commit to pin" error. PLAN T00 sets this up. Never rewrite it.
- **Every** `entire` CLI call, and **every** git operation against the `entire` remote (push, ls-remote, fetch), must run with the environment variable `ENTIRE_TOKEN_STORE=file`, set **inside the script file that runs it**. The OS keyring store fails outside the desktop console session. So never type these commands directly into the shell. Always run a script from §3.
- Allowed `entire` commands. These two, and nothing else:
  - `entire trail create --project et/altria --repo entire://aws-us-east-2.entire.io/et/altria/api-automation-tool --branch review/v1 --base baseline --title <title> --body <body>`
  - `entire trail finding list <trail-number> --project et/altria --repo entire://aws-us-east-2.entire.io/et/altria/api-automation-tool --branch review/v1 --status any --json`

## 2. Branch model

```
main      : docs commits (brief + 4 docs) → skeleton commit          (local only until T31)
baseline  : = the skeleton commit on main, frozen forever             (pushed to entire)
review/v1 : baseline + every task commit + every review-fix commit    (pushed to entire, covered by the trail)
```
All work happens on `review/v1`. `main` is fast-forwarded to `review/v1` only in §7.

## 3. Script files (create in T02; they live in `ops/`, which is git-ignored)

Run every script from the repo root as:
`powershell -NoProfile -ExecutionPolicy Bypass -File ops\<script>.ps1 [args]`

Every script uses `$ErrorActionPreference = "Continue"` and checks `$LASTEXITCODE` after every native command. In Windows PowerShell 5.1, `Stop` turns git's normal progress output on stderr into a terminating error, so do not use `Stop`.

### 3.1 `ops/entire-remote-setup.ps1`
```powershell
$env:ENTIRE_TOKEN_STORE = "file"
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$url = "entire://aws-us-east-2.entire.io/et/altria/api-automation-tool"
$names = @(git remote)
if ($names -notcontains "entire") {
    git remote add entire $url
    if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: git remote add"; exit 1 }
} else {
    $current = git remote get-url entire
    if ($current -ne $url) { Write-Output "FAILED: remote 'entire' points to $current"; exit 1 }
}
git ls-remote entire
if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: git ls-remote entire (exit $LASTEXITCODE)"; exit 1 }
Write-Output "OK: remote entire ready"
exit 0
```

### 3.2 `ops/entire-push.ps1`
```powershell
param([switch]$IncludeBaseline)
$env:ENTIRE_TOKEN_STORE = "file"
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "review/v1") { Write-Output "FAILED: current branch is '$branch', expected review/v1"; exit 1 }
$dirty = git status --porcelain
if ($dirty) { Write-Output "FAILED: working tree not clean:"; $dirty; exit 1 }
$leak = git ls-files -- ops video data
if ($leak) { Write-Output "FAILED: forbidden paths are tracked:"; $leak; exit 1 }

if ($IncludeBaseline) {
    git push entire refs/heads/baseline:refs/heads/baseline
    if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: push baseline (exit $LASTEXITCODE)"; exit 1 }
}
git push entire refs/heads/review/v1:refs/heads/review/v1
if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: push review/v1 (exit $LASTEXITCODE)"; exit 1 }

$sha = (git rev-parse HEAD).Trim()
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Add-Content -Path "ops\review-log.md" -Value "- $stamp pushed review/v1 $sha" -Encoding UTF8
Write-Output "OK: pushed $sha at $stamp"
exit 0
```
Never add `--force` or `--force-with-lease`. A rejected push means the history went wrong. Escalate.

### 3.3 `ops/entire-trail-create.ps1`
```powershell
$env:ENTIRE_TOKEN_STORE = "file"
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path "ops\trail-number.txt") { Write-Output "FAILED: trail already created (ops\trail-number.txt exists)"; exit 1 }

$title = "api-automation-tool v1"
$body  = "Full v1 implementation of api-automation-tool, built task by task from docs/PLAN.md against docs/SPEC.md and docs/ACCEPTANCE.md. Base 'baseline' holds only the spec documents and an empty skeleton. Please review code quality, security (secret handling, CSRF, host check, CSV/Excel formula injection, SSRF via next_url) and slop."

$out = & entire trail create --project et/altria --repo entire://aws-us-east-2.entire.io/et/altria/api-automation-tool --branch review/v1 --base baseline --title $title --body $body 2>&1
$code = $LASTEXITCODE
$text = ($out | ForEach-Object { "$_" }) -join "`n"
[IO.File]::WriteAllText((Join-Path (Get-Location) "ops\trail-create-output.txt"), $text, (New-Object Text.UTF8Encoding $false))
Write-Output $text
Write-Output "EXIT: $code"
exit $code
```

### 3.4 `ops/entire-findings.ps1`
```powershell
param([Parameter(Mandatory = $true)][int]$Trail)
$env:ENTIRE_TOKEN_STORE = "file"
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path "ops\findings" | Out-Null

$out = & entire trail finding list $Trail --project et/altria --repo entire://aws-us-east-2.entire.io/et/altria/api-automation-tool --branch review/v1 --status any --json
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Output "FAILED: finding list (exit $code)"; exit $code }

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$file = Join-Path (Get-Location) "ops\findings\findings-$stamp.json"
[IO.File]::WriteAllText($file, (($out | ForEach-Object { "$_" }) -join "`n"), (New-Object Text.UTF8Encoding $false))
Write-Output $file
exit 0
```
Stdout is not merged with stderr here, so the saved file stays valid JSON.

### 3.5 `ops/open-findings.ps1` (local JSON reader, no network)
```powershell
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = "Continue"
$closed = @("resolved", "fixed", "closed", "dismissed", "wontfix", "won't fix", "false_positive", "outdated", "superseded")
$raw = (Get-Content -Raw -Encoding UTF8 $File).Trim()
$list = $null
if ($raw -eq "[]") { $list = @() }
else {
    try { $data = $raw | ConvertFrom-Json } catch { Write-Output "SCHEMA-UNKNOWN: not JSON"; exit 3 }
    if ($data -is [System.Array]) { $list = $data }
    elseif ($null -ne $data) {
        foreach ($p in @("findings", "items", "data", "results")) {
            if ($data.PSObject.Properties.Name -contains $p) {
                if ($null -eq $data.$p) { $list = @() } else { $list = @($data.$p) }
                break
            }
        }
    }
}
if ($null -eq $list) { Write-Output "SCHEMA-UNKNOWN: no findings array"; exit 3 }

$open = @(); $sig = @()
foreach ($f in $list) {
    $names = $f.PSObject.Properties.Name
    $statusField = @("status", "state") | Where-Object { $names -contains $_ } | Select-Object -First 1
    $idField = @("id", "finding_id", "number", "uuid") | Where-Object { $names -contains $_ } | Select-Object -First 1
    if (-not $statusField -or -not $idField) { Write-Output "SCHEMA-UNKNOWN: finding without id/status field"; exit 3 }
    $st = "$($f.$statusField)".ToLowerInvariant()
    $sig += "$($f.$idField)=$st"
    if ($closed -notcontains $st) { $open += $f }
}
$signature = ($sig | Sort-Object) -join ";"
Write-Output "TOTAL: $($list.Count)"
Write-Output "OPEN: $($open.Count)"
Write-Output "SIGNATURE: $signature"
foreach ($f in $open) { Write-Output "---"; $f | ConvertTo-Json -Depth 10 }
exit 0
```
- The first time it runs (in T02), open the JSON file yourself and write `ops/findings-schema-notes.md`. Name the fields that hold id, status, severity, agent/reviewer, file/line and message, and list every status value you see. If the script printed `SCHEMA-UNKNOWN`, or a status value you see is neither clearly open nor in `$closed`, stop and escalate with the JSON file attached. Do not guess. The human will tell you the correct fields and statuses, and you then update this local script (it is not reviewed code).

## 4. One-time setup (PLAN T02)

1. Create the five scripts in §3 and `ops/review-log.md` (heading `# Review log`).
2. Run `ops\entire-remote-setup.ps1`. It must print `OK`.
3. Run `ops\entire-push.ps1 -IncludeBaseline`. It must print `OK`.
4. Run `ops\entire-trail-create.ps1`.
   - If the output mentions "no commit to pin" (or any pin/ancestor error): **stop and escalate**. Do not recreate branches.
   - Otherwise, read the trail number from `ops\trail-create-output.txt` and write it alone (digits only) to `ops\trail-number.txt`. If you cannot find a number in the output, escalate with the file.
5. Follow §5 (settle) and §6 (fix loop) for CP0.

## 5. Waiting for findings (the "settle" rule)

After every push to `review/v1` (and after trail creation):
1. Wait 15 minutes. Use `Start-Sleep -Seconds 900` in a single shell call with a long enough timeout, or sleep in 5-minute chunks.
2. Run `ops\entire-findings.ps1 -Trail <n>`, then `ops\open-findings.ps1 -File <printed path>`.
3. Wait 5 minutes and repeat step 2.
4. **Settled** means the last 2 consecutive `SIGNATURE` lines are identical. At **CP5**, the last **3** must be identical. If the notes from §3.5 show a per-finding commit or review-run field, the result is settled only when all three agents have reported on the pushed SHA.
5. If it has not settled 90 minutes after the push, stop and escalate.
6. Append to `ops/review-log.md`: the checkpoint, the pushed SHA, the findings file name, TOTAL and OPEN.

## 6. Fix loop

When the settled result has `OPEN: 0`, the checkpoint is clean. Continue with the next task.

Otherwise, for each open finding:
1. Read it fully: agent, file, line, message.
2. Decide whether it is a real issue:
   - **Real**: fix it in the smallest correct way that stays inside SPEC.md. If the fix changes behavior, add or extend a test that would have caught it. Never weaken, delete or edit an existing test or expected fixture to make a finding go away (G3). If the correct fix would contradict SPEC.md, escalate instead.
   - **Not real** (a false positive, or a request for out-of-scope features): do not change the code to appease it, and do not try to dismiss it (you have no dismiss command). Write the finding ID and your reasoning in `ops/review-log.md` and escalate to the human, who decides.
3. Commit each fix separately: `review: <finding id> <short summary>`. Run the G2 gate before every commit.
4. When all real findings are fixed, run `ops\entire-push.ps1` (no `-IncludeBaseline`) and go back to §5.

Limits: at most 5 fix pushes per checkpoint. If a finding stays open after 2 pushes that were meant to fix it, escalate. Never push work for the next phase while the current checkpoint has open findings.

## 7. Publishing (PLAN T31, only after CP5 is clean)

Preconditions: the CP5 result is settled with `OPEN: 0`. `git rev-parse review/v1` equals the SHA recorded as clean in `ops/review-log.md`. The working tree is clean. If any commit was made after that review, push it and get a clean review first.

1. `gh auth status`. If you are not logged in, escalate. Do not log in with a token you find anywhere.
2. `git switch main`, then `git merge --ff-only review/v1`. If the fast-forward fails, escalate.
3. Confirm that `git rev-parse main` equals the clean SHA.
4. `gh repo create api-automation-tool --public --description "Python tool with a simple web UI: connect REST APIs, handle pagination, flatten JSON, export CSV/Excel. Demo mode included." --source . --remote origin`. Do not pass `--push`.
5. `git push origin refs/heads/main:refs/heads/main`. Push only `main`. Never push `baseline` or `review/v1` to GitHub.
6. Verify: `git ls-remote origin` lists only `refs/heads/main` (and `HEAD`) with the clean SHA. `gh repo view api-automation-tool --json visibility,url` shows `PUBLIC`.
7. Wait for CI: `gh run list --branch main --limit 1`, then `gh run watch <id> --exit-status`. If CI fails, do not hotfix on GitHub. Fix it on `review/v1`, run it through review (§5–§6), then repeat steps 2–7 (step 4 is skipped because the repo exists).
8. Paste the outputs of steps 3, 6 and 7 into `ops/review-log.md` (AC-49). Tell the human the repo URL.

GitHub pushes do not need `ENTIRE_TOKEN_STORE`. They must never go through the `entire` remote.
