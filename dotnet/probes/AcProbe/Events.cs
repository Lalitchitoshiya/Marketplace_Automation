using System.Diagnostics;
using System.Text.Json;

namespace Wa;

/// <summary>Append-only NDJSON event file (probe-protocol.md §2). Thread-safe; every line is flushed.</summary>
internal sealed class EventWriter : IDisposable
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private readonly object _gate = new();
    private readonly StreamWriter _writer;
    private readonly string _runId;
    private long _seq;

    public EventWriter(string path, string runId)
    {
        _runId = runId;
        var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
        _writer = new StreamWriter(stream, new System.Text.UTF8Encoding(false)) { AutoFlush = true };
    }

    public void Write(string type, object? data = null)
    {
        lock (_gate)
        {
            var line = JsonSerializer.Serialize(
                new
                {
                    v = 1,
                    seq = ++_seq,
                    ts = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'"),
                    run_id = _runId,
                    type,
                    data = data ?? new { },
                },
                Json);
            _writer.WriteLine(line);
        }
    }

    public void Dispose()
    {
        lock (_gate) _writer.Dispose();
    }
}

internal static class Stacks
{
    /// <summary>The current call stack as text, at most <paramref name="max"/> frames.</summary>
    public static string Describe(StackTrace trace, int max = 40) =>
        string.Join("\n", trace.GetFrames().Take(max).Select(f =>
        {
            var m = f.GetMethod();
            return m is null ? "?" : $"{m.DeclaringType?.FullName}.{m.Name} [{m.Module.Assembly.GetName().Name}]";
        }));
}
