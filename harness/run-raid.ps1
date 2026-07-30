<#
.SYNOPSIS
  Start the SPT server, start the client against it, and tear both down when
  the client closes. Runs the pre-raid and post-raid protocol checks around it.

.DESCRIPTION
  The point is not saving keystrokes. It is that the checks around a run stop
  being things someone remembers to do:

    before   which commit is the deployed plugin, and does it match the
             approved one; is the config what the protocol assumes; is
             anything already running
    after    which log did this run produce, and what does the latch
             validator say about it

  Nothing here modifies the plugin, the config, or a profile. It starts two
  processes, waits, and stops the one it started.

.PARAMETER DryRun
  Run both check phases and print what would be launched. Starts nothing.
  Safe to run at any time, including while the game is open.

.PARAMETER CaptureArgs
  Start the server and the *launcher*, wait for EscapeFromTarkov.exe to
  appear, and record its command line to harness/launch-args.json. Use this
  once. After that the client is started directly and no launcher click is
  needed.

.PARAMETER ExpectCommit
  Fail before starting anything if the deployed plugin was not built from
  this commit. Defaults to the contents of harness/GO if that file exists.

.PARAMETER Force
  Continue past a failed pre-flight check. Prints what it is overriding.

.PARAMETER NoPresentMon
  Run without a frame capture, and without prompting for elevation.

.PARAMETER PresentMonExe
  Path to PresentMon. Defaults to the copy in Downloads.

.PARAMETER Elevated
  Internal. Set only by the elevated copy this script launches, as the guard
  that stops a failed elevation from looping. Passing it by hand asserts
  something it cannot make true - the script reports what it MEASURES.

.PARAMETER TestElevation
  Exercise the elevation plumbing without a raid: re-exec elevated, then dry
  run in the elevated copy, so nothing starts. The elevation path is otherwise
  only reachable by a real run, and a first test that costs a raid is a bad
  first test.

.EXAMPLE
  .\run-raid.ps1 -DryRun
  .\run-raid.ps1 -DryRun -TestElevation
  .\run-raid.ps1 -CaptureArgs
  .\run-raid.ps1
#>
[CmdletBinding()]
param(
    [switch] $DryRun,
    [switch] $CaptureArgs,
    [string] $ExpectCommit,
    [switch] $Force,
    [switch] $NoPresentMon,
    [string] $PresentMonExe,
    # Recursion sentinel for the self-elevation below. Set only by the elevated
    # child we spawn. A guard that is set by the thing it guards against is the
    # only kind that cannot loop.
    [switch] $Elevated,
    # Exercise the elevation plumbing without a raid. -DryRun normally skips
    # elevation so pre-flight stays frictionless; with this it re-execs anyway and
    # the elevated child dry-runs, so nothing starts. It exists because the
    # elevation path is otherwise untestable except by a real run, and this project
    # has spent a day learning where untested paths keep their defects.
    [switch] $TestElevation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- layout ----

$HarnessDir  = $PSScriptRoot
$RepoDir     = Split-Path -Parent $HarnessDir
$InstallDir  = 'F:\SPT\SPT4.0.13'
$ServerDir   = Join-Path $InstallDir 'SPT'
$ServerExe   = Join-Path $ServerDir 'SPT.Server.exe'
$LauncherExe = Join-Path $ServerDir 'SPT.Launcher.exe'
$ClientExe   = Join-Path $InstallDir 'EscapeFromTarkov.exe'
$PluginDll   = Join-Path $InstallDir 'BepInEx\plugins\Framesaver.dll'
$ConfigFile  = Join-Path $InstallDir 'BepInEx\config\framesaver.ai.perf.cfg'
$ProtocolFile = Join-Path $InstallDir 'BepInEx\config\framesaver.protocol.ini'
$LogDir      = Join-Path $InstallDir 'BepInEx\plugins\Framesaver-logs'
$BepInExLog  = Join-Path $InstallDir 'BepInEx\LogOutput.log'
$ProfileDir  = Join-Path $ServerDir 'user\profiles'
$HttpConfig  = Join-Path $ServerDir 'SPT_Data\configs\http.json'
$ArgsFile    = Join-Path $HarnessDir 'launch-args.json'
$GoFile      = Join-Path $HarnessDir 'GO'
$RegFile     = Join-Path $HarnessDir 'registrations.json'

$Provenance  = Join-Path $RepoDir 'analysis\build-provenance.py'
$LatchCheck  = Join-Path $RepoDir 'analysis\check-boundary-latch.py'

# PresentMon measures the one place our own telemetry cannot see: the gap
# between a frame ending and the next beginning. Every steady-state stall over
# 250 ms in the corpus lives there, unattributed, and no field we could add
# inside the process would reach it. So the capture is not a nice-to-have and
# must not depend on anyone remembering to start it.
if (-not $PresentMonExe) {
    $PresentMonExe = Join-Path $env:USERPROFILE 'Downloads\PresentMon-2.5.1-x64.exe'
}
# Written under a fixed working name and RENAMED in post-flight to match the
# ndjson stem. Naming it up front from the harness's own clock would look right
# and be wrong: the ndjson timestamp comes from the plugin at its startup, not
# from here, so the two names would disagree by however long the client took to
# load and every join would start with a guess. The stem is already how
# Player.log and BepInEx.log are kept beside their run.
$PmWorking   = Join-Path $LogDir 'presentmon-inflight.csv'
$PmSession   = 'Framesaver'

$script:Failures = 0
$script:PmProc   = $null

function Say    { param($m) Write-Host $m }
function Head   { param($m) Write-Host ''; Write-Host "== $m" -ForegroundColor Cyan }
function Ok     { param($m) Write-Host "   ok   $m" -ForegroundColor Green }
function Note   { param($m) Write-Host "   --   $m" -ForegroundColor DarkGray }
function Warn   { param($m) Write-Host "   warn $m" -ForegroundColor Yellow }
function Bad    { param($m) Write-Host "   FAIL $m" -ForegroundColor Red; $script:Failures++ }

# ------------------------------------------------------------- pre-flight ----

function Get-BackendUrl {
    <#
      Host and port come from http.json, which is the current truth. The
      SCHEME does not appear there at all, and an earlier version of this
      script assumed http:// - wrong. The launcher's ClientConfig defaults to
      https, and the game's own Player.log records
      https://127.0.0.1:6969 for a real launcher-driven session.

      That would have failed at connect and cost a launch. It was caught by
      reading the engine's record of what it was actually given rather than
      deriving it from config, which is the rule that keeps earning its keep
      today: prefer the log of the thing that acted.
    #>
    $http = Get-Content -Raw -LiteralPath $HttpConfig | ConvertFrom-Json
    # backendIp/backendPort are what the client is told to talk to; ip/port are
    # what the server binds. They are normally the same and need not be.
    $url = "https://{0}:{1}" -f $http.backendIp, $http.backendPort

    # If the game has ever been launched here, compare against what it was
    # handed. A disagreement is worth seeing rather than silently resolving.
    $observed = Get-ObservedBackendUrl
    if ($observed -and $observed -ne $url) {
        Warn "http.json implies $url but the last real launch used $observed"
        Note 'using the observed value - the game is the authority on what worked'
        $url = $observed
    }
    $url
}

function Get-ObservedBackendUrl {
    # The last `key:config value:{...}` line in Player.log is BSG's own parser
    # echoing what it was passed. Single-quoted JSON, so this reads the field
    # directly rather than trying to deserialise it.
    $logs = @("$env:LOCALAPPDATA" + 'Low\Battlestate Games\EscapeFromTarkov\Player.log',
              "$env:LOCALAPPDATA" + 'Low\Battlestate Games\EscapeFromTarkov\Player-prev.log')
    foreach ($p in $logs) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $m = Select-String -LiteralPath $p -Pattern "key:config value:.*'BackendUrl'\s*:\s*'([^']+)'" |
             Select-Object -Last 1
        if ($m) { return $m.Matches[0].Groups[1].Value }
    }
    $null
}

