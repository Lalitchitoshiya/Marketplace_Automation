using System.Diagnostics;
using System.Reflection;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Runtime;

namespace Wa;

/// <summary>
/// Commands driven by the generated script. Each one reads its argument from the next script line, so a
/// script line pair such as "LOAD command / component name" performs one action (design.md §5.2, §5.3).
/// </summary>
public sealed class Commands
{
    private static Session? S => Session.Current;

    private static string? Argument(string label)
    {
        var session = S;
        if (session is null) return null;
        session.InOwnCommand = true;
        try
        {
            var editor = Application.DocumentManager.MdiActiveDocument.Editor;
            var result = editor.GetString(new PromptStringOptions($"\n{label}: ") { AllowSpaces = true });
            return result.Status == PromptStatus.OK ? result.StringResult.Trim() : null;
        }
        finally
        {
            session.InOwnCommand = false;
        }
    }

    private static void Guard(Action action)
    {
        if (S?.Events is null) return;
        try
        {
            action();
        }
        catch (System.Exception e)
        {
            S.Error(e);
        }
    }

    /// <summary>Loads one plan component with timing; Initialize exceptions surface as first-chance events (F11).</summary>
    [CommandMethod(Identity.Group, Identity.Load, CommandFlags.Modal)]
    public void Load() => Guard(() =>
    {
        var name = Argument("Name");
        var component = S!.Plan.Components.FirstOrDefault(
            c => string.Equals(c.Name, name, StringComparison.OrdinalIgnoreCase));
        if (component is null)
        {
            S.Events!.Write("component.load.end", new { component = name, ok = false, error = "not in plan", duration_ms = 0 });
            return;
        }
        S.Events!.Write("component.load.begin", new { component = component.Name, module_path = component.Module, loader = component.Loader });
        var before = S.PluginExceptions;
        var clock = Stopwatch.StartNew();
        string? error = null;
        try
        {
            if (component.Loader == "arx")
                SystemObjects.DynamicLinker.LoadModule(component.Module, false, false);
            else
                ExtensionLoader.Load(component.Module);
        }
        catch (System.Exception e)
        {
            error = $"{e.GetType().FullName}: {e.Message}";
        }
        S.Events.Write("component.load.end", new
        {
            component = component.Name,
            module_path = component.Module,
            loader = component.Loader,
            ok = error is null,
            loaded = component.Loader == "arx" ? (bool?)null : Session.IsLoaded(component.Module),
            error,
            plugin_exceptions = S.PluginExceptions - before,
            duration_ms = clock.ElapsedMilliseconds,
        });
    });

    /// <summary>Commands the loaded plugin assemblies declare, as seen at runtime (command.registered).</summary>
    [CommandMethod(Identity.Group, Identity.Enumerate, CommandFlags.Modal)]
    public void Enumerate() => Guard(() =>
    {
        var count = 0;
        const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies().Where(S!.IsPlugin))
        {
            Type?[] types;
            try { types = assembly.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            foreach (var type in types.OfType<Type>())
            foreach (var method in type.GetMethods(all))
            foreach (var attribute in method.GetCustomAttributes<CommandMethodAttribute>(false))
            {
                count++;
                S.Events!.Write("command.registered", new
                {
                    name = attribute.GlobalName,
                    group = attribute.GroupName,
                    flags = (int)attribute.Flags,
                    source_assembly = assembly.GetName().Name,
                    method = $"{type.FullName}.{method.Name}",
                });
            }
        }
        S.Events!.Write("enumerate.end", new { count });
    });

    /// <summary>"begin X" / "end X": brackets smoke invocations in the event stream (design.md §5.5).</summary>
    [CommandMethod(Identity.Group, Identity.Mark, CommandFlags.Modal)]
    public void Mark() => Guard(() =>
    {
        var text = Argument("Label") ?? "";
        var parts = text.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
        var phase = parts.Length > 0 ? parts[0].ToLowerInvariant() : "";
        var label = parts.Length > 1 ? parts[1] : "";
        S!.CurrentMark = phase == "begin" ? label : null;
        S.Events!.Write("mark", new { phase, label });
    });

