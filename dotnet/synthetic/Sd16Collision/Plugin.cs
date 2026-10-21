using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Mta.Synthetic.Sd16.Commands))]

namespace Mta.Synthetic.Sd16;

public class Commands
{
    // AutoCAD's own LINE wins silently, so this command is unreachable (ADR-0003 F24).
    [CommandMethod("SD16", "LINE", CommandFlags.Modal)]
    public void Line() { }

    [CommandMethod("SD16", "SD16_HELLO", CommandFlags.Modal)]
    public void Hello() { }
}
