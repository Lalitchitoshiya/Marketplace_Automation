using System.Diagnostics;
using System.Reflection;
using System.Runtime.Versioning;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;
using AcDocument = Autodesk.AutoCAD.ApplicationServices.Document;

[assembly: ExtensionApplication(typeof(Wa.Session))]
[assembly: CommandClass(typeof(Wa.Commands))]

namespace Wa;

/// <summary>
/// Loaded first (ADR-0003 F11), stays passive unless the run-dir variable is set. Every hook catches its own
/// exceptions: the session must never change or crash the host (probe-protocol.md §5).
/// </summary>
public sealed class Session : IExtensionApplication
{
    private const int MaxFirstChance = 200;
    [ThreadStatic] private static bool _inHandler;

    internal static Session? Current { get; private set; }

    internal EventWriter? Events { get; private set; }
    internal Plan Plan { get; private set; } = new();
    internal string? RunDir { get; private set; }
    internal bool InOwnCommand { get; set; }
    internal string? CurrentMark { get; set; }
    internal int PluginExceptions { get; set; } // first-chance exceptions attributed to the plugin so far
    private int _firstChanceCount;
    private bool _shutdown;
    private readonly HashSet<AcDocument> _hooked = [];

    public void Initialize()
    {
        RunDir = Environment.GetEnvironmentVariable(Identity.RunDirEnv);
        if (string.IsNullOrEmpty(RunDir) || !Directory.Exists(RunDir)) return; // not under test: do nothing
        Current = this;
        try
        {
            Plan = Plan.Read(Path.Combine(RunDir, Identity.PlanFile));
            Events = new EventWriter(Path.Combine(RunDir, Identity.EventsFile), Plan.RunId);
            Events.Write("session.start", new
            {
                version = typeof(Session).Assembly.GetName().Version?.ToString(),
                host_id = "autocad",
                host_version = SafeSysvar("ACADVER"),
                pid = Environment.ProcessId,
                runtime = Environment.Version.ToString(),
            });
            AppDomain.CurrentDomain.AssemblyLoad += OnAssemblyLoad;
            AppDomain.CurrentDomain.UnhandledException += OnUnhandled;
            AppDomain.CurrentDomain.FirstChanceException += OnFirstChance;
            var documents = Application.DocumentManager;
            documents.DocumentCreated += (_, e) => Hook(e.Document);
            foreach (AcDocument document in documents) Hook(document);
            var started = Process.GetCurrentProcess().StartTime;
            Events.Write("host.ready", new
            {
                startup_ms = (long)(DateTime.Now - started).TotalMilliseconds,
                has_document = documents.MdiActiveDocument is not null,
            });
        }
        catch (System.Exception e)
        {
            Error(e);
        }
    }

    public void Terminate() => Shutdown("terminate");

    internal void Shutdown(string reason)
    {
        if (_shutdown || Events is null) return;
        _shutdown = true;
        Events.Write("session.shutdown", new { reason });
        Events.Dispose();
    }

    internal void Error(System.Exception e)
    {
        try
        {
            Events?.Write("session.error", new { message = e.Message, type = e.GetType().FullName, stack = e.StackTrace });
        }
        catch (System.Exception)
        {
            // Nothing else can be done without risking the host.
        }
    }

    private static string? SafeSysvar(string name)
    {
        try
        {
            return Application.GetSystemVariable(name)?.ToString();
        }
        catch (System.Exception)
        {
            return null;
        }
    }

    /// <summary>True when the assembly was loaded from the plugin's deployment folder (probe-protocol.md §5).</summary>
    internal bool IsPlugin(Assembly? assembly)
    {
        if (assembly is null || assembly.IsDynamic || string.IsNullOrEmpty(Plan.PluginDir)) return false;
        var location = assembly.Location;
        return location.Length > 0
               && Path.GetFullPath(location).StartsWith(Path.GetFullPath(Plan.PluginDir), StringComparison.OrdinalIgnoreCase);
    }

    private void OnAssemblyLoad(object? sender, AssemblyLoadEventArgs e)
    {
        try
        {
            var assembly = e.LoadedAssembly;
            var name = assembly.GetName();
            Events?.Write("assembly.load", new
            {
                name = name.Name,
                version = name.Version?.ToString(),
                path = assembly.IsDynamic ? null : assembly.Location,
                target_framework = TargetFramework(assembly),
                plugin = IsPlugin(assembly),
            });
        }
        catch (System.Exception ex)
        {
            Error(ex);
        }
    }