function Get-Token {
    # The client's -token is the profile id, which is also the file name. SPT
    # parses it with a plain string Replace, so anything extra breaks it.
    $profiles = @(Get-ChildItem -LiteralPath $ProfileDir -Filter '*.json' -File)
    if ($profiles.Count -eq 0) { throw "no profile in $ProfileDir" }
    if ($profiles.Count -gt 1) {
        throw ("$($profiles.Count) profiles in $ProfileDir - " +
               "this harness will not pick one for you: " +
               ($profiles.Name -join ', '))
    }
    [IO.Path]::GetFileNameWithoutExtension($profiles[0].Name)
}

function Test-AlreadyRunning {
    <#
      Refuse rather than adding a second server. Two servers on one port is a
      confusing state that looks like a working one.

      NOW REPORTS WHICH INSTALL, and that is not cosmetic. On 2026-07-29 a second
      SPT install on this machine (F:\SPT\Base, SPT 4.0.11, used by the DRIP port)
      turned out to carry the SAME backend port in its own http.json: 127.0.0.1:6969.
      Both installs bind it, so only one server can hold it at a time.

      The failure that makes this worth naming: launch our client while the OTHER
      install's server owns the port and the client talks to THAT server - a
      different SPT version, a different profile, another project's database
      mutations. Our telemetry header reads sptAssembly from the CLIENT assembly, so
      it would record 4.0.13 while the server answering was 4.0.11. The header would
      look right and the run would be contaminated.

      This check caught it by accident - it matches any process named SPT.Server,
      not one scoped to our install - so it fired on a foreign server for a reason
      it was not written for. Making it deliberate: report the path, and say
      FOREIGN INSTALL explicitly, because the remedy differs. A second server from
      OUR install means close the one you forgot about. A server from another
      install means the machine is shared right now and -Force would cross-wire the
      run rather than merely duplicating it.
    #>
    $busy = @()
    foreach ($n in 'SPT.Server', 'EscapeFromTarkov', 'SPT.Launcher') {
        foreach ($p in @(Get-Process -Name $n -ErrorAction SilentlyContinue)) {
            # .Path throws for processes we cannot open; unknown is reported as
            # unknown rather than silently treated as ours.
            $path = $null
            try { $path = $p.Path } catch { $path = $null }

            if (-not $path) {
                $busy += "$n (pid $($p.Id)) - path unreadable, install UNKNOWN"
            }
            elseif ($path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) {
                $busy += "$n (pid $($p.Id)) from THIS install"
            }
            else {
                $busy += ("$n (pid $($p.Id)) from a FOREIGN INSTALL: $path" +
                          " - it may own backend port 6969, and -Force would point this run at it")
            }
        }
    }
    $busy
}

function Show-MismatchCase {
    <#
      A stamp mismatch has two causes with opposite remedies, and the operator
      cannot tell them apart from the hashes alone:

        stale approval   the deploy moved on and nobody has verified it
        stale deploy     the approved build is not the one on disk

      Which it is follows from ancestry plus whether any *build input* differs.
      A commit that changes only docs moves the stamp without moving any IL, so
      "the commits differ" and "the program differs" are not the same question.
    #>
    param([string] $Approved, [string] $Deployed)

    Push-Location $RepoDir
    # Windows PowerShell wraps a native command's stderr in an ErrorRecord, and
    # under 'Stop' that is terminating - so git explaining itself would abort the
    # diagnosis. This function runs only when something is already wrong, which
    # is the worst possible place to throw.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $known = $true
        foreach ($c in @($Approved, $Deployed)) {
            # --verify --quiet prints nothing on a bad ref, so there is no stderr
            # to wrap in the first place.
            $null = & git rev-parse --verify --quiet "$c^{commit}"
            if ($LASTEXITCODE -ne 0) { Note "commit $c is not in this repo"; $known = $false }
        }
        if (-not $known) {
            Note 'cannot classify the mismatch without both commits.'
            return
        }

        $inputs = @(& git diff --name-only "$Approved..$Deployed" -- '*.cs' '*.csproj' 2>$null)
        $inputs += @(& git diff --name-only "$Deployed..$Approved" -- '*.cs' '*.csproj' 2>$null)
        $inputs = @($inputs | Sort-Object -Unique)

        & git merge-base --is-ancestor $Approved $Deployed 2>$null
        $approvedIsOlder = ($LASTEXITCODE -eq 0)
        & git merge-base --is-ancestor $Deployed $Approved 2>$null
        $deployedIsOlder = ($LASTEXITCODE -eq 0)

        if ($inputs.Count -eq 0) {
            # Deliberately says nothing about which side is newer. With no build
            # input differing the two builds are the same program, so the
            # direction does not change the remedy - and naming a direction here
            # would be asserting more than the evidence carries.
            Note 'no .cs or .csproj differs between them - the two builds are the'
            Note 'same program, whichever is newer. Nothing material changed.'
            Note 'Re-verify and rewrite harness/GO; -Force is defensible here.'
        }
        elseif ($approvedIsOlder) {
            Note "$($inputs.Count) build input(s) differ and the deployed build is NEWER:"
            $inputs | ForEach-Object { Note "  $_" }
            Note 'STALE APPROVAL with real code changes - nobody has verified what is'
            Note 'on disk. Do not -Force this one; get it verified.'
        }
        elseif ($deployedIsOlder) {
            Note "$($inputs.Count) build input(s) differ and the deployed build is OLDER:"
            $inputs | ForEach-Object { Note "  $_" }
            Note 'STALE DEPLOY - the approved build is not the one installed.'
            Note 'Deploy the approved artifact rather than overriding.'
        }
        else {
            Note 'the two commits are unrelated - neither is an ancestor of the other.'
            Note 'Do not proceed on either; work out where each binary came from.'
        }
    }
    finally {
        $ErrorActionPreference = $prevEap
        Pop-Location
    }
}

