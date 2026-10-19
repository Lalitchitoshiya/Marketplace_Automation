using Mta.Inspect;
using Xunit;

namespace MtaInspect.Tests;

public class InspectorTests
{
    // bin/<Configuration>/net8.0/ -> tests/fixtures/<Project>/bin/<Configuration>/<tfm>/<Project>.dll
    private static string Fixture(string project, string tfm)
    {
        var bin = new DirectoryInfo(AppContext.BaseDirectory);
        var configuration = bin.Parent!.Name;
        var tests = bin.Parent!.Parent!.Parent!.Parent!.FullName;
        return Path.Combine(tests, "fixtures", project, "bin", configuration, tfm, project + ".dll");
    }

    private static readonly AssemblyReport Plugin = AssemblyInspector.Inspect(Fixture("FixturePlugin", "net8.0"));

    [Fact]
    public void DescribesFrameworkArchitectureAndReferences()
    {
        Assert.Null(Plugin.Error);
        Assert.True(Plugin.IsManaged);
        Assert.Equal(".NETCoreApp,Version=v8.0", Plugin.TargetFramework);
        Assert.Equal("anycpu", Plugin.Architecture);
        Assert.Contains(new AssemblyRef("AcCoreMgd", "25.0.0.0"), Plugin.References);
    }

    [Theory]
    [InlineData("FIX_ONE", null, null, 0)]
    [InlineData("FIX_TWO", null, null, 6)] // UsePickSet | Redraw
    [InlineData("FIX_THREE", "FIXGRP", null, 2097152)] // Session
    [InlineData("FIX_FOUR", "FIXGRP", "FIX_FOUR_LOCAL", 0)]
    [InlineData("FIX_FIVE", "FIXGRP", "FIX_FIVE_LOCAL", 1)]
    public void DecodesEveryCommandMethodOverload(string global, string? group, string? local, int flags)
    {
        var command = Assert.Single(Plugin.Commands, c => c.GlobalName == global);
        Assert.Equal((group, local, flags, true), (command.Group, command.LocalName, command.Flags, command.Registered));
        Assert.Equal("Fixture.Commands", command.Type);
    }

    [Fact]
    public void CommandsOutsideCommandClassAreNotRegistered()
    {
        Assert.Equal(["Fixture.Commands"], Plugin.CommandClasses);
        Assert.False(Assert.Single(Plugin.Commands, c => c.GlobalName == "FIX_HIDDEN").Registered);
    }

    [Fact]
    public void FindsExtensionApplicationLispPInvokesAndUrls()
    {
        Assert.Equal(["Fixture.App"], Plugin.ExtensionAppAttributes);
        Assert.Equal(["Fixture.App"], Plugin.ExtensionAppTypes);
        Assert.Equal("fix-lisp", Assert.Single(Plugin.LispFunctions).Name);
        Assert.Equal(new PInvokeInfo("user32.dll", "FindWindowW"), Assert.Single(Plugin.Pinvokes));
        Assert.Contains("https://api.fixture.example/v1/items", Plugin.Urls);
        Assert.Contains("Autodesk.AutoCAD.Windows.PaletteSet", Plugin.TypeRefs);
        Assert.Contains("System.Diagnostics.Process::Start", Plugin.MemberRefs);
        Assert.False(Plugin.Obfuscation.Suspected);
    }

    [Fact]
    public void DescribesNetFrameworkX86()
    {
        var report = AssemblyInspector.Inspect(Fixture("FixtureNet48", "net48"));
        Assert.Equal(".NETFramework,Version=v4.8", report.TargetFramework);
        Assert.Equal(("x86", "I386"), (report.Architecture, report.Machine));
        Assert.Equal("mscorlib", Assert.Single(report.References).Name);
    }

    [Fact]
    public void NativeDllIsNotManaged()
    {
        var report = AssemblyInspector.Inspect(Path.Combine(Environment.SystemDirectory, "kernel32.dll"));
        Assert.False(report.IsManaged);
        Assert.Equal(("AMD64", "x64"), (report.Machine, report.Architecture));
    }

    [Fact]
    public void NonPeFileIsReportedNotThrown()
    {
        var path = Path.GetTempFileName();
        File.WriteAllText(path, "not a PE file");
        try
        {
            var report = AssemblyInspector.Inspect(path);
            Assert.StartsWith("BadImageFormatException", report.Error);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void ReadsEnumConstantsWithoutLoading()
    {
        var values = AssemblyInspector.EnumValues(
            Path.Combine(Path.GetDirectoryName(Fixture("FixturePlugin", "net8.0"))!, "AcCoreMgd.dll"),
            "Autodesk.AutoCAD.Runtime.CommandFlags");
        Assert.Equal(2097152, values["Session"]);
        Assert.Equal(6, values.Count);
    }

    [Fact]
    public void CommandLineWritesJsonArray()
    {
        var list = Path.GetTempFileName();
        File.WriteAllLines(list, [Fixture("FixtureNet48", "net48"), ""]);
        var output = new StringWriter();
        try
        {
            Assert.Equal(0, Program.Run(["--files-from", list], output, TextWriter.Null));
        }
        finally
        {
            File.Delete(list);
        }
        Assert.Contains("\"target_framework\": \".NETFramework,Version=v4.8\"", output.ToString());
        Assert.Equal(2, Program.Run(["--files-from", "missing.txt"], TextWriter.Null, TextWriter.Null));
        Assert.Equal(1, Program.Run(["--enum", "missing.dll", "X"], TextWriter.Null, TextWriter.Null));
    }
}
