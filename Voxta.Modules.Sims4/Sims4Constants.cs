using Voxta.Abstractions.Registration;

namespace Voxta.Modules.Sims4;

public static class Sims4Constants
{
    /// <summary>What user settings are saved against. Never change it once published.</summary>
    public const string ServiceName = "Sims4";

    /// <summary>The key a character or chat turns on to get the household in its chat.</summary>
    public const string AugmentationKey = "sims4";

    /// <summary>Everything this module puts in a chat's context is replaced together, under this key.</summary>
    public const string ContextKey = ServiceName;

    /// <summary>Bumped when the game ↔ Voxta wire format changes incompatibly. The script mod sends its own.</summary>
    public const int ProtocolVersion = 1;

    public static readonly AugmentationKeyDescriptor[] Augmentations =
    [
        new(
            AugmentationKey,
            "The Sims 4",
            "Gives the character its Sim's live state from a running game (mood, needs, traits, career, what they are doing, relationships) and shows its replies in the game."
        ),
    ];
}
