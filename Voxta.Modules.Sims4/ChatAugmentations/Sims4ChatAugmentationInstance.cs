using System.Collections.Concurrent;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using Voxta.Abstractions.Chats.Objects.Characters;
using Voxta.Abstractions.Chats.Sessions;
using Voxta.Abstractions.Model;
using Voxta.Abstractions.Scripting.ActionScripts;
using Voxta.Abstractions.Services.ChatAugmentations;
using Voxta.Model.Shared;
using Voxta.Modules.Sims4.Bridge;
using Voxta.Modules.Sims4.Configuration;
using Voxta.Modules.Sims4.Household;

namespace Voxta.Modules.Sims4.ChatAugmentations;

/// <summary>
/// One chat with the household. It keeps the chat's context in step with the game, passes notable
/// game events to the characters, and sends what they say back into the game.
///
/// Characters are matched to Sims by name. Everyone in the chat is known from the start; characters
/// a scenario enables later are picked up the first time they speak.
/// </summary>
public sealed partial class Sims4ChatAugmentationInstance : IChatScriptEventsAugmentation
{
    /// <summary>Needs and activities change every few seconds; the context is rebuilt at most this often.</summary>
    private static readonly TimeSpan ContextDebounce = TimeSpan.FromSeconds(3);

    /// <summary>A notification is a few lines on screen, not a transcript.</summary>
    private const int MaxNotificationLength = 450;

    private readonly IChatSessionChatAugmentationApi _session;
    private readonly SimsBridge _bridge;
    private readonly Sims4Settings _settings;
    private readonly ILogger _logger;
    private readonly SimMatcher _matcher;
    private readonly CancellationTokenSource _cts;

    /// <summary>Names of the characters seen in this chat.</summary>
    private readonly ConcurrentDictionary<string, byte> _characters = new(StringComparer.OrdinalIgnoreCase);

    private readonly SemaphoreSlim _publishLock = new(1, 1);
    private int _publishScheduled;
    private string? _lastContext;

    private volatile bool _generating;
    private volatile bool _userTyping;
    private DateTimeOffset _lastReaction = DateTimeOffset.MinValue;

    public Sims4ChatAugmentationInstance(
        IChatSessionChatAugmentationApi session,
        SimsBridge bridge,
        Sims4Settings settings,
        ILogger<Sims4ChatAugmentationInstance> logger
    )
    {
        _session = session;
        _bridge = bridge;
        _settings = settings;
        _logger = logger;
        _matcher = new SimMatcher(settings.NameAliases);
        _cts = CancellationTokenSource.CreateLinkedTokenSource(session.Abort);
        // Everyone in the chat from the start, so every Sim's state is there for the first reply.
        // Characters a scenario brings in later are picked up when they first speak.
        _characters.TryAdd(session.MainCharacter.Name, 0);
        foreach (var character in session.Chat.GetCharacters())
        {
            if (character.Enabled)
                _characters.TryAdd(character.Name, 0);
        }

        _bridge.StateChanged += OnStateChanged;
        _bridge.ConnectionChanged += OnConnectionChanged;
        _bridge.EventReceived += OnGameEvent;
    }

    public ServiceTypes[] GetRequiredServiceTypes() => [];

    public async Task StartAsync(CancellationToken cancellationToken)
    {
        await PublishContextAsync(cancellationToken);
        // A fresh snapshot rather than one that may be minutes old.
        await _bridge.RequestStateAsync(cancellationToken);

        if (_bridge.State is { } state && Match(_session.MainCharacter.Name, state) is null)
            _logger.LogWarning(
                "No Sim in the household matches the character '{Character}'. Household: {Sims}. Add a line under 'Character → Sim names' in the module settings.",
                _session.MainCharacter.Name,
                string.Join(", ", state.Sims.Select(s => s.FullName)));
    }

    // ---- Game → chat ----

    private void OnStateChanged(GameState state) => ScheduleContextUpdate();

    private void OnConnectionChanged(bool connected) => ScheduleContextUpdate();

    private void ScheduleContextUpdate()
    {
        if (Interlocked.Exchange(ref _publishScheduled, 1) == 1) return;
        _ = Task.Run(async () =>
        {
            try
            {
                await Task.Delay(ContextDebounce, _cts.Token);
                Interlocked.Exchange(ref _publishScheduled, 0);
                await PublishContextAsync(_cts.Token);
            }
            catch (OperationCanceledException)
            {
                // The chat ended.
            }
            catch (Exception exc)
            {
                Interlocked.Exchange(ref _publishScheduled, 0);
                _logger.LogWarning(exc, "Could not update the chat with the household's state");
            }
        });
    }

    /// <summary>Replaces this module's context in the chat with the latest household state.</summary>
    private async Task PublishContextAsync(CancellationToken cancellationToken)
    {
        await _publishLock.WaitAsync(cancellationToken);
        try
        {
            var state = _bridge.State;
            var text = HouseholdContextBuilder.Build(
                state,
                _bridge.IsConnected,
                Participants(state),
                new HouseholdContextBuilder.Options(_settings.UserRole, _settings.CustomUserRole)
            );

            // Most snapshots change nothing the characters would notice (a need moving from 63 to 61).
            if (text == _lastContext) return;
            _lastContext = text;

            await _session.SetContexts(
                Sims4Constants.ContextKey,
                [new ContextDefinition { Name = "The Sims 4 household", Text = text }],
                cancellationToken
            );
            _logger.LogDebug("Updated the household context:\n{Context}", text);
        }
        finally
        {
            _publishLock.Release();
        }
    }

