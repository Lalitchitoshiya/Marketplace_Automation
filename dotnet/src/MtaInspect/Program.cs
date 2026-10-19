using System.Reflection;
using System.Text.Json;

namespace Mta.Inspect;

internal static class Program
{
    internal const string Usage = """
        usage:
          mta-inspect <file>...                 describe assemblies / PE files as a JSON array
          mta-inspect --files-from <list>       same, with one path per line in <list>
          mta-inspect --enum <dll> <Type>       constant values of an enum, e.g. Autodesk.AutoCAD.Runtime.CommandFlags
          mta-inspect --version
        """;

    internal static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    };

    internal static string Version =>
        typeof(Program).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0]
        ?? "0.0.0";

    internal static int Main(string[] args) => Run(args, Console.Out, Console.Error);

    internal static int Run(string[] args, TextWriter output, TextWriter error)
    {
        switch (args)
        {
            case ["--version"]:
                output.WriteLine($"mta-inspect {Version}");
                return 0;
            case ["--enum", var dll, var type]:
                try
                {
                    output.WriteLine(JsonSerializer.Serialize(AssemblyInspector.EnumValues(dll, type), Json));
                    return 0;
                }
                catch (Exception e) when (e is ArgumentException or IOException or BadImageFormatException)
                {
                    error.WriteLine($"error: {e.Message}");
                    return 1;
                }
            case ["--files-from", var list]:
                if (!File.Exists(list)) break;
                return Describe(File.ReadAllLines(list).Where(l => l.Trim().Length > 0).Select(l => l.Trim()), output);
            case [var first, ..] when !first.StartsWith("--", StringComparison.Ordinal):
                return Describe(args, output);
        }
        error.WriteLine(Usage);
        return 2;
    }

    private static int Describe(IEnumerable<string> paths, TextWriter output)
    {
        // Per-file problems are reported in the JSON ("error"); the exit code stays 0 so one bad file
        // does not hide the others.
        var reports = paths.Select(AssemblyInspector.Inspect).ToList();
        output.WriteLine(JsonSerializer.Serialize(reports, Json));
        return 0;
    }
}
