using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(Mta.Synthetic.Sd02.App))]
[assembly: CommandClass(typeof(Mta.Synthetic.Sd02.Commands))]

namespace Mta.Synthetic.Sd02;

public class App : IExtensionApplication
{
    public void Initialize() => throw new InvalidOperationException("SD-02: Initialize fails");

    public void Terminate() { }
}

public class Commands
{
    [CommandMethod("SD02", "SD02_HELLO", CommandFlags.Modal)]
    public void Hello() { }
}
