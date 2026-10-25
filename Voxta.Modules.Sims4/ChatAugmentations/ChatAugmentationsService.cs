using System.Globalization;
using Microsoft.Extensions.Logging;
using Voxta.Abstractions.Registration;
using Voxta.Abstractions.Services;
using Voxta.Abstractions.Services.ChatAugmentations;
using Voxta.Modules.Sims4.Bridge;
using Voxta.Modules.Sims4.Configuration;

namespace Voxta.Modules.Sims4.ChatAugmentations;

/// <summary>
/// Offers the "sims4" augmentation to chats. Planning is cheap and also starts the game listener, so
/// the game can connect as soon as anyone opens a chat that could use it; the real work waits in
/// <c>ActivateAsync</c>, when a chat that turned the key on actually starts.
/// </summary>
public class ChatAugmentationsService(
    ILogger<ChatAugmentationsService> logger,
    ILoggerFactory loggerFactory,
    SimsBridge bridge
) : ServiceBase(logger), IChatAugmentationsService
{
    private readonly SimsBridge _bridge = AttachLogging(bridge, loggerFactory);

    private static SimsBridge AttachLogging(SimsBridge bridge, ILoggerFactory loggerFactory)
    {
        bridge.AttachLogger(loggerFactory);
        return bridge;
    }

    public Task<AugmentationPlanItem[]> PlanAsync(
        IChatAugmentationPlanContext context,
        CancellationToken cancellationToken
    )
    {
        var settings = ReadSettings();
        _bridge.EnsureListening(settings.Port, settings.AllowRemoteGame);

        var augmentation = Sims4Constants.Augmentations.Get(Sims4Constants.AugmentationKey);
        return Task.FromResult<AugmentationPlanItem[]>([
            new AugmentationPlanItem
            {
                Key = augmentation.Key,
                Label = augmentation.Label,
                Description = augmentation.Description,
                // Only where a character or chat asked for it: a household has no business in every chat.
                Activation = AugmentationActivation.OptIn,
                Suggested = false,
                IncludeInCatchAll = false,
                ActivateAsync = async (session, ct) =>
                {
                    var instance = new Sims4ChatAugmentationInstance(
                        session,
                        _bridge,
                        settings,
                        loggerFactory.CreateLogger<Sims4ChatAugmentationInstance>()
                    );
                    await instance.StartAsync(ct);
                    return instance;
                },
            },
        ]);
    }

    private Sims4Settings ReadSettings()
    {
        var portText = ModuleConfiguration.GetRequired(ModuleConfigurationProvider.Port);
        if (!int.TryParse(portText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var port) || port is < 1 or > 65535)
        {
            logger.LogWarning("'{Port}' is not a valid port for the Sims 4 bridge, using {Default}", portText, SimsBridge.DefaultPort);
            port = SimsBridge.DefaultPort;
        }

        var cooldownText = ModuleConfiguration.GetRequired(ModuleConfigurationProvider.ReactCooldownSeconds);
        if (!int.TryParse(cooldownText, NumberStyles.Integer, CultureInfo.InvariantCulture, out var cooldown) || cooldown < 0)
            cooldown = 90;

        return new Sims4Settings(
            Port: port,
            AllowRemoteGame: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.AllowRemoteGame),
            UserRole: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.UserRole),
            CustomUserRole: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.CustomUserRole),
            NameAliases: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.NameAliases),
            ShowRepliesInGame: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.ShowRepliesInGame),
            ShowUserMessagesInGame: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.ShowUserMessagesInGame),
            CameraFocus: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.CameraFocus),
            GameEvents: ModuleConfiguration.GetRequired(ModuleConfigurationProvider.GameEvents),
            ReactCooldown: TimeSpan.FromSeconds(cooldown)
        );
    }
}

/// <summary>The module settings as one chat sees them, read once when it starts.</summary>
public sealed record Sims4Settings(
    int Port,
    bool AllowRemoteGame,
    string UserRole,
    string? CustomUserRole,
    string? NameAliases,
    bool ShowRepliesInGame,
    bool ShowUserMessagesInGame,
    string CameraFocus,
    string GameEvents,
    TimeSpan ReactCooldown
);
