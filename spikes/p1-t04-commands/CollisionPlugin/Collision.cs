// Spike P1-T04: what happens when a plugin registers a command that already exists in AutoCAD?
// Also lists every public static API mentioning "Command" in Autodesk assemblies (looking for an enumeration API).
using System.Reflection;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Collision.Commands))]

namespace Collision;

public class Commands
{
    // Same global name as the built-in LINE command.
    [CommandMethod("SPKGRP", "LINE", CommandFlags.Modal)]
    public void FakeLine() =>
        Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nCOLLISION: plugin LINE ran instead of AutoCAD LINE\n");

    [CommandMethod("SPK_LISTAPI")]
    public void ListApi()
    {
        var outFile = Path.Combine(Environment.GetEnvironmentVariable("SPIKE_RUN_DIR") ?? Path.GetTempPath(), "command-apis.txt");
        var lines = new List<string>();
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            var name = asm.GetName().Name ?? "";
            if (!(name.StartsWith("Ac", StringComparison.OrdinalIgnoreCase) || name.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase)))
                continue;
            Type?[] types;
            try { types = asm.GetTypes(); } catch (ReflectionTypeLoadException e) { types = e.Types; }
            foreach (var t in types)
            {
                if (t is null) continue;
                foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
                    if (m.Name.Contains("Command", StringComparison.OrdinalIgnoreCase))
                        lines.Add($"{name} | {t.FullName}.{m.Name}({string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name))}) -> {m.ReturnType.Name}");
            }
        }
        File.WriteAllLines(outFile, lines.Distinct().OrderBy(x => x));
        Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage($"\nLISTAPI wrote {lines.Count} entries\n");
    }
}
