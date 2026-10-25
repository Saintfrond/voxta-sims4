using System.Globalization;
using System.Text;
using Voxta.Modules.Sims4.Bridge;

namespace Voxta.Modules.Sims4.Household;

/// <summary>
/// Finds the Sim a Voxta character stands for. In order: an explicit alias from the settings, the
/// full name, then a first name that only one household member has. Accents, case and punctuation
/// are ignored, so "Ünal Öztürk" in Voxta finds "Unal Ozturk" in the game.
/// </summary>
public sealed class SimMatcher
{
    private readonly Dictionary<string, string> _aliases;

    public SimMatcher(string? aliasLines)
    {
        _aliases = ParseAliases(aliasLines);
    }

    public SimInfo? Match(string characterName, IReadOnlyList<SimInfo> sims)
    {
        if (sims.Count == 0 || string.IsNullOrWhiteSpace(characterName)) return null;

        var key = Normalize(characterName);
        var target = _aliases.TryGetValue(key, out var alias) ? alias : key;

        var byFullName = sims.FirstOrDefault(s => Normalize(s.FullName) == target);
        if (byFullName is not null) return byFullName;

        var byFirstName = sims.Where(s => Normalize(s.FirstName) == target).ToArray();
        if (byFirstName.Length == 1) return byFirstName[0];

        // "Bella" in Voxta, "Bella Goth" in game is handled above; this catches "Bella G." or a
        // character called "Bella Goth (Sims)".
        var byPrefix = sims.Where(s => target.StartsWith(Normalize(s.FullName) + " ", StringComparison.Ordinal)
                                       || (Normalize(s.FirstName).Length > 0 && target.StartsWith(Normalize(s.FirstName) + " ", StringComparison.Ordinal)))
            .ToArray();
        return byPrefix.Length == 1 ? byPrefix[0] : null;
    }

    private static Dictionary<string, string> ParseAliases(string? lines)
    {
        var result = new Dictionary<string, string>();
        if (string.IsNullOrWhiteSpace(lines)) return result;

        foreach (var raw in lines.Split('\n'))
        {
            var separator = raw.IndexOf('=');
            if (separator <= 0) continue;
            var character = Normalize(raw[..separator]);
            var sim = Normalize(raw[(separator + 1)..]);
            if (character.Length > 0 && sim.Length > 0)
                result[character] = sim;
        }

        return result;
    }

    public static string Normalize(string value)
    {
        var decomposed = value.Normalize(NormalizationForm.FormD);
        var builder = new StringBuilder(decomposed.Length);
        var lastWasSpace = true;
        foreach (var c in decomposed)
        {
            var category = CharUnicodeInfo.GetUnicodeCategory(c);
            if (category == UnicodeCategory.NonSpacingMark) continue;
            if (char.IsLetterOrDigit(c))
            {
                builder.Append(char.ToLowerInvariant(c));
                lastWasSpace = false;
            }
            else if (!lastWasSpace)
            {
                builder.Append(' ');
                lastWasSpace = true;
            }
        }

        return builder.ToString().Trim();
    }
}
