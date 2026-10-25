using System.Globalization;
using System.Text;
using Voxta.Modules.Sims4.Bridge;
using Voxta.Modules.Sims4.Configuration;

namespace Voxta.Modules.Sims4.Household;

/// <summary>
/// Turns a household snapshot into the context the characters read. Written to be read by a model,
/// not a person: words over numbers ("very hungry" rather than "hunger 8"), the Sims in this chat in
/// full, everyone else in a line, and nothing that changes every few seconds unless it matters.
/// </summary>
public static class HouseholdContextBuilder
{
    public sealed record Options(string UserRole, string? CustomUserRole);

    /// <param name="participants">Sims played by characters in this chat, keyed by Sim id, with the character's name.</param>
    public static string Build(GameState? state, bool connected, IReadOnlyDictionary<string, string> participants, Options options)
    {
        var text = new StringBuilder();

        if (state is null)
        {
            text.AppendLine("[The Sims 4] The game is not running, so there is no news from the household. Stay in character as a member of your Sims household; don't invent specific current events.");
            AppendUserRole(text, null, options);
            return text.ToString().TrimEnd();
        }

        var world = state.World;
        var when = Join(", ", world?.Day, world?.Time, world?.Season);
        var where = string.IsNullOrWhiteSpace(world?.Lot) ? null : $"at {world!.Lot}";
        text.Append("[The Sims 4 — ");
        text.Append(connected ? "live from the game" : "last known, the game has closed");
        if (when.Length > 0) text.Append(", ").Append(when);
        if (where is not null) text.Append(", ").Append(where);
        text.AppendLine("]");

        if (state.Household is { } household)
        {
            text.Append("Household: ").Append(household.Name ?? "unnamed");
            if (household.Funds is { } funds) text.Append(" (§").Append(funds.ToString("N0", CultureInfo.InvariantCulture)).Append(')');
            text.AppendLine();
        }

        var inChat = state.Sims.Where(s => participants.ContainsKey(s.Id)).ToArray();
        var others = state.Sims.Where(s => !participants.ContainsKey(s.Id)).ToArray();

        foreach (var sim in inChat)
            AppendSimInDetail(text, sim, participants[sim.Id], state);

        if (others.Length > 0)
        {
            text.AppendLine("Also in the household:");
            foreach (var sim in others)
                text.Append("- ").AppendLine(SummaryLine(sim));
        }

        AppendUserRole(text, state, options);

        text.AppendLine("Stay true to your Sim: let their mood, needs and what they are doing shape how you talk, the way a person would mention being tired or busy. Don't recite these notes or quote numbers.");
        return text.ToString().TrimEnd();
    }

    private static void AppendSimInDetail(StringBuilder text, SimInfo sim, string characterName, GameState state)
    {
        text.Append("* ").Append(sim.FullName);
        if (!string.Equals(SimMatcher.Normalize(characterName), SimMatcher.Normalize(sim.FullName), StringComparison.Ordinal))
            text.Append(" (played by ").Append(characterName).Append(')');
        text.Append(" — ").Append(Describe(sim.Age, sim.Gender));
        if (sim.IsActive) text.Append(", the Sim the player is controlling right now");
        text.AppendLine();

        var mood = MoodPhrase(sim);
        if (mood is not null) text.Append("  Mood: ").AppendLine(mood);

        if (!string.IsNullOrWhiteSpace(sim.Activity))
            text.Append("  Doing: ").AppendLine(sim.Activity);
        else if (!sim.OnLot)
            text.AppendLine("  Away from the home lot right now.");

        var needs = NeedsPhrase(sim);
        if (needs is not null) text.Append("  Needs: ").AppendLine(needs);

        if (sim.Traits is { Length: > 0 })
            text.Append("  Traits: ").AppendLine(string.Join(", ", sim.Traits));

        if (sim.Career is { Name: not null } career)
            text.Append("  Career: ").Append(career.Name).AppendLine(career.Level is { } level ? $", level {level}" : "");

        var relationships = (sim.Relationships ?? [])
            .Select(r => RelationshipPhrase(r, state))
            .Where(r => r is not null)
            .ToArray();
        if (relationships.Length > 0)
            text.Append("  Relationships: ").AppendLine(string.Join("; ", relationships));
    }

    private static string SummaryLine(SimInfo sim)
    {
        var parts = new List<string> { $"{sim.FullName} ({Describe(sim.Age, sim.Gender)})" };
        var mood = MoodPhrase(sim);
        if (mood is not null) parts.Add(mood.ToLowerInvariant());
        if (!string.IsNullOrWhiteSpace(sim.Activity)) parts.Add($"doing: {sim.Activity}");
        else if (!sim.OnLot) parts.Add("away");
        if (sim.IsActive) parts.Add("the Sim the player controls");
        return string.Join(", ", parts);
    }