    /// <summary>
    /// One in-drawing assertion (scenario-dsl.md §3). Forms:
    /// "entity_count TYPE OP N LAYER" (TYPE = ObjectARX class such as AcDbLine or *, LAYER or *),
    /// "layer_exists NAME", "block_exists NAME", "sysvar NAME VALUE". "count OP N" is kept for step 11 tests.
    /// </summary>
    [CommandMethod(Identity.Group, Identity.Assert, CommandFlags.Modal)]
    public void Assert() => Guard(() =>
    {
        var text = Argument("Check") ?? "";
        var parts = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string? actual = null;
        var ok = false;
        switch (parts)
        {
            case ["count", var op, var n] when int.TryParse(n, out var expected):
                var all = CountEntities("*", "*");
                (actual, ok) = (all.ToString(), Compare(all, op, expected));
                break;
            case ["entity_count", var type, var op, var n, var layer] when int.TryParse(n, out var expected):
                var count = CountEntities(type, layer);
                (actual, ok) = (count.ToString(), Compare(count, op, expected));
                break;
            case ["layer_exists", .. var name]:
                ok = TableHas(db => db.LayerTableId, string.Join(' ', name));
                actual = ok.ToString();
                break;
            case ["block_exists", .. var name]:
                ok = TableHas(db => db.BlockTableId, string.Join(' ', name));
                actual = ok.ToString();
                break;
            case ["sysvar", var name, .. var value]:
                actual = Application.GetSystemVariable(name)?.ToString();
                ok = string.Equals(actual, string.Join(' ', value), StringComparison.OrdinalIgnoreCase);
                break;
        }
        S!.Events!.Write("assert.result", new { assertion = text, actual, ok, mark = S.CurrentMark });
    });

    private static bool Compare(int actual, string op, int expected) => op switch
    {
        "==" => actual == expected,
        "!=" => actual != expected,
        ">=" => actual >= expected,
        "<=" => actual <= expected,
        ">" => actual > expected,
        "<" => actual < expected,
        _ => false,
    };

    [CommandMethod(Identity.Group, Identity.End, CommandFlags.Modal)]
    public void End() => Guard(() => S!.Shutdown("end"));

    /// <summary>(fn "defined" "CMD" (getcname "CMD")): the script reports getcname results (ADR-0003 F18).</summary>
    [LispFunction(Identity.LispFunction)]
    public ResultBuffer Note(ResultBuffer? args)
    {
        Guard(() =>
        {
            var values = args?.AsArray() ?? [];
            string? Text(int i) => i < values.Length && values[i].Value is string s ? s : null;
            var kind = Text(0);
            var name = Text(1);
            var value = Text(2); // nil arrives as LispDataType.Nil: no string
            if (kind == "defined")
                S!.Events!.Write("command.defined", new { name, defined = value is not null, global = value });
            else
                S!.Events!.Write("note", new { kind, name, value });
        });
        return new ResultBuffer(new TypedValue((int)LispDataType.T_atom));
    }

    private static int CountEntities(string type, string layer)
    {
        var db = Application.DocumentManager.MdiActiveDocument.Database;
        using var tr = db.TransactionManager.StartOpenCloseTransaction();
        var space = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
        var count = 0;
        foreach (ObjectId id in space)
        {
            if (type != "*" && !string.Equals(id.ObjectClass.Name, type, StringComparison.OrdinalIgnoreCase)) continue;
            if (layer != "*")
            {
                var entity = (Entity)tr.GetObject(id, OpenMode.ForRead);
                if (!string.Equals(entity.Layer, layer, StringComparison.OrdinalIgnoreCase)) continue;
            }
            count++;
        }
        tr.Commit();
        return count;
    }

    private static bool TableHas(Func<Database, ObjectId> table, string name)
    {
        var db = Application.DocumentManager.MdiActiveDocument.Database;
        using var tr = db.TransactionManager.StartOpenCloseTransaction();
        var found = ((SymbolTable)tr.GetObject(table(db), OpenMode.ForRead)).Has(name);
        tr.Commit();
        return found;
    }
}
