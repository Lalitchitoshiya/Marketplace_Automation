using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Mta.Synthetic.Canary.Commands))]

namespace Mta.Synthetic.Canary;

public class Commands
{
    // Completes (F19: command events).
    [CommandMethod("CANARY", "CANARY_HELLO", CommandFlags.Modal)]
    public void Hello() => Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nCANARY hello\n");

    // Waits for input (F5: (command) cancels the prompt).
    [CommandMethod("CANARY", "CANARY_PROMPT", CommandFlags.Modal)]
    public void Prompt() => Application.DocumentManager.MdiActiveDocument.Editor.GetString("\nCANARY value: ");

    // Unhandled exception (F8: the core console exits with 0xC0000005).
    [CommandMethod("CANARY", "CANARY_THROW", CommandFlags.Modal)]
    public void Throw() => throw new InvalidOperationException("canary: deliberate exception");

    // Never returns (F10: only the watchdog ends it).
    [CommandMethod("CANARY", "CANARY_HANG", CommandFlags.Modal)]
    public void Hang()
    {
        while (true) Thread.Sleep(1000);
    }
}
