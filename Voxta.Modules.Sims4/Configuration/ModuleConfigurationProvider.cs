using Voxta.Abstractions.Registration;
using Voxta.Abstractions.Security;
using Voxta.Model.Shared.Forms;

namespace Voxta.Modules.Sims4.Configuration;

public class ModuleConfigurationProvider : ModuleConfigurationProviderBase, IModuleConfigurationProvider
{
    public static string[] FieldsRequiringReload => [];

    public static readonly FormTextField Port = new()
    {
        Name = "Port",
        Label = "Game connection port",
        Text = "The local TCP port the Sims 4 script mod connects to. Must match `port` in the mod's voxta_bridge.cfg. Default 5385.",
        DefaultValue = "5385",
    };

    public static readonly FormBooleanField AllowRemoteGame = new()
    {
        Name = "AllowRemoteGame",
        Label = "Allow the game on another PC",
        Text = "Off: only a game on this computer can connect (recommended). On: listens on every network interface, for a game running on a different machine in your home network.",
        DefaultValue = false,
    };

    public const string UserIsWatcher = "watcher";
    public const string UserIsActiveSim = "active_sim";
    public const string UserIsCustom = "custom";

    public static readonly FormChoicesField UserRole = new()
    {
        Name = "UserRole",
        Label = "Who are you to the Sims?",
        Text = "How the household sees you, the person chatting.",
        DefaultValue = UserIsWatcher,
        Choices =
        [
            new() { Value = UserIsWatcher, Label = "The Watcher (the player who controls their lives)" },
            new() { Value = UserIsActiveSim, Label = "The Sim I'm currently controlling" },
            new() { Value = UserIsCustom, Label = "Custom (write it below)" },
        ],
    };

    public static readonly FormMultilineField CustomUserRole = new()
    {
        Name = "CustomUserRole",
        Label = "Custom description of you",
        Text = "Used when 'Who are you to the Sims?' is Custom. {{ user }} is your name.",
        Required = false,
        DefaultValue = "",
        Rows = 3,
        Placeholder = "{{ user }} is a family friend who calls the household on the phone.",
    };

    public static readonly FormMultilineField NameAliases = new()
    {
        Name = "NameAliases",
        Label = "Character → Sim names",
        Text = "Characters are matched to Sims by name automatically (full name, then a unique first name). Add a line `Character Name = Sim First Last` for any that don't match.",
        Required = false,
        DefaultValue = "",
        Rows = 4,
        Placeholder = "Mom = Bella Goth",
    };

    public static readonly FormBooleanField ShowRepliesInGame = new()
    {
        Name = "ShowRepliesInGame",
        Label = "Show replies in the game",
        Text = "Each reply from a character appears in the game as a notification with their Sim's portrait.",
        DefaultValue = true,
    };

    public static readonly FormBooleanField ShowUserMessagesInGame = new()
    {
        Name = "ShowUserMessagesInGame",
        Label = "Show my messages in the game",
        Text = "Your own messages also appear in the game, so the notification feed reads as a conversation.",
        DefaultValue = false,
    };

    public const string CameraOff = "off";
    public const string CameraPan = "pan";
    public const string CameraFollow = "follow";

    public static readonly FormChoicesField CameraFocus = new()
    {
        Name = "CameraFocus",
        Label = "Camera on the speaker",
        Text = "Move the game camera to the Sim whose character is speaking (only Sims on the current lot).",
        DefaultValue = CameraPan,
        Choices =
        [
            new() { Value = CameraOff, Label = "Off" },
            new() { Value = CameraPan, Label = "Pan to the speaker" },
            new() { Value = CameraFollow, Label = "Follow the speaker until someone else talks" },
        ],
    };

    public const string EventsOff = "off";
    public const string EventsSilent = "silent";
    public const string EventsReact = "react";

    public static readonly FormChoicesField GameEvents = new()
    {
        Name = "GameEvents",
        Label = "Game events",
        Text = "What happens when something notable happens to a Sim in the chat (a strong mood, a critical need, a promotion, a birthday...).",
        DefaultValue = EventsSilent,
        Choices =
        [
            new() { Value = EventsOff, Label = "Ignore them" },
            new() { Value = EventsSilent, Label = "Tell the character quietly (it may bring it up next reply)" },
            new() { Value = EventsReact, Label = "Let the character react right away" },
        ],
    };

    public static readonly FormTextField ReactCooldownSeconds = new()
    {
        Name = "ReactCooldownSeconds",
        Label = "Seconds between reactions",
        Text = "With 'react right away', a character speaks up on its own at most once per this many seconds.",
        DefaultValue = "90",
    };

    public Task<FormField[]> GetModuleConfigurationFieldsAsync(
        IAuthenticationContext auth,
        ISettingsSource settings,
        CancellationToken cancellationToken
    )
    {
        return Task.FromResult(FormBuilder.Build(
            FormTitleField.Create("Game connection"),
            Port,
            AllowRemoteGame,
            FormTitleField.Create("Household"),
            UserRole,
            CustomUserRole,
            NameAliases,
            FormTitleField.Create("In the game"),
            ShowRepliesInGame,
            ShowUserMessagesInGame,
            CameraFocus,
            GameEvents,
            ReactCooldownSeconds
        ));
    }
}