    private static void AppendUserRole(StringBuilder text, GameState? state, Options options)
    {
        switch (options.UserRole)
        {
            case ModuleConfigurationProvider.UserIsActiveSim:
                var active = state?.Sims.FirstOrDefault(s => s.IsActive);
                text.AppendLine(active is not null
                    ? $"{{{{ user }}}} is {active.FullName}, a member of this household."
                    : "{{ user }} is a member of this household.");
                break;
            case ModuleConfigurationProvider.UserIsCustom when !string.IsNullOrWhiteSpace(options.CustomUserRole):
                text.AppendLine(options.CustomUserRole!.Trim());
                break;
            default:
                text.AppendLine("{{ user }} is the Watcher: the unseen player who guides this household's lives. The Sims can talk to them directly.");
                break;
        }
    }

    private static string Describe(string? age, string? gender)
    {
        var a = string.IsNullOrWhiteSpace(age) ? null : age.ToLowerInvariant().Replace("youngadult", "young adult");
        var g = string.IsNullOrWhiteSpace(gender) ? null : gender.ToLowerInvariant();
        return Join(" ", a, g) is { Length: > 0 } s ? s : "Sim";
    }

    private static string? MoodPhrase(SimInfo sim)
    {
        if (string.IsNullOrWhiteSpace(sim.Mood)) return null;
        var intensity = sim.MoodIntensity switch
        {
            >= 3 => "very ",
            2 => "",
            1 => "slightly ",
            _ => "",
        };
        return sim.Mood.Equals("Fine", StringComparison.OrdinalIgnoreCase)
            ? "fine"
            : $"{intensity}{sim.Mood.ToLowerInvariant()}";
    }

    /// <summary>Only the needs worth mentioning. A Sim whose needs are all fine gets "all fine".</summary>
    public static string? NeedsPhrase(SimInfo sim)
    {
        if (sim.Needs is not { Count: > 0 } needs) return null;
        var notable = new List<string>();
        foreach (var (need, value) in needs.OrderBy(n => n.Value))
        {
            var phrase = NeedPhrase(need, value);
            if (phrase is not null) notable.Add(phrase);
        }

        return notable.Count == 0 ? "all fine" : string.Join(", ", notable);
    }

    private static string? NeedPhrase(string need, double value)
    {
        var level = value switch
        {
            < 10 => 3,
            < 25 => 2,
            < 40 => 1,
            _ => 0,
        };
        if (level == 0) return null;
        var how = level switch { 3 => "desperately", 2 => "very", _ => "a bit" };
        return need.ToLowerInvariant() switch
        {
            "hunger" => $"{how} hungry",
            "energy" => $"{how} tired",
            "bladder" => level == 3 ? "desperately needs the bathroom" : $"{how} needs the bathroom",
            "hygiene" => $"{how} in need of a shower",
            "social" => $"{how} lonely",
            "fun" => $"{how} bored",
            _ => $"{need.ToLowerInvariant()} low",
        };
    }

    private static string? RelationshipPhrase(RelationshipInfo relationship, GameState state)
    {
        var name = string.IsNullOrWhiteSpace(relationship.Name)
            ? state.Sims.FirstOrDefault(s => s.Id == relationship.Id)?.FullName
            : relationship.Name;
        if (string.IsNullOrWhiteSpace(name)) return null;

        var parts = new List<string>();
        if (relationship.Bits is { Length: > 0 }) parts.Add(string.Join(", ", relationship.Bits.Take(3)).ToLowerInvariant());
        if (relationship.Friendship is { } friendship) parts.Add(FeelingPhrase(friendship, "friends", "dislike each other"));
        if (relationship.Romance is { } romance and >= 15) parts.Add(romance >= 60 ? "deeply in love" : "romantic");
        parts.RemoveAll(string.IsNullOrEmpty);
        return parts.Count == 0 ? name : $"{name} ({string.Join(", ", parts)})";
    }

    private static string FeelingPhrase(double score, string positive, string negative) => score switch
    {
        >= 75 => $"close {positive}",
        >= 30 => positive,
        > -30 => "",
        _ => negative,
    };

    private static string Join(string separator, params string?[] parts) =>
        string.Join(separator, parts.Where(p => !string.IsNullOrWhiteSpace(p)));
}
