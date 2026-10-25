using System.Text.Json;
using System.Text.Json.Serialization;

namespace Voxta.Modules.Sims4.Bridge;

// The wire format between the Sims 4 script mod and this module: one JSON object per line, UTF-8,
// every object has a "type". Keys are snake_case on the wire. docs/PROTOCOL.md describes it for the
// Python side; keep the two in step.

public static class BridgeJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        // A Sim's needs arrive as 42.5 and sometimes as "42.5" from older Python numbers; accept both.
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
        PropertyNameCaseInsensitive = true,
    };
}

// ---- Game → Voxta ----

public sealed record GameHello
{
    public int Protocol { get; init; }
    public string? ModVersion { get; init; }
}

public sealed record GameState
{
    public HouseholdInfo? Household { get; init; }
    public WorldInfo? World { get; init; }
    public string? ActiveSimId { get; init; }
    public SimInfo[] Sims { get; init; } = [];
}

public sealed record HouseholdInfo
{
    public string? Name { get; init; }
    public long? Funds { get; init; }
}

public sealed record WorldInfo
{
    /// <summary>e.g. "Tuesday"</summary>
    public string? Day { get; init; }

    /// <summary>24h, "14:05"</summary>
    public string? Time { get; init; }

    public string? Season { get; init; }
    public string? Lot { get; init; }
    public bool? Paused { get; init; }
}

public sealed record SimInfo
{
    public required string Id { get; init; }
    public string FirstName { get; init; } = "";
    public string LastName { get; init; } = "";
    public string? Age { get; init; }
    public string? Gender { get; init; }
    public bool IsActive { get; init; }

    /// <summary>On the lot the player is looking at (instanced), rather than away.</summary>
    public bool OnLot { get; init; }

    public string? Mood { get; init; }

    /// <summary>0 none, 1 mild, 2 strong, 3 very strong.</summary>
    public int? MoodIntensity { get; init; }

    /// <summary>Need name → 0..100, where 0 is empty (starving, exhausted) and 100 is full.</summary>
    public Dictionary<string, double>? Needs { get; init; }

    public string[] Traits { get; init; } = [];
    public CareerInfo? Career { get; init; }

    /// <summary>What the Sim is doing right now, e.g. "Cook", "Sleep", "Chat". Null when idle or away.</summary>
    public string? Activity { get; init; }

    public RelationshipInfo[] Relationships { get; init; } = [];

    [JsonIgnore]
    public string FullName => string.IsNullOrWhiteSpace(LastName) ? FirstName : $"{FirstName} {LastName}";
}

public sealed record CareerInfo
{
    public string? Name { get; init; }
    public int? Level { get; init; }
}

public sealed record RelationshipInfo
{
    public required string Id { get; init; }
    public string Name { get; init; } = "";

    /// <summary>-100..100</summary>
    public double? Friendship { get; init; }

    /// <summary>-100..100</summary>
    public double? Romance { get; init; }

    /// <summary>Readable relationship bits, e.g. "Spouse", "Parent", "Best Friend".</summary>
    public string[] Bits { get; init; } = [];
}

public sealed record GameEvent
{
    public string? SimId { get; init; }
    public string? SimName { get; init; }

    /// <summary>mood_changed, need_critical, aged_up, career_changed, joined_household, left_household, ...</summary>
    public string Kind { get; init; } = "";

    /// <summary>Already worded for a reader, e.g. "Bella Goth is now Sad (was Happy)."</summary>
    public string Text { get; init; } = "";

    /// <summary>The mod's own estimate: 0 trivia, 1 notable, 2 important.</summary>
    public int Importance { get; init; }
}

// ---- Voxta → Game ----

public sealed record ServerHello
{
    public string Type => "hello";
    public int Protocol => Sims4Constants.ProtocolVersion;
    public string Server => "Voxta.Modules.Sims4";
    public string? Version { get; init; }
}

public sealed record NotifyCommand
{
    public string Type => "notify";

    /// <summary>The Sim whose portrait is shown; null for a plain notification.</summary>
    public string? SimId { get; init; }

    public required string Title { get; init; }
    public required string Text { get; init; }
}

public sealed record FocusCommand
{
    public string Type => "focus";

    public required string SimId { get; init; }

    /// <summary>Keep following the Sim (until the player moves the camera), rather than only panning to them.</summary>
    public bool Follow { get; init; }
}

public sealed record RequestStateCommand
{
    public string Type => "request_state";
}
