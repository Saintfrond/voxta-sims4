using Microsoft.Extensions.DependencyInjection;
using Voxta.Abstractions.Modules;
using Voxta.Abstractions.Registration;
using Voxta.Modules.Sims4.Bridge;
using Voxta.Modules.Sims4.ChatAugmentations;
using Voxta.Modules.Sims4.Configuration;

namespace Voxta.Modules.Sims4;

public class VoxtaModule : IVoxtaModule
{
    public void Configure(IVoxtaModuleBuilder builder)
    {
        builder.Register(new()
        {
            ServiceName = Sims4Constants.ServiceName,
            Label = "The Sims 4",
            Version = ModuleInfo.Version,
            Flags = [ModuleFlag.Experimental, ModuleFlag.SupportsExplicitContent],
            Supports = new()
            {
                ChatAugmentations = new(ServiceDefinitionCategoryScore.Medium),
            },
            Pricing = ServiceDefinitionPricing.Free,
            Hosting = ServiceDefinitionHosting.Builtin,
            Notes = "Chat with your Sims 4 household. Install the companion script mod (voxta_bridge.ts4script) in the game's Mods folder, enable script mods, then turn on the 'sims4' augmentation on a character named like one of your Sims.",
            HelpLink = "https://github.com/Saintfrond/voxta-sims4",
            Augmentations = Sims4Constants.Augmentations,
            Logo = ModuleLogo.EmbeddedResource(typeof(VoxtaModule), "Assets.logo.svg"),
            ModuleConfigurationProviderType = typeof(ModuleConfigurationProvider),
            ModuleConfigurationFieldsRequiringReload = ModuleConfigurationProvider.FieldsRequiringReload,
        });

        // One game connection for the whole server, shared by every chat.
        builder.Services.AddSingleton<SimsBridge>();
        builder.AddChatAugmentationsService<ChatAugmentationsService>(Sims4Constants.ServiceName);
    }
}
