// Spike P1-T03: a plugin that touches the UI assembly (AcMgd) during Initialize and in a command.
using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(SpikeUi.UiApp))]
[assembly: CommandClass(typeof(SpikeUi.UiCommands))]

namespace SpikeUi;

public class UiApp : IExtensionApplication
{
    public void Initialize()
    {
        var path = Path.Combine(Environment.GetEnvironmentVariable("SPIKE_RUN_DIR") ?? Path.GetTempPath(), "spike-ui.txt");
        try
        {
            // UI-level Application (AcMgd), not ApplicationServices.Core.
            var ver = Autodesk.AutoCAD.ApplicationServices.Application.Version;
            File.AppendAllText(path, $"ui-init ok version={ver}\n");
        }
        catch (System.Exception e)
        {
            File.AppendAllText(path, $"ui-init failed {e.GetType().FullName}: {e.Message}\n");
            throw;
        }
    }

    public void Terminate() { }
}

public class UiCommands
{
    [CommandMethod("SPKUI_ALERT")]
    public void Alert() => Autodesk.AutoCAD.ApplicationServices.Application.ShowAlertDialog("spike ui alert");
}
