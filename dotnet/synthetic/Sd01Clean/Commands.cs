using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;

[assembly: ExtensionApplication(typeof(Mta.Synthetic.Sd01.App))]
[assembly: CommandClass(typeof(Mta.Synthetic.Sd01.Commands))]

namespace Mta.Synthetic.Sd01;

public class App : IExtensionApplication
{
    public void Initialize() { }

    public void Terminate() { }
}

public class Commands
{
    // Completes without input.
    [CommandMethod("SD01", "SD01_HELLO", CommandFlags.Modal)]
    public void Hello() =>
        Application.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\nSD01 hello\n");

    // Modifies the drawing: adds one line to model space.
    [CommandMethod("SD01", "SD01_ADDLINE", CommandFlags.Modal)]
    public void AddLine()
    {
        var db = Application.DocumentManager.MdiActiveDocument.Database;
        using var tr = db.TransactionManager.StartTransaction();
        var space = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite);
        using var line = new Line(Point3d.Origin, new Point3d(10, 10, 0));
        space.AppendEntity(line);
        tr.AddNewlyCreatedDBObject(line, true);
        tr.Commit();
    }

    // Interactive: asks for a string and handles cancel correctly.
    [CommandMethod("SD01", "SD01_ASK", CommandFlags.Modal)]
    public void Ask()
    {
        var ed = Application.DocumentManager.MdiActiveDocument.Editor;
        var result = ed.GetString("\nSD01 enter a name: ");
        ed.WriteMessage($"\nSD01 status={result.Status}\n");
    }
}
