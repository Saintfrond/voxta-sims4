using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace Voxta.Modules.Sims4.Bridge;

/// <summary>
/// The one connection to the running game, shared by every chat. Voxta listens and the game connects,
/// because Voxta is up long before the game starts and long after it quits: the script mod just keeps
/// retrying until it gets through.
///
/// One game at a time. A new connection replaces the old one, which is what happens when the game
/// restarts before the old socket has noticed it is dead.
/// </summary>
public sealed class SimsBridge(ILogger<SimsBridge> logger) : IAsyncDisposable
{
    /// <summary>A game state line is a few kilobytes. Anything this long is not the mod talking.</summary>
    private const int MaxLineLength = 1024 * 1024;

    private readonly Lock _gate = new();
    private TcpListener? _listener;
    private CancellationTokenSource? _listenerCts;
    private IPEndPoint? _endpoint;
    private GameConnection? _connection;

    /// <summary>The most recent household snapshot. Kept after the game disconnects, so a chat can still say what it last saw.</summary>
    public GameState? State { get; private set; }

    public DateTimeOffset? StateReceivedAt { get; private set; }

    public bool IsConnected => _connection is not null;

    public string? ModVersion { get; private set; }

    /// <summary>Raised on the bridge's own thread. Handlers must not block it.</summary>
    public event Action<GameState>? StateChanged;

    public event Action<GameEvent>? EventReceived;

    public event Action<bool>? ConnectionChanged;

    /// <summary>
    /// Starts listening, or moves to a new port or address if the settings changed. Cheap to call
    /// every time a chat starts.
    /// </summary>
    public void EnsureListening(int port, bool anyInterface)
    {
        var endpoint = new IPEndPoint(anyInterface ? IPAddress.Any : IPAddress.Loopback, port);
        lock (_gate)
        {
            if (_listener is not null && endpoint.Equals(_endpoint))
                return;

            StopListeningLocked();

            var listener = new TcpListener(endpoint);
            try
            {
                listener.Start();
            }
            catch (SocketException exc)
            {
                logger.LogError(exc, "The Sims 4 bridge could not listen on {Endpoint}. Is another program using port {Port}?", endpoint, port);
                return;
            }

            _listener = listener;
            _endpoint = endpoint;
            _listenerCts = new CancellationTokenSource();
            _ = AcceptLoopAsync(listener, _listenerCts.Token);
            logger.LogInformation("The Sims 4 bridge is waiting for the game on {Endpoint}", endpoint);
        }
    }

    public Task NotifyAsync(NotifyCommand command, CancellationToken cancellationToken) => SendAsync(command, cancellationToken);

    public Task RequestStateAsync(CancellationToken cancellationToken) => SendAsync(new RequestStateCommand(), cancellationToken);

    private async Task SendAsync<T>(T message, CancellationToken cancellationToken)
    {
        var connection = _connection;
        if (connection is null) return;
        try
        {
            await connection.SendAsync(JsonSerializer.Serialize(message, BridgeJson.Options), cancellationToken);
        }
        catch (Exception exc) when (exc is IOException or SocketException or ObjectDisposedException)
        {
            logger.LogDebug(exc, "Could not send to the game; it probably just closed");
        }
    }