function Test-Registrations {
    <#
      Refuse GO while a registered prediction's precondition is unresolved.

      On 2026-07-28 a registration stated its own dependency - "if item 4 also
      latches endToStart at the boundary, this needs re-deriving BEFORE the
      raid" - assigned it, and the raid ran anyway. Nobody forgot. Nothing in
      the path from registration to GO had to look at it.

      So the default does the work, not the gate: unresolved unless stated, and
      a missing field is unresolved too. Silence blocks rather than passes.
    #>
    if (-not (Test-Path -LiteralPath $RegFile)) {
        Warn "no $([IO.Path]::GetFileName($RegFile)) - no preconditions checked"
        return
    }

    $doc = Get-Content -Raw -LiteralPath $RegFile | ConvertFrom-Json
    $regs = @($doc.registrations)
    if ($regs.Count -eq 0) { Note 'no registrations on file'; return }

    # A registration that names only the outcome it expects is decoration. Beta's
    # said "drop endToStart once endToLatch is validated" - an outcome assumed in
    # the wording - while Gamma's named a verdict for each branch, which is the
    # only reason the result could be scored against it when endToLatch failed
    # 0 of 44. Reported and never blocking: refusing a raid over a record-keeping
    # field is the class of misfire that teaches people to pass -Force.
    $noBranch = @($regs | Where-Object {
        -not ($_.PSObject.Properties.Name -contains 'ifItFails' -and $_.ifItFails)
    })
    if ($noBranch.Count -gt 0) {
        Warn ("$($noBranch.Count) registration(s) name no failure branch: " +
              ($noBranch.id -join ', '))
        Note '  a prediction whose failure is undescribed cannot be scored against'
    }

    foreach ($r in $regs) {
        # Read the property defensively: absent and 'unresolved' must behave
        # identically, or the default stops being the design.
        $state = 'unresolved'
        if ($r.PSObject.Properties.Name -contains 'precondition' -and $r.precondition) {
            $state = [string] $r.precondition
        }
        if ($state -eq 'resolved') {
            $who = 'unattributed'
            if ($r.PSObject.Properties.Name -contains 'resolvedBy' -and $r.resolvedBy) { $who = $r.resolvedBy }
            if ($who -eq 'unattributed') {
                # Resolved by nobody is not resolved. The name is the act.
                Bad "registration '$($r.id)': resolved with no resolvedBy"
            }
            else { Ok "registration '$($r.id)': precondition resolved ($who)" }
        }
        else {
            Bad "registration '$($r.id)': precondition $state"
            if ($r.PSObject.Properties.Name -contains 'preconditionWas' -and $r.preconditionWas) {
                Note "  $($r.preconditionWas)"
            }
            Note '  resolve it and name yourself, or this raid tests a prediction'
            Note '  whose stated dependency nobody has checked.'
        }
    }

    # Gamma's caveat, and the reason this is not just the gate: registrations
    # written as prose are invisible to the loop above. Count them and say so,
    # rather than reporting a clean pass over a population this cannot see.
    $findings = Join-Path $RepoDir 'FINDINGS.md'
    if (Test-Path -LiteralPath $findings) {
        $prose = @(Select-String -LiteralPath $findings -Pattern 'Registered' -AllMatches)
        $known = @($regs | ForEach-Object { $_.id }).Count
        Note "$($prose.Count) 'Registered' mentions in FINDINGS.md; $known structured here"
        Warn 'prose registrations are NOT checked by this gate - only the structured ones'
    }
}

