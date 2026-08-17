#!/usr/bin/env python3
"""Bare-name collision check over Plugin.cs config keys.

WHY THIS EXISTS
---------------
ProtocolRunner.BuildEntryMap() keys every setting by its BARE NAME with no section, into an
OrdinalIgnoreCase dictionary, last-writer-wins. Two settings sharing a name are therefore resolved
SILENTLY and arbitrarily by a protocol file - the protocol refuses UNKNOWN keys loudly and resolves
AMBIGUOUS ones quietly, which is the worse pair of behaviours. `Enabled` is already such a pair
([1. Bot stand-by] and [3. Telemetry]) and a protocol arm must never pin it.

Adding a config key is exactly when a NEW instance of that defect gets introduced. So this runs on
every key addition.

WHY THREE ANCHORS AND NOT ONE
-----------------------------
Three seats ran this enumeration by hand on 2026-08-07 with three differently-shaped greps, and
every one of them was wrong in a way invisible from inside its own output:

    Alpha, Beta   `Config.Bind(` immediately followed by a string literal   -> 39, missed one
    Gamma         section-literal anchored                                  -> 40

The miss was `[0. Compatibility] Reclaim stand-by from QuestingBots`, which puts a COMMENT between
`Config.Bind(` and its section argument (Plugin.cs:130-133). A whitespace-only regex cannot span it,
and the scan returns a clean, plausible, wrong count with nothing saying so.

Gamma's stronger point: BuildEntryMap uses REFLECTION over real fields, so runtime is authoritative
and any source scan is a lower bound. This answers that without needing the game running, by making
the third anchor track the set reflection walks - `public static ConfigEntry<...>` fields on Plugin.

    THAT IS "TRACKS", NOT "IS", AND THE DIFFERENCE IS A THIRD PARTY'S BEHAVIOUR (Beta).
    BuildEntryMap calls typeof(Plugin).GetFields(Public | Static) WITHOUT DeclaredOnly, so it
    also returns public static fields INHERITED from BaseUnityPlugin and above. Anchor 3 scans
    declarations in Plugin.cs and cannot see those.

    Measured 2026-08-07 by reflecting the real assemblies, rather than asserted from memory:

        BepInEx.BaseUnityPlugin     public static fields  0
        UnityEngine.MonoBehaviour                         0
        UnityEngine.Behaviour                             0
        UnityEngine.Component                             0
        UnityEngine.Object                                0
        System.Object                                     0

    Measured twice, by two instruments over ONE set of bytes - which is worth exactly that much:

        Alpha   real CLR type loading, GetFields(Public|Static|DeclaredOnly) on each type in the
                chain - the same API BuildEntryMap calls. NOTE: plain reflection FAILS here
                (BaseUnityPlugin needs UnityEngine to resolve, and GetTypes throws
                ReflectionTypeLoadException); it needs an AppDomain.AssemblyResolve handler
                pointing at Managed/ and BepInEx/core before GetType will return the type.
        Delta   Mono.Cecil metadata read - no type loading, no dependency resolution, and it
                needs none of the above. Also surfaced BaseUnityPlugin's three PRIVATE INSTANCE
                property backing fields (<Info>, <Logger>, <Config>); Config is a ConfigFile,
                not a ConfigEntry, and none are public static.

    SHARED FAILURE MODE, stated because two agreeing methods over the same input is not two
    independent observations: both read the SAME FILES. If the running game ever loads its
    assemblies from anywhere other than the paths below, both measurements are of the wrong bytes
    and would agree while being wrong.

        F:/SPT/SPT4.0.13/BepInEx/core/BepInEx.dll
        F:/SPT/SPT4.0.13/EscapeFromTarkov_Data/Managed/UnityEngine.CoreModule.dll

    RE-CHECK AFTER ANY BepInEx OR UNITY UPGRADE. Delta's Cecil read is a five-second job against
    those two paths and is cheaper than reasoning about it again.

    So the two sets are equal TODAY - by BepInEx's and Unity's continued good behaviour, not by
    construction. A future BepInEx that adds a public static ConfigEntry anywhere up that chain
    would silently enter Framesaver's protocol key namespace and could collide with one of ours:
    the `Enabled` defect arriving from outside the repo, in an upgrade after which nobody would
    think to re-run a config scan.

    THE STRUCTURAL FIX IS BETA'S AND IS NOT IN THIS FILE: add BindingFlags.DeclaredOnly to
    BuildEntryMap. That makes the reflected set exactly the set visible in Plugin.cs, which makes
    these anchors equivalent by construction and makes external collision impossible rather than
    merely absent. It is a one-flag change to a method with no test coverage, so it wants doing
    deliberately rather than at the end of a long night.

    Gamma checked the neighbouring gap: BuildEntryMap casts to ConfigEntryBase while anchor 3
    greps ConfigEntry<...>. There are 0 fields declared as the base type today - and if one ever
    appears, anchors 1 and 2 still find its bind while anchor 3 does not, so this reports
    DISAGREEMENT rather than a quiet undercount. The blind spot is self-detecting.

    anchor 1   count of Config.Bind( call sites          (comment-stripped source)
    anchor 2   count of (section, key) literal pairs      recovered from those calls
    anchor 3   count of public static ConfigEntry<> field declarations

If all three agree, then every field BuildEntryMap can find is bound exactly once, and every bind
had two string literals to recover - which also rules out a key computed at runtime that a pair-scan
would silently skip. A DISAGREEMENT is the finding; the counts are not the point.

Out of scope by construction: a ConfigEntry declared on a class other than Plugin. BuildEntryMap
only reflects typeof(Plugin), so such a field is not in the map either.

Exit 0 clean, 1 on a collision or an anchor disagreement.
"""