    private async Task AcceptLoopAsync(TcpListener listener, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            TcpClient client;
            try
            {
                client = await listener.AcceptTcpClientAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception exc) when (exc is SocketException or ObjectDisposedException)
            {
                if (cancellationToken.IsCancellationRequested) return;
                logger.LogWarning(exc, "The Sims 4 bridge stopped accepting connections");
                return;
            }

            client.NoDelay = true;
            var connection = new GameConnection(client);
            GameConnection? previous;
            lock (_gate)
            {
                previous = _connection;
                _connection = connection;
            }

            if (previous is not null)
            {
                logger.LogInformation("A new game connection replaces the previous one");
                await previous.DisposeAsync();
            }

            logger.LogInformation("The Sims 4 connected from {Remote}", client.Client.RemoteEndPoint);
            _ = RunConnectionAsync(connection, cancellationToken);
        }
    }

    private async Task RunConnectionAsync(GameConnection connection, CancellationToken cancellationToken)
    {
        try
        {
            await connection.SendAsync(JsonSerializer.Serialize(new ServerHello { Version = ModuleInfo.Version }, BridgeJson.Options), cancellationToken);
            Raise(ConnectionChanged, true);

            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await connection.ReadLineAsync(MaxLineLength, cancellationToken);
                if (line is null) break;
                if (line.Length == 0) continue;
                HandleLine(line);
            }
        }
        catch (Exception exc) when (exc is IOException or SocketException or ObjectDisposedException or OperationCanceledException)
        {
            // The game closed, crashed, or was replaced. All of those are ordinary.
        }
        catch (Exception exc)
        {
            logger.LogWarning(exc, "The Sims 4 connection failed");
        }
        finally
        {
            var wasCurrent = false;
            lock (_gate)
            {
                if (ReferenceEquals(_connection, connection))
                {
                    _connection = null;
                    wasCurrent = true;
                }
            }

            await connection.DisposeAsync();
            if (wasCurrent)
            {
                logger.LogInformation("The Sims 4 disconnected");
                Raise(ConnectionChanged, false);
            }
        }
    }

    private void HandleLine(string line)
    {
        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(line);
        }
        catch (JsonException exc)
        {
            logger.LogWarning(exc, "Ignoring a line from the game that is not JSON");
            return;
        }

        using (doc)
        {
            if (doc.RootElement.ValueKind != JsonValueKind.Object
                || !doc.RootElement.TryGetProperty("type", out var typeElement)
                || typeElement.ValueKind != JsonValueKind.String)
            {
                logger.LogWarning("Ignoring a message from the game without a type");
                return;
            }

            try
            {
                switch (typeElement.GetString())
                {
                    case "hello":
                        var hello = doc.RootElement.Deserialize<GameHello>(BridgeJson.Options);
                        ModVersion = hello?.ModVersion;
                        if (hello is not null && hello.Protocol != Sims4Constants.ProtocolVersion)
                            logger.LogWarning(
                                "The Sims 4 mod speaks protocol {ModProtocol}, this module {OurProtocol}. Update whichever is older.",
                                hello.Protocol, Sims4Constants.ProtocolVersion);
                        logger.LogInformation("The Sims 4 mod {Version} said hello", ModVersion ?? "(unknown version)");
                        break;
                    case "state":
                        var state = doc.RootElement.Deserialize<GameState>(BridgeJson.Options);
                        if (state is null) return;
                        State = state;
                        StateReceivedAt = DateTimeOffset.UtcNow;
                        Raise(StateChanged, state);
                        break;
                    case "event":
                        var gameEvent = doc.RootElement.Deserialize<GameEvent>(BridgeJson.Options);
                        if (gameEvent is null) return;
                        logger.LogDebug("Game event {Kind}: {Text}", gameEvent.Kind, gameEvent.Text);
                        Raise(EventReceived, gameEvent);
                        break;
                    case "ping":
                        _ = SendAsync(new { type = "pong" }, CancellationToken.None);
                        break;
                    case "bye":
                        logger.LogInformation("The Sims 4 said goodbye");
                        break;
                    default:
                        logger.LogDebug("Ignoring game message type {Type}", typeElement.GetString());
                        break;
                }
            }
            catch (JsonException exc)
            {
                logger.LogWarning(exc, "Ignoring a malformed {Type} message from the game", typeElement.GetString());
            }
        }
    }

    private void Raise<T>(Action<T>? handler, T value)
    {
        if (handler is null) return;
        foreach (var single in handler.GetInvocationList().Cast<Action<T>>())
        {
            try
            {
                single(value);
            }
            catch (Exception exc)
            {
                // One chat's bug must not cut the game off from the others.
                logger.LogWarning(exc, "A Sims 4 bridge listener failed");
            }
        }
    }

    private void StopListeningLocked()
    {
        _listenerCts?.Cancel();
        _listenerCts?.Dispose();
        _listenerCts = null;
        try
        {
            _listener?.Stop();
        }
        catch (SocketException)
        {
            // Already stopped.
        }

        _listener = null;
        _endpoint = null;
    }

    public async ValueTask DisposeAsync()
    {
        GameConnection? connection;
        lock (_gate)
        {
            StopListeningLocked();
            connection = _connection;
            _connection = null;
        }

        if (connection is not null)
            await connection.DisposeAsync();
    }

    /// <summary>One TCP connection, read as lines and written a line at a time.</summary>
    private sealed class GameConnection(TcpClient client) : IAsyncDisposable
    {
        private readonly NetworkStream _stream = client.GetStream();
        private readonly SemaphoreSlim _writeLock = new(1, 1);
        private readonly byte[] _buffer = new byte[16 * 1024];
        private readonly MemoryStream _pending = new();
        private int _disposed;

        public async Task SendAsync(string json, CancellationToken cancellationToken)
        {
            var bytes = Encoding.UTF8.GetBytes(json + "\n");
            await _writeLock.WaitAsync(cancellationToken);
            try
            {
                await _stream.WriteAsync(bytes, cancellationToken);
                await _stream.FlushAsync(cancellationToken);
            }
            finally
            {
                _writeLock.Release();
            }
        }

        /// <summary>Returns the next line without its newline, or null when the game closed the connection.</summary>
        public async Task<string?> ReadLineAsync(int maxLength, CancellationToken cancellationToken)
        {
            while (true)
            {
                var line = TryTakeLine();
                if (line is not null) return line;

                if (_pending.Length > maxLength)
                    throw new IOException($"The game sent a line longer than {maxLength} bytes");

                var read = await _stream.ReadAsync(_buffer, cancellationToken);
                if (read == 0) return null;
                _pending.Write(_buffer, 0, read);
            }
        }

        private string? TryTakeLine()
        {
            var data = _pending.GetBuffer();
            var length = (int)_pending.Length;
            var newline = Array.IndexOf(data, (byte)'\n', 0, length);
            if (newline < 0) return null;

            var end = newline > 0 && data[newline - 1] == '\r' ? newline - 1 : newline;
            var line = Encoding.UTF8.GetString(data, 0, end);

            var rest = length - newline - 1;
            Buffer.BlockCopy(data, newline + 1, data, 0, rest);
            _pending.SetLength(rest);
            return line;
        }

        public ValueTask DisposeAsync()
        {
            if (Interlocked.Exchange(ref _disposed, 1) == 1) return ValueTask.CompletedTask;
            try
            {
                client.Close();
            }
            catch (SocketException)
            {
                // Already closed.
            }

            _writeLock.Dispose();
            return ValueTask.CompletedTask;
        }
    }
}
