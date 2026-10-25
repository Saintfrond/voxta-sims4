# Game ↔ Voxta protocol (version 1)

TCP, the Voxta module listens (default `127.0.0.1:5385`), the game mod connects and keeps retrying.
One JSON object per line, UTF-8, `\n` terminated. Every object has a `type`. Keys are snake_case.
Unknown types and unknown keys are ignored by both sides, so either side can add fields without
breaking the other. Bump the protocol number only for incompatible changes.

C# side: `Voxta.Modules.Sims4/Bridge/Messages.cs`. Python side: `sims4-mod/src/voxta_bridge/`.
`sims4-mod/tests/test_end_to_end.py` checks that every key the mod sends exists on the C# records.

## Game → Voxta

### `hello` (first message on every connection)

```json
{"type": "hello", "protocol": 1, "mod_version": "0.1.0"}
```

### `state` (on connect, then whenever it changes; checked every `state_interval` seconds)

```json
{
  "type": "state",
  "household": {"name": "Goth", "funds": 34500},
  "world": {"day": "Tuesday", "time": "14:05", "season": "Summer", "lot": "Goth Manor", "paused": false},
  "active_sim_id": "101",
  "sims": [
    {
      "id": "101", "first_name": "Bella", "last_name": "Goth",
      "age": "Adult", "gender": "Female", "is_active": true, "on_lot": true,
      "mood": "Happy", "mood_intensity": 2,
      "needs": {"hunger": 42.5, "energy": 80, "bladder": 66, "hygiene": 90, "social": 30, "fun": 55},
      "traits": ["Romantic", "Snob"],
      "career": {"name": "Business", "level": 4},
      "activity": "Stove Cook Dinner",
      "relationships": [
        {"id": "102", "name": "Mortimer Goth", "friendship": 80, "romance": 90, "bits": ["Married"]}
      ]
    }
  ]
}
```

- Sim ids are strings (they are 64-bit in the game).
- `needs`: 0 = empty (starving, exhausted), 100 = full. Missing for Sims without these motives.
- `mood_intensity`: 0–3. `friendship` / `romance`: −100…100.
- Any field the mod failed to read is left out; the receiver must not assume a field is present.
- Names come from game tuning (not translated), e.g. traits and careers are English words.

### `event` (when the mod notices a change between two snapshots)

```json
{"type": "event", "sim_id": "101", "sim_name": "Bella Goth", "kind": "mood_changed",
 "text": "Bella Goth is now very angry (was happy).", "importance": 1}
```

`kind`: `mood_changed`, `need_critical`, `aged_up`, `career_changed`, `joined_household`,
`left_household`, `relationship_changed`, `active_sim_changed`.
`importance`: 0 trivia, 1 notable (a character may react), 2 news for the whole household.
`text` is already worded for the characters to read.

### `bye`

Sent when the mod drops the connection on purpose (`voxta.reconnect`).

## Voxta → Game

### `hello`

```json
{"type": "hello", "protocol": 1, "server": "Voxta.Modules.Sims4", "version": "0.1.0"}
```

### `notify` (show a chat line in the game)

```json
{"type": "notify", "sim_id": "101", "title": "Bella Goth", "text": "Dinner's almost ready, dear."}
```

`sim_id` is optional; with it, the notification shows that Sim's portrait.

### `focus` (point the game camera at a Sim)

```json
{"type": "focus", "sim_id": "101", "follow": false}
```

Only acts for a Sim on the current lot. `follow: true` keeps the camera on them until the player
moves it; otherwise it pans once.

### `request_state`

Asks the game to send a full `state` now (a chat just started and wants fresh data).
