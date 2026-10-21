using System.Text.Json;
using System.Text.Json.Serialization;

namespace Wa;

/// <summary>The plan file written by the orchestrator (probe-protocol.md §4).</summary>
internal sealed record Plan
{
    [JsonPropertyName("v")] public int Version { get; init; } = 1;
    [JsonPropertyName("run_id")] public string RunId { get; init; } = "unknown";
    [JsonPropertyName("plugin_dir")] public string? PluginDir { get; init; }
    [JsonPropertyName("components")] public List<PlanComponent> Components { get; init; } = [];

    public static Plan Read(string path) =>
        File.Exists(path) ? JsonSerializer.Deserialize<Plan>(File.ReadAllText(path)) ?? new Plan() : new Plan();
}

internal sealed record PlanComponent
{
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("module")] public string Module { get; init; } = "";
    [JsonPropertyName("loader")] public string Loader { get; init; } = "netload"; // netload | arx
}
