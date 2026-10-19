namespace Mta.Inspect;

// JSON contract read by src/mta/static/dotnet.py (snake_case). Add fields; never rename without updating both sides.

public sealed record AssemblyReport
{
    public required string Path { get; init; }
    public bool IsManaged { get; init; }
    public string Machine { get; init; } = "UNKNOWN"; // COFF machine: AMD64, I386, ARM64, ...
    public string Architecture { get; init; } = "unknown"; // x64, x86, anycpu, arm64, unknown
    public bool MixedMode { get; init; } // managed + native code (C++/CLI)
    public string? AssemblyName { get; init; }
    public string? AssemblyVersion { get; init; }
    public string? TargetFramework { get; init; } // e.g. ".NETCoreApp,Version=v8.0"
    public List<AssemblyRef> References { get; init; } = [];
    public List<CommandInfo> Commands { get; init; } = [];
    public List<LispFunctionInfo> LispFunctions { get; init; } = [];
    public List<string> CommandClasses { get; init; } = []; // [assembly: CommandClass(typeof(...))]
    public List<string> ExtensionAppAttributes { get; init; } = []; // [assembly: ExtensionApplication(typeof(...))]
    public List<string> ExtensionAppTypes { get; init; } = []; // types implementing IExtensionApplication
    public List<PInvokeInfo> Pinvokes { get; init; } = [];
    public List<string> Urls { get; init; } = [];
    public List<string> TypeRefs { get; init; } = [];
    public List<string> MemberRefs { get; init; } = []; // "Namespace.Type::Member"
    public ObfuscationInfo Obfuscation { get; init; } = new();
    public string? Error { get; init; }
}

public sealed record AssemblyRef(string Name, string Version);

public sealed record CommandInfo(
    string GlobalName,
    string? LocalName,
    string? Group,
    int Flags,
    string Type,
    string Method,
    bool Registered); // false when [assembly: CommandClass] exists and does not list the type

public sealed record LispFunctionInfo(string Name, string Type, string Method);

public sealed record PInvokeInfo(string Dll, string Entry);

public sealed record ObfuscationInfo
{
    public bool Suspected { get; init; }
    public List<string> Signals { get; init; } = [];
}
