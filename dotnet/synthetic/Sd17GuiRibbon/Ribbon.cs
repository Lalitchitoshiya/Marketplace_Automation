using Autodesk.AutoCAD.Runtime;
using Autodesk.Windows;

[assembly: ExtensionApplication(typeof(Mta.Synthetic.Sd17.App))]
[assembly: CommandClass(typeof(Mta.Synthetic.Sd17.Commands))]

namespace Mta.Synthetic.Sd17;

public class App : IExtensionApplication
{
    // ComponentManager.Ribbon exists only in the full AutoCAD UI; in the core console this throws.
    public void Initialize() => ComponentManager.Ribbon.Tabs.Add(new RibbonTab { Title = "SD17", Id = "SD17_TAB" });

    public void Terminate() { }
}

public class Commands
{
    [CommandMethod("SD17", "SD17_HELLO", CommandFlags.Modal)]
    public void Hello() { }
}