    private void OnGameEvent(GameEvent gameEvent)
    {
        if (_settings.GameEvents == ModuleConfigurationProvider.EventsOff) return;
        if (string.IsNullOrWhiteSpace(gameEvent.Text)) return;

        // Events about the Sims in this chat, plus anything big enough to concern the whole household.
        var state = _bridge.State;
        var participants = Participants(state);
        var concernsChat = gameEvent.SimId is not null && participants.ContainsKey(gameEvent.SimId);
        if (!concernsChat && gameEvent.Importance < 2) return;

        _ = Task.Run(async () =>
        {
            try
            {
                await _session.SendSecretAsync($"[In the game: {gameEvent.Text}]", _cts.Token);

                if (_settings.GameEvents != ModuleConfigurationProvider.EventsReact) return;
                if (gameEvent.Importance < 1) return;
                if (_generating || _userTyping) return;
                var now = DateTimeOffset.UtcNow;
                if (now - _lastReaction < _settings.ReactCooldown) return;
                _lastReaction = now;

                // The context should describe the moment being reacted to, not the one before it.
                await PublishContextAsync(_cts.Token);
                await _session.TriggerReplyAsync(_cts.Token);
            }
            catch (OperationCanceledException)
            {
                // The chat ended.
            }
            catch (Exception exc)
            {
                _logger.LogWarning(exc, "Could not pass a game event to the chat");
            }
        });
    }

    // ---- Chat → game ----

    public async Task OnChatScriptEvent(
        IActionScriptEvent e,
        ChatMessageData? message,
        ICharacterOrUserData? character,
        CancellationToken cancellationToken
    )
    {
        switch (e)
        {
            case GeneratingActionScriptEvent generating:
                _generating = true;
                if (_characters.TryAdd(generating.Character.Name, 0))
                {
                    // A character from a group chat speaking for the first time: describe their Sim too.
                    _logger.LogInformation("'{Character}' joined the household chat", generating.Character.Name);
                    await PublishContextAsync(cancellationToken);
                }
                break;

            case GeneratingCompleteActionScriptEvent complete:
                _generating = false;
                if (_settings.ShowRepliesInGame)
                    await ShowInGameAsync(complete.Character.Name, complete.Message.Value, cancellationToken);
                break;

            case UserMessageReceivedActionScriptEvent userMessage:
                _userTyping = false;
                if (_settings.ShowUserMessagesInGame)
                    await ShowInGameAsync(_session.User.Name, userMessage.Message.Value, cancellationToken, isUser: true);
                break;

            case TypingStartScriptEvent:
                _userTyping = true;
                break;

            case TypingEndScriptEvent:
                _userTyping = false;
                break;
        }
    }

    private async Task ShowInGameAsync(string speaker, string? text, CancellationToken cancellationToken, bool isUser = false)
    {
        if (!_bridge.IsConnected || string.IsNullOrWhiteSpace(text)) return;

        var sim = isUser
            ? (_settings.UserRole == ModuleConfigurationProvider.UserIsActiveSim ? _bridge.State?.Sims.FirstOrDefault(s => s.IsActive) : null)
            : Match(speaker, _bridge.State);

        await _bridge.NotifyAsync(new NotifyCommand
        {
            SimId = sim?.Id,
            Title = sim?.FullName ?? speaker,
            Text = ForNotification(text),
        }, cancellationToken);
    }

    // ---- Helpers ----

    private SimInfo? Match(string characterName, GameState? state) =>
        state is null ? null : _matcher.Match(characterName, state.Sims);

    /// <summary>Sim id → character name, for the characters seen in this chat that have a Sim.</summary>
    private Dictionary<string, string> Participants(GameState? state)
    {
        var result = new Dictionary<string, string>();
        if (state is null) return result;
        foreach (var name in _characters.Keys)
        {
            var sim = Match(name, state);
            if (sim is not null) result.TryAdd(sim.Id, name);
        }

        return result;
    }

    internal static string ForNotification(string text)
    {
        var flat = Whitespace().Replace(text, " ").Trim();
        if (flat.Length <= MaxNotificationLength) return flat;

        // Cut at a sentence end if there is one in the last third, else at a word.
        var cut = flat[..MaxNotificationLength];
        var sentenceEnd = cut.LastIndexOfAny(['.', '!', '?']);
        if (sentenceEnd > MaxNotificationLength * 2 / 3) return cut[..(sentenceEnd + 1)];
        var space = cut.LastIndexOf(' ');
        return (space > 0 ? cut[..space] : cut) + "…";
    }

    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    public async ValueTask DisposeAsync()
    {
        _bridge.StateChanged -= OnStateChanged;
        _bridge.ConnectionChanged -= OnConnectionChanged;
        _bridge.EventReceived -= OnGameEvent;
        // Cancelled, not disposed: a debounce or event task may still be about to read the token.
        await _cts.CancelAsync();
    }
}