function Invoke-PreFlight {
    Head 'pre-flight'

    # @() because PowerShell unrolls an empty array to $null on return, and
    # Set-StrictMode then throws on .Count rather than reporting zero.
    $busy = @(Test-AlreadyRunning)
    if ($busy.Count -gt 0) { Bad ("already running: " + ($busy -join '; ')) }
    else { Ok 'nothing already running' }

    if (-not (Test-Path -LiteralPath $PluginDll)) {
        Bad "no plugin at $PluginDll"
    }
    else {
        $md5 = (Get-FileHash -LiteralPath $PluginDll -Algorithm MD5).Hash.ToLower()
        Ok "plugin md5 $md5"

        # The commit is read out of the assembly, so it cannot disagree with
        # the file the way a filename or a written-down hash can.
        $stamp = $null
        if (Test-Path -LiteralPath $Provenance) {
            $out = & python $Provenance $PluginDll 2>&1
            $line = $out | Where-Object { $_ -match 'commit\s+([0-9a-f]{7,})' } | Select-Object -First 1
            if ($line -and $line -match 'commit\s+([0-9a-f]{7,})') { $stamp = $Matches[1] }
        }
        if (-not $stamp) { Bad 'could not read the build commit out of the plugin' }
        else {
            Ok "built from commit $stamp"
            $want = $ExpectCommit
            if (-not $want -and (Test-Path -LiteralPath $GoFile)) {
                # Trim the BOM explicitly. Set-Content -Encoding utf8 on Windows
                # PowerShell writes one, and a BOM survives .Trim() - so an
                # approval file written by the obvious command would fail to
                # match a commit it names correctly. Delta hit the same trap in
                # bot.json today, in the other direction.
                $want = (Get-Content -Raw -LiteralPath $GoFile).Trim([char]0xFEFF, ' ', "`t", "`r", "`n")
            }
            if (-not $want) {
                Warn 'no expected commit given and no harness/GO file - not checked'
            }
            elseif ($stamp.StartsWith($want) -or $want.StartsWith($stamp)) {
                Ok "matches the approved commit $want"
            }
            else {
                Bad "approved commit is $want but the deployed plugin is $stamp"
                # Telling someone not to guess without handing them what they
                # need in order not to is not a check, it is an obstacle. The
                # data is one git command away, so classify the mismatch.
                Show-MismatchCase -Approved $want -Deployed $stamp
            }
        }
    }

    if (-not (Test-Path -LiteralPath $ConfigFile)) { Bad "no config at $ConfigFile" }
    else {
        # Reported, not enforced. These are choices per run; the failure this
        # prevents is discovering afterwards that one of them was not what the
        # protocol assumed.
        foreach ($key in 'Run tag', 'Window seconds', 'Spike event ms', 'Do not expand phases',
                         'Protocol step key', 'Mark key') {
            $line = Select-String -LiteralPath $ConfigFile -Pattern "^$([regex]::Escape($key)) =" |
                    Select-Object -First 1
            if ($line) { Note ($line.Line.Trim()) } else { Warn "config key missing: $key" }
        }

        # A duplicated key name is a silent trap and it cost four keypresses to
        # find. BepInEx scopes settings to their section, so appending
        # `Mark key = Mouse3` at the END of the file defines a NEW setting under
        # whatever section happens to be last - `[4. Experimental]` - while the real
        # entry under `[3. Telemetry]` keeps its old value. Both lines are present,
        # both look right in isolation, and the one you edited is the one nothing
        # reads.
        #
        # DUPLICATE NAMES ARE NOT THE TEST, and the first version of this check got
        # that wrong: it flagged `Enabled`, which appears twice entirely
        # legitimately, because `[1. Bot stand-by] Enabled` and `[3. Telemetry]
        # Enabled` are different settings. Scoping is the feature, not the bug.
        #
        # The discriminator is the header block. BepInEx writes every bound entry
        # with `## description`, `# Setting type:` and `# Default value:` above it.
        # A hand-added line has none - so an entry with no `# Default value:` above
        # it is one nobody's code reads. Same test that found an orphaned
        # `Expand phase` line left behind by a rename earlier today.
        $cfgLines = [System.IO.File]::ReadAllLines($ConfigFile)
        $orphans = @()
        for ($i = 0; $i -lt $cfgLines.Length; $i++) {
            $l = $cfgLines[$i]
            if ($l -notmatch '^[^#\[\s][^=]*=') { continue }
            # Walk back over the entry's own comment block looking for the default.
            $bound = $false
            for ($j = $i - 1; $j -ge 0 -and $j -ge $i - 6; $j--) {
                if ($cfgLines[$j] -match '^# Default value:') { $bound = $true; break }
                if ($cfgLines[$j] -match '^\s*$' -and $j -lt $i - 1) { break }
            }
            if (-not $bound) { $orphans += ("line " + ($i + 1) + ": " + $l.Trim()) }
        }
        foreach ($o in $orphans) {
            Bad ("config entry nothing reads - $o")
            Note '  hand-added lines land in whatever section is last; edit the existing entry instead'
        }
        if ($orphans.Count -eq 0) { Note 'every config entry is one the plugin binds' }

        # This one IS enforced, because a protocol step writes the config to disk.
        # ProtocolRunner assigns through ConfigEntryBase.BoxedValue and
        # SaveOnConfigSet is on by default, so the LAST arm of a protocol run
        # persists after the game closes. End a slicing raid on its treatment arm
        # and the next run starts with slicing silently applied - with the ini
        # removed, `protocol` reading null and every other signal saying "no arm".
        #
        # That is the state-without-history shape: the config is not corrupt, it
        # is a correct record of a decision made in a previous session, and
        # nothing in the run that inherits it can tell. Enforced rather than
        # reported because its cost is a whole run measured under a setting nobody
        # chose - and the run most exposed is a map sweep over maps that have
        # never been measured at all, where there is no prior number to disagree
        # with it.
        $bp = Select-String -LiteralPath $ConfigFile -Pattern '^Brain update period =' |
              Select-Object -First 1
        $hasProtocol = Test-Path -LiteralPath $ProtocolFile
        if (-not $bp) { Warn 'config key missing: Brain update period' }
        else {
            $val = ($bp.Line -split '=', 2)[1].Trim()
            $zero = ($val -as [double]) -eq 0
            if ($zero) {
                Note "Brain update period = $val"
            } elseif ($hasProtocol) {
                # A protocol is installed, so a non-zero value is plausibly its
                # arm 1 or a leftover its arm 1 will overwrite. Say so and move on.
                Warn ("Brain update period = $val with a protocol installed - " +
                      "expected if an arm sets it, stale from a previous run if not")
            } else {
                Bad ("Brain update period = $val and NO protocol is installed - " +
                     "slicing would be silently on for this whole run")
                Note 'set it to 0, or install a protocol that states its own arms'
            }
        }
        if ($hasProtocol) {
            $steps = @(Select-String -LiteralPath $ProtocolFile -Pattern '^\s*\[').Count
            Note "protocol installed: $steps step(s) - the log must agree"
        } else {
            Note 'no protocol installed - `protocol` will read null'
        }
    }

    Test-Registrations
    Test-PresentMon

    $backend = Get-BackendUrl
    Ok "backend $backend"
    try { $token = Get-Token; Ok "profile token $token" }
    catch { Bad $_.Exception.Message; $token = $null }

    [pscustomobject]@{ Backend = $backend; Token = $token }
}

# ------------------------------------------------------------- presentmon ----

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

<#
Reports whether a capture will happen, and never blocks the run over it. A
missing capture costs one raid's worth of PresentMon data; a pre-flight that
refuses the run costs the raid, and a gate that refuses runs it has no business
refusing teaches everyone to pass -Force.