import collections
import os
import re
import sys

BS = chr(92)


def strip_comments(src):
    """Remove C# comments, preserving string literals.

    Descriptions in Plugin.cs contain paths and '//' sequences, so a naive comment strip eats real
    key text. String literals are copied verbatim, backslash escapes honoured.
    """
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                if src[i] == BS:
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if src.startswith('//', i):
            while i < n and src[i] != chr(10):
                i += 1
            continue
        if src.startswith('/*', i):
            j = src.find('*/', i)
            i = (j + 2) if j >= 0 else n
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', 'Plugin.cs')
    path = os.path.normpath(path)

    if not os.path.isfile(path):
        print('REFUSED: no such file: ' + path)
        return 1

    with open(path, encoding='utf-8', errors='replace') as fh:
        clean = strip_comments(fh.read())

    call_sites = len(re.findall(r'Config\.Bind\s*(?:<[^>]*>)?\s*\(', clean))
    pairs = re.findall(r'Config\.Bind\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', clean)
    decls = re.findall(r'public\s+static\s+ConfigEntry<[^>]+>\s+(\w+)\s*;', clean)

    # A file with no binds at all means the anchors were pointed at the wrong thing. Refuse rather
    # than report "no collisions", which is what an empty set reads as.
    if call_sites == 0:
        print('REFUSED: no Config.Bind call sites in ' + path + ' - wrong file, or the anchors have')
        print('         gone stale against a rename. An empty scan is not a clean scan.')
        return 1

    counts = collections.Counter(k for _, k in pairs)
    dups = sorted(k for k, v in counts.items() if v > 1)
    agree = call_sites == len(pairs) == len(decls)

    print('  Config.Bind( call sites      : %d' % call_sites)
    print('  section+key pairs recovered  : %d' % len(pairs))
    print('  ConfigEntry<> field declares : %d' % len(decls))
    print('  ANCHORS AGREE                : %s' % agree)
    print('  distinct bare keys           : %d' % len(counts))
    print('')

    if not agree:
        print('ANCHOR DISAGREEMENT - the scan is unreliable and its collision list means nothing.')
        print('A bind whose section/key are not adjacent string literals, or a declared-but-unbound')
        print('field, will land here. Read the source before trusting any count above.')
        return 1

    for key in dups:
        sections = [s for s, k in pairs if k == key]
        print('COLLISION  "%s"  in  %s' % (key, ', '.join(sections)))
        print('           BuildEntryMap resolves this by bare name, last-writer-wins over a')
        print('           GetFields() order .NET does not guarantee. A protocol arm pinning it')
        print('           may address either one. Do not pin it; confirm the live config by hand.')

    if not dups:
        print('No bare-name collisions.')
        return 0

    # `Enabled` is a known, documented, pre-existing pair. It is reported every run rather than
    # allow-listed: an allow-list is how a second instance hides behind the first.
    print('')
    print('%d collision(s). `Enabled` is the known pre-existing pair (framesaver/shared/boot).' % len(dups))
    print('Deliberately NOT allow-listed - an allow-list is how the second instance hides.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
