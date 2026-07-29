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

.EXAMPLE
  .\run-raid.ps1 -DryRun
  .\run-raid.ps1 -CaptureArgs
  .\run-raid.ps1
#>
[CmdletBinding()]
param(
    [switch] $DryRun,
    [switch] $CaptureArgs,
    [string] $ExpectCommit,
    [switch] $Force
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

$script:Failures = 0

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
    # Refuse rather than adding a second server. Two servers on one port is a
    # confusing state that looks like a working one.
    $busy = @()
    foreach ($n in 'SPT.Server', 'EscapeFromTarkov', 'SPT.Launcher') {
        $p = Get-Process -Name $n -ErrorAction SilentlyContinue
        if ($p) { $busy += "$n (pid $($p.Id -join ','))" }
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

    $backend = Get-BackendUrl
    Ok "backend $backend"
    try { $token = Get-Token; Ok "profile token $token" }
    catch { Bad $_.Exception.Message; $token = $null }

    [pscustomobject]@{ Backend = $backend; Token = $token }
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

    Head 'running'
    Say  '   waiting for the client to close. Closing the game ends the session.'
    $client.WaitForExit()
    Ok "client exited (code $($client.ExitCode))"
}
finally {
    # finally, so a Ctrl-C or a thrown error still stops the server. Leaving a
    # headless server running is the failure this whole script exists to avoid.
    Stop-SptServer -Proc $server
    Invoke-PostFlight -Before $logsBefore

    Head 'done'
    if ($script:Failures -gt 0) { Bad "$($script:Failures) problem(s) - read above" }
    else { Ok 'clean run' }
}