Deliberately NOT using PresentMon's own --restart_as_admin: it exits the process
we launched and starts an elevated one we did not, so the handle we hold refers
to something already gone and the teardown below would silently stop nothing.
Leaving an ETW session running is the same class of failure as leaving a
headless server running, which is the thing this script exists to prevent.
#>
function Test-PresentMon {
    # Rescue an orphan FIRST, before any reason to skip today's capture. An
    # unnamed file from a previous run is a raid somebody played, and whether we
    # are elevated now has nothing to do with whether it should survive. Putting
    # this after the early returns meant it was only reachable on runs that
    # needed it least.
    if (Test-Path -LiteralPath $PmWorking) {
        $n = 0
        do { $n++; $aside = Join-Path $LogDir ("presentmon-orphan-$n.csv") }
        while (Test-Path -LiteralPath $aside)
        Move-Item -LiteralPath $PmWorking -Destination $aside
        Warn ("kept an unnamed capture from a previous run as " +
              (Split-Path $aside -Leaf))
    }

    if ($NoPresentMon) { Note 'PresentMon disabled by -NoPresentMon'; return }

    if (-not (Test-Path -LiteralPath $PresentMonExe)) {
        Warn "no PresentMon at $PresentMonExe - this run will have NO capture"
        Note 'pass -PresentMonExe <path>, or -NoPresentMon to say so on purpose'
        $script:NoPresentMon = $true
        return
    }
    if (-not (Test-Elevated)) {
        # A real run self-elevates before reaching here, so this now fires almost
        # only on a dry run - and telling someone to re-run as admin when the tool
        # does it for them is a message that has outlived its reason.
        Warn 'not elevated - PresentMon cannot open an ETW session, so NO capture'
        Note 'a real run self-elevates and prompts once at the start; a dry run does not'
        Note 'test that plumbing without a raid: -DryRun -TestElevation'
        $script:NoPresentMon = $true
        return
    }
    Ok ("PresentMon " + (Split-Path $PresentMonExe -Leaf) + ', elevated')
}

<#
Started AFTER the client, targeting its pid, which is a change from "start it
once the server is ready". --terminate_on_proc_exit means "stop when all target
processes have exited", and with no target alive yet that condition is already
true - so starting it early risks it stopping immediately, having recorded
nothing, while reporting success. Targeting the pid rather than the exe name
also makes it impossible to attach to the wrong Tarkov.

--qpc_time is the load-bearing flag: it emits CPUStartQPC, which is what joins
this capture to the `qpc` on our own spike lines. Without it the two files
cannot be aligned and the capture answers nothing.

