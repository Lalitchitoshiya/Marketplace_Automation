// Same full type names and constructor shapes as the AutoCAD .NET API (values from data/autocad/2026/commandflags.json).
#pragma warning disable CA1018, CA1813

namespace Autodesk.AutoCAD.Runtime
{
    [Flags]
    public enum CommandFlags
    {
        Modal = 0,
        Transparent = 1,
        UsePickSet = 2,
        Redraw = 4,
        NoMultiple = 16,
        Session = 2097152,
    }

    public interface IExtensionApplication
    {
        void Initialize();

        void Terminate();
    }

    [AttributeUsage(AttributeTargets.Method, AllowMultiple = true)]
    public sealed class CommandMethodAttribute : Attribute
    {
        public CommandMethodAttribute(string globalName) { }

        public CommandMethodAttribute(string globalName, CommandFlags flags) { }

        public CommandMethodAttribute(string groupName, string globalName, CommandFlags flags) { }

        public CommandMethodAttribute(string groupName, string globalName, string localizedNameId, CommandFlags flags) { }

        public CommandMethodAttribute(
            string groupName, string globalName, string localizedNameId, CommandFlags flags, string helpTopic) { }
    }

    [AttributeUsage(AttributeTargets.Method)]
    public sealed class LispFunctionAttribute(string globalName) : Attribute
    {
        public string GlobalName { get; } = globalName;
    }

    [AttributeUsage(AttributeTargets.Assembly, AllowMultiple = true)]
    public sealed class CommandClassAttribute(Type type) : Attribute
    {
        public Type Type { get; } = type;
    }

    [AttributeUsage(AttributeTargets.Assembly)]
    public sealed class ExtensionApplicationAttribute(Type type) : Attribute
    {
        public Type Type { get; } = type;
    }
}

namespace Autodesk.AutoCAD.Windows
{
    public class PaletteSet
    {
        public PaletteSet(string name) => Name = name;

        public string Name { get; }
    }
}
