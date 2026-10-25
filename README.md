# Voxta × The Sims 4

Chat with the members of your Sims 4 household through [Voxta](https://voxta.ai). Each Sim gets a
Voxta character that knows, live from your running game, how that Sim is feeling, what they need,
what they are doing, their traits, career and relationships. What they say to you pops up in the
game as a notification with their portrait.

> **Status: 0.1, experimental.** Built against Voxta 1.13 (alpha). The Voxta module compiles in CI
> and the game mod passes its tests against a simulated game, but the mod has not had much play
> time in the real game yet. Please report what breaks.

```
 The Sims 4  ──  voxta_bridge.ts4script            Voxta Server  ──  "The Sims 4" module
 ┌──────────────────────────────┐   localhost TCP    ┌──────────────────────────────────────┐
 │ reads the active household   │   JSON lines       │ waits for the game on 127.0.0.1:5385 │
 │ every few seconds            │ ───────────────►   │ "sims4" augmentation:                │
 │ notices events (moods,       │   state + events   │  • matches characters to Sims        │
 │ needs, promotions, ...)      │                    │  • keeps the chat context up to date │
 │ shows replies as             │ ◄───────────────   │  • passes game events to characters  │
 │ in-game notifications        │   notifications    │  • sends replies back to the game    │
 └──────────────────────────────┘                    └──────────────────────────────────────┘
```

## Setup

You need two pieces: the Voxta module and the game mod. Both come from this repository's
[Releases](https://github.com/Saintfrond/voxta-sims4/releases).

### 1. The Voxta module

In Voxta Server (1.13 or newer): **Add Modules → Module Registries**, add `Saintfrond/voxta-sims4`,
then install **The Sims 4** from the list and add it.

The defaults work when the game and Voxta run on the same PC. Settings, under the module's
**Configure** page:

| Setting | What it does |
| --- | --- |
| Game connection port | Port the game mod connects to (default 5385). Must match `voxta_bridge.cfg`. |
| Allow the game on another PC | Listen on the network instead of only this computer. |
| Who are you to the Sims? | The Watcher (the player), the Sim you're controlling, or your own description. |
| Character → Sim names | `Character Name = Sim First Last` lines, for characters whose names don't match a Sim. |
| Show replies in the game | Character replies appear as in-game notifications. |
| Show my messages in the game | Your messages appear too. |
| Camera on the speaker | Off, pan to the Sim who is speaking, or follow them until someone else talks. |
| Game events | Ignore events, tell characters quietly, or let them react right away. |
| Seconds between reactions | Limits how often a character speaks up on its own. |

### 2. The game mod

1. Download `voxta_bridge-<version>.zip` from the release and unzip it into
   `Documents\Electronic Arts\The Sims 4\Mods\` so you get `Mods\Voxta\voxta_bridge.ts4script`.
2. In the game: **Options → Game Options → Other**, tick **Enable Custom Content and Mods** and
   **Script Mods Allowed**, then restart the game.
3. Load your household. The mod connects to Voxta on its own and retries until Voxta is up.

Check it from the cheat console (Ctrl+Shift+C): `voxta.status`.

### 3. Characters

Make one Voxta character per Sim you want to talk to, named like the Sim (`Bella Goth`, or just
`Bella` if no one else in the household is called Bella), and turn on the **The Sims 4**
augmentation (`sims4`) for it. Write the character's personality as you see that Sim; the module
adds the live state on top. A group chat with several of them is a family conversation.

Tip: in the character's description, say how they know they are a Sim (or don't). The default
"Watcher" setting lets them talk to you as the player who guides their lives.

## What the characters know

Refreshed every couple of seconds while you play, and only sent to the chat when something
changes in a way they'd notice:

- day, time, season and lot; household name and funds
- for each Sim in the chat: age, mood and how strong it is, needs that are low, what they're doing
  right now (or that they're away), personality traits, career and level, relationships with the
  rest of the household
- a line about everyone else in the household

Events a character hears about (depending on the **Game events** setting): a strong new mood, a
need hitting critical, a promotion or demotion, ageing up, someone joining or leaving the
household, a new marriage, engagement, best friendship and the like.

## Troubleshooting

- **`voxta.status` says not connected:** is Voxta Server running with the module added, and is
  something else using port 5385? Both sides log: Voxta's server log, and `voxta_bridge.log` next
  to the mod.
- **The character doesn't know their Sim:** the Voxta log says which character didn't match and
  lists the household. Add a `Character → Sim names` line.
- **Nothing happens in the game at all:** script mods are off, or the `.ts4script` is more than one
  folder deep inside `Mods`. `voxta.test` should show a notification.
- **After a game patch:** check `voxta_bridge.log` for errors. Each value is read separately, so a
  patch usually costs one detail (say, relationships) rather than the whole mod.

## Development

```
Voxta.Modules.Sims4/     the Voxta module (C#, .NET 10, Voxta.Sdk.Modules 1.13)
  Bridge/                TCP listener and the wire format
  Household/             character ↔ Sim matching, the context the characters read
  ChatAugmentations/     the "sims4" augmentation
sims4-mod/               the game mod (Python 3.7)
  src/voxta_bridge/      connection (background thread), snapshot, events, notifications
  tests/                 unit tests, and an end-to-end test against a fake game and fake Voxta
docs/PROTOCOL.md         the messages between the two
```

**Voxta module:** `dotnet build`, then in Voxta **Add Modules → Add Custom Module** and point it
at `Voxta.Modules.Sims4`. Change, build, **Apply**. Commit `packages.lock.json` with package changes.

**Game mod:** `python -m pytest sims4-mod/tests` (any Python 3.7+). Release builds need Python 3.7
because the game only loads `.pyc` files from its own version; CI does that. For a quick local try
on another Python, `python sims4-mod/build.py --source` makes a mod from the sources.

**Releasing:** set the same version in `Voxta.Modules.Sims4/module.json` and `MOD_VERSION` in
`sims4-mod/src/voxta_bridge/__init__.py` (CI checks they match) and commit. Then either click
**Actions → publish release → Run workflow**, or `git tag v0.1.0 && git push --tags`. The release
gets the module zip Voxta installs and the game mod zip. A version like `0.2.0-beta.1` makes a
pre-release.

The module's release pipeline is Voxta's own ([voxta-module-template](https://github.com/voxta-ai/voxta-module-template)):
see there for Voxta's trusted-repository listing and verifying releases.

## License

MIT, see [LICENSE](LICENSE).

Not affiliated with or endorsed by Electronic Arts or Maxis. The Sims is a trademark of
Electronic Arts Inc.