--exclude_dropped is deliberately NOT passed. A stall that shows up in none of
GPUTime, CPUWait or CPUBusy most likely means a frame that was never presented,
and that is a result about presentation rather than a failed capture. Excluding
dropped frames would delete the evidence for it.
#>
function Start-PresentMon {
    param($ClientPid)
    if ($NoPresentMon) { return }
    Head 'presentmon'

    $a = @(
        '--process_id', $ClientPid,
        '--output_file', $PmWorking,
        '--qpc_time',
        '--v2_metrics',
        '--no_console_stats',
        '--session_name', $PmSession,
        '--stop_existing_session',
        '--terminate_on_proc_exit'
    )
    try {
        $script:PmProc = Start-Process -FilePath $PresentMonExe -ArgumentList $a `
                                       -WindowStyle Hidden -PassThru
        Ok "started pid $($script:PmProc.Id), targeting client $ClientPid"
        Note "writing $(Split-Path $PmWorking -Leaf) - renamed to match the log at the end"
    } catch {
        Warn "could not start PresentMon: $($_.Exception.Message)"
        Warn 'the run continues without a capture'
        $script:PmProc = $null
    }
}

function Stop-PresentMon {
    if (-not $script:PmProc) { return }
    Head 'presentmon'

    # --terminate_on_proc_exit should already have done this. Give it a moment,
    # because killing PresentMon mid-write is how a CSV ends on half a row.
    if (-not $script:PmProc.WaitForExit(15000)) {
        Warn 'PresentMon did not stop itself - stopping it'
        try { Stop-Process -Id $script:PmProc.Id -Force -ErrorAction Stop }
        catch { Warn "could not stop PresentMon: $($_.Exception.Message)" }
        [void] $script:PmProc.WaitForExit(5000)
    }
    if ($script:PmProc.HasExited) { Ok "stopped (code $($script:PmProc.ExitCode))" }
    else { Bad 'PresentMon is still running - its ETW session may block the next run' }

    if (-not (Test-Path -LiteralPath $PmWorking)) {
        Warn 'PresentMon wrote no file - the capture is missing, not empty'
        return
    }
    # A header-only CSV is the shape a failed capture takes, and it is the one
    # that reads as success: the file exists and parses.
    #
    # Wrapped, and this is not defensive habit. PresentMon opens the CSV with NO
    # sharing at all - not even FileShare.ReadWrite gets in - so if it is still
    # holding the handle, Get-Content THROWS. With $ErrorActionPreference = 'Stop'
    # that throw happens inside the finally block, ABOVE Stop-SptServer, and would
    # leave a headless server running: precisely the failure this whole script
    # exists to prevent, introduced by a diagnostic. Found by trying to read the
    # file mid-run, which is the only state where it bites.
    try {
        $rows = @(Get-Content -LiteralPath $PmWorking -TotalCount 3 -ErrorAction Stop).Count
        if ($rows -lt 2) { Warn 'capture has a header and no frames - it recorded nothing' }
        else { Ok ("capture has frames ({0:n0} bytes)" -f (Get-Item -LiteralPath $PmWorking).Length) }
    } catch {
        Warn "could not read the capture to check it: $($_.Exception.Message)"
        Warn 'the file is probably still locked - check it by hand before trusting it'
    }
}

# ----------------------------------------------------------------- server ----

function Start-SptServer {
    Head 'server'
    $p = Start-Process -FilePath $ServerExe -WorkingDirectory $ServerDir -PassThru
    Ok "started pid $($p.Id)"
    $p
}

function Wait-ServerReady {
    param($Proc, [int] $TimeoutSec = 180)

    # Poll for a real signal rather than sleeping. A fixed sleep is right
    # exactly once and silently wrong on either side of that.
    #
    # A TCP connect rather than an HTTP request, deliberately: SPT serves over
    # Kestrel HTTPS with a self-signed certificate, and Invoke-WebRequest in
    # Windows PowerShell rejects that by default - so an HTTPS probe would keep
    # failing against a perfectly healthy server and report "not ready" forever.
    # A check that reports the wrong thing is worse than no check.
    #
    # What this establishes is narrower than "the server works": the port is
    # accepting connections. That is the precondition the client needs, and it
    # is honest about being only that.
    $http = Get-Content -Raw -LiteralPath $HttpConfig | ConvertFrom-Json
    $bindHost = $http.ip
    $bindPort = [int] $http.port
    $sw = [Diagnostics.Stopwatch]::StartNew()

    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if ($Proc.HasExited) {
            throw "server exited during startup with code $($Proc.ExitCode)"
        }
        $client = New-Object Net.Sockets.TcpClient
        try {
            $iar = $client.BeginConnect($bindHost, $bindPort, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(1000) -and $client.Connected) {
                $client.EndConnect($iar)
                Ok ("listening on {0}:{1} after {2:n1}s" -f $bindHost, $bindPort, $sw.Elapsed.TotalSeconds)
                return
            }
        }
        catch { }
        finally { $client.Close() }
        Start-Sleep -Milliseconds 500
    }
    throw "server not listening on ${bindHost}:${bindPort} after ${TimeoutSec}s"
}

function Stop-SptServer {
    param($Proc)
    if (-not $Proc) { return }
    Head 'teardown'
    if ($Proc.HasExited) { Note "server already exited (code $($Proc.ExitCode))"; return }

    # CloseMainWindow first so the server can flush and save. Only the process
    # this script started is ever touched - never by name, because the user may
    # have a second server running deliberately.
    [void] $Proc.CloseMainWindow()
    if (-not $Proc.WaitForExit(20000)) {
        Warn 'server did not exit on request - killing'
        Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
        [void] $Proc.WaitForExit(10000)
    }
    if ($Proc.HasExited) { Ok "server stopped (code $($Proc.ExitCode))" }
    else { Bad "server pid $($Proc.Id) still running" }
}

# ----------------------------------------------------------------- client ----

function Get-SavedArgs {
    if (-not (Test-Path -LiteralPath $ArgsFile)) { return $null }
    (Get-Content -Raw -LiteralPath $ArgsFile | ConvertFrom-Json).arguments
}

function Wait-ForClient {
    param([int] $TimeoutSec = 300)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        $p = Get-Process -Name 'EscapeFromTarkov' -ErrorAction SilentlyContinue
        if ($p) { return $p | Select-Object -First 1 }
        Start-Sleep -Milliseconds 500
    }
    throw "EscapeFromTarkov.exe did not appear within ${TimeoutSec}s"
}

function Save-ClientArgs {
    param($Proc)
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId = $($Proc.Id)").CommandLine
    if (-not $cmd) { Warn 'could not read the client command line'; return }

    # Stored verbatim. The token and backend are substituted at replay time so
    # the file stays valid across a profile change, and everything else the
    # launcher passes is preserved - because a harness that launches with
    # different arguments than the launcher is measuring a different program.
    @{ capturedFrom = 'SPT.Launcher.exe'; commandLine = $cmd
       arguments = ($cmd -replace '^\s*"?[^"]*EscapeFromTarkov\.exe"?\s*', '') } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ArgsFile -Encoding utf8
    Ok "captured client arguments to $ArgsFile"
    Note $cmd
}

function Get-ClientArgs {
    <#
      One definition, used by both the launch and the dry run. An earlier
      version built the string twice and the dry run kept printing the old
      shape after the real one was corrected - a dry run that disagrees with
      the launch is worse than no dry run, because it is believed.
    #>
    param($Backend, $Token)

    $saved = Get-SavedArgs
    if ($saved) {
        # Replace the launcher's own token/config with this run's values and
        # keep every other argument exactly as captured.
        $a = $saved -replace '-token=\S+', "-token=$Token"
        $a = $a -replace '-config=\{[^}]*\}', ('-config={{"BackendUrl":"{0}"}}' -f $Backend)
        Note "replaying captured arguments"
    }
    else {
        # Read out of the launcher's own source, not guessed:
        # SPT.Launcher.Base/Controllers/GameStarter.cs:140 builds exactly this,
        # and Json.SerializeSingleQuotes sets QuoteChar to a single quote, so the
        # config really is single-quoted on the command line.
        #
        # -force-gfx-jobs native matters and an earlier version of this script
        # omitted it. It is a graphics-job threading flag, so leaving it out
        # would change `render` - the quantity Protocol B measures - against
        # every log in the corpus. boot.config also sets
        # gfx-enable-native-gfx-jobs=1, so the two agree and omitting the flag
        # may well be harmless; "may well be" is not a basis for a measurement.
        #
        # ClientConfig also carries Version and MatchingVersion. SPT's own
        # RequestHandler reads only BackendUrl, but BSG's ApplicationConfigClass
        # reads the others, so they are not decoration.
        Note 'using the launcher-equivalent arguments (from GameStarter.cs:140)'
        $a = ("-force-gfx-jobs native -token={0} " +
              "-config={{'BackendUrl':'{1}','MatchingVersion':'live','Version':'live'}}") -f $Token, $Backend
    }
    $a
}

function Start-Client {
    param($Backend, $Token)
    Head 'client'

    $a = Get-ClientArgs -Backend $Backend -Token $Token
    Note "args: $a"
    # UseShellExecute=false and the game directory as cwd, matching
    # GameStarter.cs:149-152.
    $p = Start-Process -FilePath $ClientExe -WorkingDirectory $InstallDir `
                       -ArgumentList $a -PassThru
    Ok "started pid $($p.Id)"
    $p
}

# ------------------------------------------------------------ post-flight ----

function Invoke-PostFlight {
    param($Before, [switch] $NothingRan)
    Head 'post-flight'

    $now = @(Get-ChildItem -LiteralPath $LogDir -Filter '*.ndjson' -File -ErrorAction SilentlyContinue)
    $new = @($now | Where-Object { $Before -notcontains $_.Name })

    if ($new.Count -eq 0) {
        # A dry run is *expected* to produce nothing, so warning here would fire
        # on the normal case - and a check that always fires is one nobody reads.
        if ($NothingRan) { Note 'no new log, as expected - nothing was started' }
        else { Warn 'this run produced no new ndjson - the plugin may not have loaded' }
        return
    }
    # Preserve the engine and BepInEx logs beside the ndjson, because some things
    # a run has to prove are only in them and both are overwritten on the next
    # launch. The brain-slicing arm is the live case: `cfg.brainPeriod` reports
    # the value REQUESTED, and whether slicing actually engaged past
    # `ModCompat.SuppressSlicing` appears only in the BepInEx summary. So a log
    # can read `brainPeriod: 0.1` on a vanilla arm, and the artifact that says
    # otherwise is one game start from gone. See analysis/CORPUS.md, "Recoverable,
    # but only from outside the ndjson".
    $eft = "$env:LOCALAPPDATA" + 'Low\Battlestate Games\EscapeFromTarkov'
    $sidecars = @(
        @{ From = "$eft\Player.log";              Suffix = 'Player.log' },
        @{ From = $BepInExLog;                    Suffix = 'BepInEx.log' }
    )

    foreach ($f in $new) {
        Ok ("log {0} ({1:n0} bytes)" -f $f.Name, $f.Length)

        $stem = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
        foreach ($s in $sidecars) {
            if (-not (Test-Path -LiteralPath $s.From)) {
                Warn ("no {0} to keep - {1}" -f $s.Suffix, $s.From)
                continue
            }
            $dest = Join-Path $LogDir ("{0}.{1}" -f $stem, $s.Suffix)
            # Never overwrite: a second post-flight pass over the same log must
            # not replace the copy taken when it was fresh.
            if (Test-Path -LiteralPath $dest) {
                Note ("{0} already kept" -f $s.Suffix)
                continue
            }
            try {
                Copy-Item -LiteralPath $s.From -Destination $dest -ErrorAction Stop
                Ok ("kept {0}" -f (Split-Path $dest -Leaf))
            } catch {
                Warn ("could not keep {0}: {1}" -f $s.Suffix, $_.Exception.Message)
            }
        }

        if (-not (Test-Path -LiteralPath $LatchCheck)) { continue }

        & python $LatchCheck $f.FullName
        switch ($LASTEXITCODE) {
            0 { Ok 'latch validator: passed' }
            2 { Warn 'latch validator: INCONCLUSIVE - it could not assess this log' }
            default { Bad "latch validator: failed (exit $LASTEXITCODE)" }
        }
    }

    # The capture is named here rather than at spawn time, so its name is the
    # ndjson's own stem and the pairing needs no timestamp arithmetic.
    if (Test-Path -LiteralPath $PmWorking) {
        if ($new.Count -ne 1) {
            # Two logs and one capture: which run it covers is a guess, and a
            # guess committed to a filename outlives everyone who knew it was one.
            Warn ("{0} new logs and one capture - leaving it as {1}, pair it by hand" `
                  -f $new.Count, (Split-Path $PmWorking -Leaf))
        } else {
            $stem = [System.IO.Path]::GetFileNameWithoutExtension($new[0].Name)
            $dest = Join-Path $LogDir ("{0}.presentmon.csv" -f $stem)
            if (Test-Path -LiteralPath $dest) {
                Warn ("{0} already exists - leaving the new capture unnamed" `
                      -f (Split-Path $dest -Leaf))
            } else {
                try {
                    Move-Item -LiteralPath $PmWorking -Destination $dest -ErrorAction Stop
                    Ok ("kept {0}" -f (Split-Path $dest -Leaf))
                    Note 'join it to the ndjson on CPUStartQPC against spike `qpc`'
                } catch {
                    Warn "could not name the capture: $($_.Exception.Message)"
                }
            }
        }
    } elseif (-not $NoPresentMon) {
        Warn 'no capture to keep - see the presentmon section above'
    }

    Invoke-FieldCensus $new
}

