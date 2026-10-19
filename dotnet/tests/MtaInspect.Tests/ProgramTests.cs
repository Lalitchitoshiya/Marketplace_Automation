using Mta.Inspect;
using Xunit;

namespace MtaInspect.Tests;

public class ProgramTests
{
    [Fact]
    public void VersionMatchesBuildVersion() => Assert.Equal("0.1.0", Program.Version);

    [Fact]
    public void UnknownArgumentsReturnUsageExitCode() => Assert.Equal(2, Program.Main(["--nope"]));
}
