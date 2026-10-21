using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Mta.Synthetic.Sd03.Commands))]

namespace Mta.Synthetic.Sd03;

public class Commands
{
    private static string? Missing => Environment.GetEnvironmentVariable("SD03_NEVER_SET");

    [CommandMethod("SD03", "SD03_OK", CommandFlags.Modal)]
    public void Ok() { }

    [CommandMethod("SD03", "SD03_BOOM", CommandFlags.Modal)]
    public void Boom() => _ = Missing!.Length;
}
