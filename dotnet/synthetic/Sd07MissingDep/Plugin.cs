using Autodesk.AutoCAD.Runtime;
using Mta.Synthetic.Sd07Helper;

[assembly: ExtensionApplication(typeof(Mta.Synthetic.Sd07.App))]
[assembly: CommandClass(typeof(Mta.Synthetic.Sd07.Commands))]

namespace Mta.Synthetic.Sd07;

public class App : IExtensionApplication
{
    public static int Value { get; private set; }

    public void Initialize() => Value = Helper.Answer();  // FileNotFoundException: Sd07Helper is not shipped

    public void Terminate() { }
}

public class Commands
{
    [CommandMethod("SD07", "SD07_HELLO", CommandFlags.Modal)]
    public void Hello() { }
}