    /// <summary>
    /// Read without constructing attributes: GetCustomAttribute resolves every assembly attribute type, which can
    /// throw inside the load event for assemblies with WPF attributes, and then the event was lost (step 12).
    /// </summary>
    private static string? TargetFramework(Assembly assembly)
    {
        try
        {
            return assembly.GetCustomAttributesData()
                .FirstOrDefault(a => a.AttributeType.FullName == typeof(TargetFrameworkAttribute).FullName)
                ?.ConstructorArguments.FirstOrDefault().Value as string;
        }
        catch (System.Exception)
        {
            return null;
        }
    }

    /// <summary>True when an assembly loaded from exactly this file is in the process (load evidence).</summary>
    internal static bool IsLoaded(string path)
    {
        var full = Path.GetFullPath(path);
        return AppDomain.CurrentDomain.GetAssemblies().Any(a =>
        {
            try { return !a.IsDynamic && string.Equals(Path.GetFullPath(a.Location), full, StringComparison.OrdinalIgnoreCase); }
            catch (System.Exception) { return false; }
        });
    }

    private void OnUnhandled(object sender, UnhandledExceptionEventArgs e)
    {
        try
        {
            var ex = e.ExceptionObject as System.Exception;
            Events?.Write("exception.unhandled", new
            {
                type = ex?.GetType().FullName,
                message = ex?.Message,
                stack = ex?.ToString(),
                source_assembly = ex?.TargetSite?.Module.Assembly.GetName().Name,
                is_terminating = e.IsTerminating,
                mark = CurrentMark,
            });
        }
        catch (System.Exception)
        {
            // The process is going down; never throw from here.
        }
    }

    /// <summary>
    /// Records exceptions thrown with a plugin frame on the stack. In the core console an unhandled exception in
    /// a command kills the process before any other hook runs (ADR-0003 F8), so this is often the only evidence.
    /// </summary>
    private void OnFirstChance(object? sender, System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs e)
    {
        if (_inHandler || _firstChanceCount >= MaxFirstChance || string.IsNullOrEmpty(Plan.PluginDir)) return;
        _inHandler = true;
        try
        {
            var trace = new StackTrace(1, false);
            var source = trace.GetFrames()
                .Select(f => f.GetMethod()?.Module.Assembly)
                .FirstOrDefault(IsPlugin);
            if (source is null) return;
            _firstChanceCount++;
            PluginExceptions++;
            Events?.Write("exception.first_chance", new
            {
                type = e.Exception.GetType().FullName,
                message = e.Exception.Message,
                source_assembly = source.GetName().Name,
                stack = Stacks.Describe(trace),
                mark = CurrentMark,
            });
        }
        catch (System.Exception)
        {
            // Never let a diagnostic hook change the exception flow.
        }
        finally
        {
            _inHandler = false;
        }
    }

    private void Hook(AcDocument document)
    {
        if (!_hooked.Add(document)) return;
        document.CommandWillStart += (_, e) => CommandEvent("command.start", e.GlobalCommandName);
        document.CommandEnded += (_, e) => CommandEvent("command.ended", e.GlobalCommandName);
        document.CommandCancelled += (_, e) => CommandEvent("command.cancelled", e.GlobalCommandName);
        document.CommandFailed += (_, e) => CommandEvent("command.failed", e.GlobalCommandName);
        document.UnknownCommand += (_, e) => CommandEvent("command.unknown", e.GlobalCommandName);
        var editor = document.Editor;
        editor.PromptingForString += (_, e) => Prompt("string", e.Options.Message);
        editor.PromptingForKeyword += (_, e) => Prompt("keyword", e.Options.Message);
        editor.PromptingForPoint += (_, e) => Prompt("point", e.Options.Message);
        editor.PromptingForCorner += (_, e) => Prompt("corner", e.Options.Message);
        editor.PromptingForDistance += (_, e) => Prompt("distance", e.Options.Message);
        editor.PromptingForAngle += (_, e) => Prompt("angle", e.Options.Message);
        editor.PromptingForInteger += (_, e) => Prompt("integer", e.Options.Message);
        editor.PromptingForDouble += (_, e) => Prompt("double", e.Options.Message);
        editor.PromptingForEntity += (_, e) => Prompt("entity", e.Options.Message);
        editor.PromptingForNestedEntity += (_, e) => Prompt("nested_entity", e.Options.Message);
        editor.PromptingForSelection += (_, e) => Prompt("selection", e.Options.MessageForAdding);
    }

    private void CommandEvent(string type, string name)
    {
        if (Identity.IsOwnCommand(name)) return;
        try
        {
            Events?.Write(type, new { name, mark = CurrentMark });
        }
        catch (System.Exception ex)
        {
            Error(ex);
        }
    }

    private void Prompt(string kind, string? message)
    {
        if (InOwnCommand) return; // the session's own argument prompts are not plugin behaviour
        try
        {
            Events?.Write("prompt", new { kind, message, mark = CurrentMark });
        }
        catch (System.Exception ex)
        {
            Error(ex);
        }
    }
}
