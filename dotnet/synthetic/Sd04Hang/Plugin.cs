using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Mta.Synthetic.Sd04.Commands))]

namespace Mta.Synthetic.Sd04;

public class Commands
{
    [CommandMethod("SD04", "SD04_HANG", CommandFlags.Modal)]
    public void Hang()
    {
        while (true) Thread.Sleep(1000);
    }

    [CommandMethod("SD04", "SD04_OK", CommandFlags.Modal)]
    public void Ok() { }
}
