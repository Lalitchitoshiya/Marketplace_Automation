using System.Diagnostics;
using System.Runtime.InteropServices;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.Windows;

[assembly: ExtensionApplication(typeof(Fixture.App))]
[assembly: CommandClass(typeof(Fixture.Commands))]

namespace Fixture;

public class App : IExtensionApplication
{
    public void Initialize() { }

    public void Terminate() { }
}

public class Commands
{
    [CommandMethod("FIX_ONE")]
    public void One() { }

    [CommandMethod("FIX_TWO", CommandFlags.UsePickSet | CommandFlags.Redraw)]
    public void Two() { }

    [CommandMethod("FIXGRP", "FIX_THREE", CommandFlags.Session)]
    public void Three() { }

    [CommandMethod("FIXGRP", "FIX_FOUR", "FIX_FOUR_LOCAL", CommandFlags.Modal)]
    public void Four() { }

    [CommandMethod("FIXGRP", "FIX_FIVE", "FIX_FIVE_LOCAL", CommandFlags.Transparent, "help-topic")]
    public void Five() { }

    // Same name as the built-in LINE command (CMD-003, ADR-0003 F24).
    [CommandMethod("FIXGRP", "LINE", CommandFlags.Modal)]
    public void Line() { }

    [LispFunction("fix-lisp")]
    public object? Lisp() => null;

    public void Palette() => _ = new PaletteSet("Fixture");

    public void Spawn() => Process.Start("notepad.exe");

    public static string Endpoint => "https://api.fixture.example/v1/items, see http://schemas.microsoft.com/x";

    [DllImport("user32.dll", EntryPoint = "FindWindowW", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindow(string? className, string? windowName);
}

// Not listed in [assembly: CommandClass], so AutoCAD does not register its commands.
public class Hidden
{
    [CommandMethod("FIX_HIDDEN")]
    public void Hide() { }
}