# Refuses a run whose new telemetry emitted but carries nothing.
#
# Six builds landed on 2026-07-29 and every one can fail the way this project keeps
# cataloguing: a field that emits, reads plausible, and means nothing. Strict mode is
# right here because the log was produced by the binary we just verified in pre-flight,
# so ABSENT is a defect rather than an old build.
#
# Python, not ConvertFrom-Json: our ndjson carries a UTF-8 BOM that ConvertFrom-Json
# chokes on, while utf-8-sig reads it silently. A recorded trap, not a preference.
#
# Everything here is inside try/catch because post-flight runs on the way out, above
# Stop-SptServer. An exception thrown here would strand a headless server - which is a
# defect this file has already had once, from reading a locked PresentMon capture.
function Invoke-FieldCensus {
    param($New)

    $script = Join-Path $PSScriptRoot 'check-fields.py'
    if (-not (Test-Path -LiteralPath $script)) {
        Warn 'no check-fields.py beside the harness - new fields NOT checked'
        return
    }
    if ($New.Count -ne 1) {
        # Silence here would read as a pass, so say which case we are in.
        Note ("{0} new logs - field census skipped, run it by hand per log" -f $New.Count)
        return
    }

    $log = Join-Path $LogDir $New[0].Name
    try {
        # `2>&1` here is deliberate and is NOT the recorded PowerShell 5.1 trap. That
        # trap is that redirecting a native command's stderr sets `$?` to $false even
        # on exit 0 - and we read $LASTEXITCODE, never `$?`. Verified both ways on a
        # real log: identical exit code, all lines String. Keeping the redirection so a
        # Python traceback lands in the output instead of vanishing.
        $out = & python $script $log 2>&1
        $code = $LASTEXITCODE
    } catch {
        Warn "could not run the field census: $($_.Exception.Message)"
        Warn 'the new telemetry is UNVERIFIED - check it by hand before scoring this run'
        return
    }

    foreach ($line in $out) { Note $line }

    # 2 is separate from 1 deliberately: read-nothing must never present as a pass.
    switch ($code) {
        0 { Ok 'field census: every new field present and non-degenerate' }
        1 { Bad 'field census: FAILED - do not score this run until each line is understood' }
        2 { Warn 'field census: REFUSED to report - it read nothing usable. NOT a pass.' }
        default { Warn "field census: unexpected exit $code - treat as unverified" }
    }
}

# ------------------------------------------------------------- elevation ----

<#
Re-exec self elevated, so the UAC prompt lands BEFORE anything starts.

Why not PresentMon's own --restart_as_admin: it relaunches PresentMon elevated and
the process WE started exits immediately. So $script:PmProc points at a corpse,
HasExited reads true, and every lifecycle guarantee in Start/Stop-PresentMon is
built on that handle - we could neither stop it nor tell whether it was running,
while an elevated process kept an ETW session and a write lock on the capture. The
flag does not fail loudly; it makes our own bookkeeping confidently wrong.

Why not elevate PresentMon alone: a non-elevated parent gets a Process object for an
elevated child but cannot Kill() it, so Stop-PresentMon's backstop is gone - and the
UAC prompt would arrive mid-run, stealing focus while the client is loading and
Wait-ServerReady is timing.

So: elevate the whole harness, once, at the top. Everything downstream keeps the
handle it already relies on.

