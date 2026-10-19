// Spike P1-T03: observe how AcCoreConsole behaves for load, exceptions, prompts, hangs and crashes.
using System.Reflection;
using System.Text.Json;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(Spike.SpikeApp))]
[assembly: CommandClass(typeof(Spike.SpikeCommands))]

namespace Spike;

internal static class Log
{
    private static readonly object Gate = new();
    private static int _seq;
    private static readonly string FilePath = Path.Combine(
        Environment.GetEnvironmentVariable("SPIKE_RUN_DIR") ?? Path.GetTempPath(), "spike-events.ndjson");

    public static void Write(string type, object? data = null)
    {
        lock (Gate)
        {
            var line = JsonSerializer.Serialize(new { seq = ++_seq, ts = DateTime.UtcNow.ToString("O"), type, data });
            File.AppendAllText(FilePath, line + Environment.NewLine);
        }
    }
}

public class SpikeApp : IExtensionApplication
{
    public void Initialize()
    {
        Log.Write("init", new { pid = Environment.ProcessId, runtime = Environment.Version.ToString() });
        if (Environment.GetEnvironmentVariable("SPIKE_THROW_INIT") == "1")
            throw new InvalidOperationException("spike: deliberate exception in Initialize");

        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            Log.Write("unhandled", new { e.IsTerminating, ex = e.ExceptionObject?.ToString() });

        AppDomain.CurrentDomain.FirstChanceException += (_, e) =>
        {
            if (e.Exception.TargetSite?.DeclaringType?.Assembly == typeof(SpikeApp).Assembly)
                Log.Write("first_chance", new { type = e.Exception.GetType().FullName, e.Exception.Message });
        };

        var doc = Application.DocumentManager.MdiActiveDocument;
        Log.Write("doc", new { hasDoc = doc != null, name = doc?.Name });
        if (doc == null) return;

        doc.CommandWillStart += (_, e) => Log.Write("cmd_start", new { e.GlobalCommandName });
        doc.CommandEnded += (_, e) => Log.Write("cmd_ended", new { e.GlobalCommandName });
        doc.CommandCancelled += (_, e) => Log.Write("cmd_cancelled", new { e.GlobalCommandName });
        doc.CommandFailed += (_, e) => Log.Write("cmd_failed", new { e.GlobalCommandName });
        doc.UnknownCommand += (_, e) => Log.Write("cmd_unknown", new { e.GlobalCommandName });

        var ed = doc.Editor;
        ed.PromptingForString += (_, e) => Log.Write("prompt", new { kind = "string", e.Options.Message });
        ed.PromptingForPoint += (_, e) => Log.Write("prompt", new { kind = "point", e.Options.Message });
        ed.PromptingForSelection += (_, e) => Log.Write("prompt", new { kind = "selection", msg = e.Options.MessageForAdding });
        ed.PromptingForKeyword += (_, e) => Log.Write("prompt", new { kind = "keyword", e.Options.Message });
        ed.PromptedForString += (_, e) => Log.Write("prompt_result", new { kind = "string", status = e.Result.Status.ToString() });
    }

    public void Terminate() => Log.Write("terminate");
}

public class SpikeCommands
{
    [CommandMethod("SPK_HELLO")]
    public void Hello() => Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nSPK hello\n");

    [CommandMethod("SPK_THROW")]
    public void Throw() => throw new InvalidOperationException("spike: deliberate exception");

    [CommandMethod("SPK_PROMPT")]
    public void Prompt()
    {
        var ed = Application.DocumentManager.MdiActiveDocument.Editor;
        var r = ed.GetString("\nSPK enter text: ");
        ed.WriteMessage($"\nSPK got status={r.Status} value='{r.StringResult}'\n");
    }

    [CommandMethod("SPK_SELECT")]
    public void Select()
    {
        var ed = Application.DocumentManager.MdiActiveDocument.Editor;
        var r = ed.GetSelection();
        ed.WriteMessage($"\nSPK selection status={r.Status}\n");
    }

    [CommandMethod("SPK_HANG")]
    public void Hang() => Thread.Sleep(TimeSpan.FromMinutes(10));

    [CommandMethod("SPK_CRASH")]
    public void Crash() => Environment.FailFast("spike: deliberate crash");

    // Discover which internal APIs exist for checking whether a command is defined.
    [CommandMethod("SPK_PROBEAPI")]
    public void ProbeApi()
    {
        var found = new List<string>();
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            if (!(asm.GetName().Name ?? "").StartsWith("Ac", StringComparison.OrdinalIgnoreCase)) continue;
            Type[] types;
            try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException e) { types = e.Types.Where(t => t != null).ToArray()!; }
            foreach (var t in types)
            {
                if (t.FullName is null || !t.FullName.Contains("Internal")) continue;
                foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.Static))
                    if (m.Name.Contains("Command", StringComparison.OrdinalIgnoreCase) &&
                        (m.Name.Contains("Defined") || m.Name.Contains("InUse") || m.Name.Contains("Lookup") || m.Name.Contains("Exists")))
                        found.Add($"{asm.GetName().Name}:{t.FullName}.{m.Name}({string.Join(",", m.GetParameters().Select(p => p.ParameterType.Name))})");
            }
        }
        Log.Write("probe_api", found);
        TryIsCommandDefined("SPK_HELLO");
        TryIsCommandDefined("LINE");
        TryIsCommandDefined("NOT_A_REAL_CMD");
    }

    private static void TryIsCommandDefined(string name)
    {
        var t = AppDomain.CurrentDomain.GetAssemblies()
            .Select(a => a.GetType("Autodesk.AutoCAD.Internal.Utils")).FirstOrDefault(x => x != null);
        var m = t?.GetMethod("IsCommandDefined", BindingFlags.Public | BindingFlags.Static);
        object? result = null; string? err = null;
        try { result = m?.Invoke(null, new object[] { name }); } catch (System.Exception e) { err = e.InnerException?.Message ?? e.Message; }
        Log.Write("is_command_defined", new { name, apiFound = m != null, result, err });
    }
}