Two costs, both stated rather than hidden. The elevated child gets a NEW CONSOLE, so
its output does not appear in the shell you launched from - which is why it starts a
transcript beside the logs, and the transcript is the reason the new window is
acceptable rather than a nuisance. And the server and client inherit elevation, so
the files they create are owned by an elevated process.
#>
function Invoke-SelfElevate {
    # Order matters: the sentinel is checked FIRST, so a failure to elevate can
    # never produce a second attempt.
    # The sentinel is a DECLARATION; Test-Elevated is a MEASUREMENT. Report the
    # measurement, because a flag that says "I am elevated" is exactly the shape
    # this project spent a day cataloguing - a success that survives the failure.
    if ($Elevated) {
        if (Test-Elevated) { Ok 'running elevated (re-exec)' }
        else { Warn '-Elevated was passed but this shell is NOT elevated - there will be no capture' }
        return
    }
    if (Test-Elevated) { return }
    if ($NoPresentMon) { return }   # no capture wanted, so no reason to prompt
    if ($DryRun -and -not $TestElevation) { return }   # starts nothing; the warning is the output
    if (-not (Test-Path -LiteralPath $PresentMonExe)) { return }

    Head 'elevation'
    Note 'PresentMon needs an ETW session, which needs administrator.'
    Note 'Re-launching this harness elevated - approve the UAC prompt.'
    Note 'Pass -NoPresentMon to run without a capture and without prompting.'

    # Switches carry no value and cannot be mangled. The two string parameters can,
    # so they are quoted with embedded-quote doubling - and the child ECHOES what it
    # received, so a mangled path is visible rather than silently becoming two args.
    $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $PSCommandPath), '-Elevated')
    # Forwarded only under -TestElevation, which is the one path where a dry run
    # reaches here at all. Without it a dry run returns above and never elevates.
    if ($DryRun)      { $argv += '-DryRun' }
    if ($CaptureArgs) { $argv += '-CaptureArgs' }
    if ($Force)       { $argv += '-Force' }
    if ($ExpectCommit) { $argv += @('-ExpectCommit', ('"{0}"' -f $ExpectCommit.Replace('"', '""'))) }
    if ($PSBoundParameters.ContainsKey('PresentMonExe') -and $PresentMonExe) {
        $argv += @('-PresentMonExe', ('"{0}"' -f $PresentMonExe.Replace('"', '""')))
    }

    try {
        # WorkingDirectory is explicit because RunAs does NOT inherit it - an
        # elevated process starts in system32 and every relative path would resolve
        # somewhere else entirely.
        $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $argv -Verb RunAs `
                           -WorkingDirectory $HarnessDir -PassThru -ErrorAction Stop
    } catch {
        Bad 'elevation was declined or failed - nothing was started'
        Note "reason: $($_.Exception.Message)"
        Note 'run from an admin terminal, or pass -NoPresentMon to skip the capture'
        exit 1
    }

    Note ("elevated harness started as pid {0} in its own window" -f $p.Id)
    Note 'this shell is done; watch the new window, or read the transcript it writes'

    # A non-elevated parent can wait on a child it created, but querying an elevated
    # process's ExitCode can be refused - and an unhandled throw here would look like
    # the run failed when the run is what succeeded. So the wait is best-effort and
    # says which half it could not do.
    try {
        $p.WaitForExit()
        exit $p.ExitCode
    } catch {
        Warn "could not read the elevated run's exit code: $($_.Exception.Message)"
        Warn 'the run itself is unaffected - read the transcript for its result'
        exit 0
    }
}

Invoke-SelfElevate

# The elevated child owns a console this shell cannot see, so preserve its output
# unconditionally. Failing to start a transcript must not stop a run - the run is
# the point and the transcript is a convenience.
if ($Elevated) {
    $tr = Join-Path $LogDir ('harness-elevated-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    try { Start-Transcript -LiteralPath $tr -ErrorAction Stop | Out-Null; Ok "transcript $tr" }
    catch { Warn "no transcript: $($_.Exception.Message)" }
    Note ('parameters received: DryRun={0} CaptureArgs={1} Force={2} ExpectCommit=[{3}] PresentMonExe=[{4}]' `
          -f $DryRun, $CaptureArgs, $Force, $ExpectCommit, $PresentMonExe)
}

# ------------------------------------------------------------------- main ----

# Snapshot the log directory before anything starts, so the run's own output
# can be named afterwards rather than guessed at by timestamp.
$logsBefore = @(@(Get-ChildItem -LiteralPath $LogDir -Filter '*.ndjson' -File `
                                -ErrorAction SilentlyContinue) | ForEach-Object { $_.Name })

$info  = Invoke-PreFlight
$fatal = $script:Failures

if ($fatal -gt 0 -and -not $Force) {
    Head 'stopping'
    Bad "$fatal pre-flight check(s) failed - nothing was started"
    Note 'pass -Force to run anyway, or fix the mismatch'
    exit 1
}
if ($fatal -gt 0) { Warn "overriding $fatal failed check(s) because -Force was given" }

if ($DryRun) {
    Head 'dry run'
    Note "would start server : $ServerExe"
    Note "would start client : $ClientExe"
    Note ("        with args : " + (Get-ClientArgs -Backend $info.Backend -Token $info.Token))
    if (Get-SavedArgs) { Note 'these are captured launcher arguments, replayed' }
    else { Note 'these are read from GameStarter.cs - -CaptureArgs is optional' }
    Invoke-PostFlight -Before $logsBefore -NothingRan
    exit 0
}

$server = $null
try {
    $server = Start-SptServer
    Wait-ServerReady -Proc $server

    if ($CaptureArgs) {
        Head 'capture'
        Note 'starting the launcher - press Start in it as usual'
        [void] (Start-Process -FilePath $LauncherExe -WorkingDirectory $ServerDir -PassThru)
        $client = Wait-ForClient
        Save-ClientArgs -Proc $client
    }
    else {
        $client = Start-Client -Backend $info.Backend -Token $info.Token
    }

    Start-PresentMon -ClientPid $client.Id

    Head 'running'
    Say  '   waiting for the client to close. Closing the game ends the session.'
    $client.WaitForExit()
    Ok "client exited (code $($client.ExitCode))"
}
finally {
    # finally, so a Ctrl-C or a thrown error still stops the server. Leaving a
    # headless server running is the failure this whole script exists to avoid,
    # and an orphaned ETW session is the same shape - it survives the run and
    # blocks the next one.
    Stop-PresentMon
    Stop-SptServer -Proc $server
    Invoke-PostFlight -Before $logsBefore

    Head 'done'
    if ($script:Failures -gt 0) { Bad "$($script:Failures) problem(s) - read above" }
    else { Ok 'clean run' }
}
