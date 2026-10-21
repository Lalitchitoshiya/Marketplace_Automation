using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Text.RegularExpressions;

namespace Mta.Inspect;

/// <summary>
/// Describes a plugin assembly from its metadata only (P1-R06). Nothing is loaded or executed: the file is
/// read with <see cref="PEReader"/> / <see cref="MetadataReader"/>, so hostile code in it never runs.
/// </summary>
public static partial class AssemblyInspector
{
    private const string Runtime = "Autodesk.AutoCAD.Runtime.";
    private const string CommandMethod = Runtime + "CommandMethodAttribute";
    private const string LispFunction = Runtime + "LispFunctionAttribute";
    private const string CommandClass = Runtime + "CommandClassAttribute";
    private const string ExtensionApplication = Runtime + "ExtensionApplicationAttribute";
    private const string IExtensionApplication = Runtime + "IExtensionApplication";
    private const int MaxUrls = 500;

    // Attributes left behind by common obfuscators (strong signal).
    private static readonly HashSet<string> ObfuscatorMarkers = new(StringComparer.OrdinalIgnoreCase)
    {
        "ConfusedByAttribute", "DotfuscatorAttribute", "ObfuscatedByGoliath", "BabelAttribute",
        "BabelObfuscatorAttribute", "PoweredByAttribute", "YanoAttribute", "CryptoObfuscatorAttribute",
        "ProcessedByXenocode", "NETGuard", "ObfuscatedByAgileDotNetAttribute", "SecureTeam.Attributes.ObfuscatedByCliSecureAttribute",
    };

    public static AssemblyReport Inspect(string path)
    {
        try
        {
            using var stream = File.OpenRead(path);
            using var pe = new PEReader(stream);
            var headers = pe.PEHeaders;
            var machine = headers.CoffHeader.Machine;
            var corFlags = headers.CorHeader?.Flags ?? 0;
            var report = new AssemblyReport
            {
                Path = path,
                Machine = MachineName(machine),
                Architecture = ArchitectureOf(machine, headers.CorHeader is not null, corFlags),
                IsManaged = pe.HasMetadata,
                MixedMode = pe.HasMetadata && (corFlags & CorFlags.ILOnly) == 0,
            };
            return pe.HasMetadata ? Describe(report, pe.GetMetadataReader()) : report;
        }
        catch (Exception e) when (e is not OutOfMemoryException)
        {
            // Never let one file (hostile or just unusual) take down the whole inspection.
            return new AssemblyReport { Path = path, Error = $"{e.GetType().Name}: {e.Message}" };
        }
    }

    private static string MachineName(Machine machine) => machine switch
    {
        Machine.Amd64 => "AMD64",
        Machine.I386 => "I386",
        Machine.Arm64 => "ARM64",
        _ => machine.ToString().ToUpperInvariant(),
    };

    private static string ArchitectureOf(Machine machine, bool managed, CorFlags flags) => machine switch
    {
        Machine.Amd64 => "x64",
        Machine.Arm64 => "arm64",
        Machine.I386 when managed && (flags & CorFlags.ILOnly) != 0 && (flags & CorFlags.Requires32Bit) == 0 => "anycpu",
        Machine.I386 => "x86",
        _ => "unknown",
    };

    private static AssemblyReport Describe(AssemblyReport report, MetadataReader r)
    {
        var provider = new NameProvider(r);
        string? name = null, version = null, tfm = null;
        var commandClasses = new List<string>();
        var extensionAttributes = new List<string>();
        if (r.IsAssembly)
        {
            var assembly = r.GetAssemblyDefinition();
            name = r.GetString(assembly.Name);
            version = assembly.Version.ToString();
            foreach (var handle in assembly.GetCustomAttributes())
            {
                var attribute = r.GetCustomAttribute(handle);
                var type = Names.AttributeType(r, attribute);
                if (type is not ("System.Runtime.Versioning.TargetFrameworkAttribute" or CommandClass or ExtensionApplication))
                    continue;
                var first = TryDecode(attribute, provider)?.FixedArguments.FirstOrDefault().Value as string;
                if (first is null) continue;
                if (type == CommandClass) commandClasses.Add(first);
                else if (type == ExtensionApplication) extensionAttributes.Add(first);
                else tfm = first;
            }
        }

        var (commands, lisp) = Commands(r, provider, commandClasses);
        var typeRefs = r.TypeReferences.Select(h => Names.Type(r, h)).Distinct().Order(StringComparer.Ordinal).ToList();
        return report with
        {
            AssemblyName = name,
            AssemblyVersion = version,
            TargetFramework = tfm,
            References = r.AssemblyReferences
                .Select(h => r.GetAssemblyReference(h))
                .Select(a => new AssemblyRef(r.GetString(a.Name), a.Version.ToString()))
                .ToList(),
            Commands = commands,
            LispFunctions = lisp,
            CommandClasses = commandClasses,
            ExtensionAppAttributes = extensionAttributes,
            ExtensionAppTypes = ExtensionAppTypes(r),
            Pinvokes = PInvokes(r),
            Urls = Urls(r),
            TypeRefs = typeRefs,
            MemberRefs = MemberRefs(r),
            Obfuscation = Obfuscation(r, typeRefs),
        };
    }

    private static (List<CommandInfo>, List<LispFunctionInfo>) Commands(
        MetadataReader r, NameProvider provider, List<string> commandClasses)
    {
        var commands = new List<CommandInfo>();
        var lisp = new List<LispFunctionInfo>();
        foreach (var handle in r.CustomAttributes)
        {
            var attribute = r.GetCustomAttribute(handle);
            if (attribute.Parent.Kind != HandleKind.MethodDefinition) continue;
            var attributeType = Names.AttributeType(r, attribute);
            if (attributeType is not (CommandMethod or LispFunction)) continue;

            var method = r.GetMethodDefinition((MethodDefinitionHandle)attribute.Parent);
            var type = Names.Type(r, method.GetDeclaringType());
            var methodName = r.GetString(method.Name);
            var decoded = TryDecode(attribute, provider);
            if (decoded is null) continue;
            var args = decoded.Value.FixedArguments;
            // Overloads: (global), (global, flags), (group, global, flags), (group, global, localId, flags, ...).
            // The leading strings name the command; the first Int32 is CommandFlags.
            var strings = args.TakeWhile(a => a.Value is string or null).Select(a => a.Value as string).ToList();
            if (strings.Count == 0) continue;
            if (attributeType == LispFunction)
            {
                lisp.Add(new LispFunctionInfo(strings[0] ?? "", type, methodName));
                continue;
            }
            var flags = args.Select(a => a.Value).OfType<int>().FirstOrDefault();
            var (group, global, local) = strings.Count switch
            {
                1 => (null, strings[0], null),
                2 => (strings[0], strings[1], null),
                _ => (strings[0], strings[1], strings[2]),
            };
            if (string.IsNullOrEmpty(global)) continue;
            var registered = commandClasses.Count == 0 || commandClasses.Contains(type);
            commands.Add(new CommandInfo(global, local, group, flags, type, methodName, registered));
        }
        return (commands, lisp);
    }

    /// <summary>One undecodable attribute blob must not lose the rest of the report.</summary>
    private static CustomAttributeValue<string>? TryDecode(CustomAttribute attribute, NameProvider provider)
    {
        try
        {
            return attribute.DecodeValue(provider);
        }
        catch (Exception e) when (e is BadImageFormatException or ArgumentException or InvalidOperationException
                                      or NullReferenceException or NotSupportedException)
        {
            return null;
        }
    }

    private static List<string> ExtensionAppTypes(MetadataReader r)
    {
        var found = new List<string>();
        foreach (var handle in r.TypeDefinitions)
        {
            var definition = r.GetTypeDefinition(handle);
            foreach (var implementation in definition.GetInterfaceImplementations())
            {
                var iface = Names.Type(r, r.GetInterfaceImplementation(implementation).Interface);
                if (iface == IExtensionApplication) found.Add(Names.Type(r, handle));
            }
        }
        return found;
    }

    private static List<PInvokeInfo> PInvokes(MetadataReader r)
    {
        var found = new List<PInvokeInfo>();
        foreach (var handle in r.MethodDefinitions)
        {
            var method = r.GetMethodDefinition(handle);
            if ((method.Attributes & MethodAttributes.PinvokeImpl) == 0) continue;
            var import = method.GetImport();
            var dll = import.Module.IsNil ? "?" : r.GetString(r.GetModuleReference(import.Module).Name);
            var entry = import.Name.IsNil ? r.GetString(method.Name) : r.GetString(import.Name);
            found.Add(new PInvokeInfo(dll, entry.Length > 0 ? entry : r.GetString(method.Name)));
        }
        return found.Distinct().ToList();
    }

    [GeneratedRegex(@"\b(?:https?|ftp|wss?)://[^\s""'<>\\]+", RegexOptions.IgnoreCase)]
    private static partial Regex UrlPattern();

    private static List<string> Urls(MetadataReader r)
    {
        var urls = new SortedSet<string>(StringComparer.Ordinal);
        if (r.GetHeapSize(HeapIndex.UserString) <= 1) return [];
        var handle = MetadataTokens.UserStringHandle(1);
        while (!handle.IsNil && urls.Count < MaxUrls)
        {
            foreach (Match match in UrlPattern().Matches(r.GetUserString(handle)))
                urls.Add(match.Value.TrimEnd('.', ',', ')', ';'));
            handle = r.GetNextHandle(handle);
        }
        return [.. urls];
    }

    private static List<string> MemberRefs(MetadataReader r) =>
        r.MemberReferences
            .Select(h => r.GetMemberReference(h))
            .Select(m => Names.Type(r, m.Parent) + "::" + r.GetString(m.Name))
            .Distinct()
            .Order(StringComparer.Ordinal)
            .ToList();

    private static ObfuscationInfo Obfuscation(MetadataReader r, List<string> typeRefs)
    {
        var signals = new List<string>();
        var strong = false;
        var defined = r.TypeDefinitions.Select(h => r.GetString(r.GetTypeDefinition(h).Name)).ToList();
        var marker = defined.Concat(typeRefs.Select(t => t.Split('.', '+')[^1]))
            .FirstOrDefault(n => ObfuscatorMarkers.Contains(n));
        if (marker is not null)
        {
            signals.Add($"obfuscator marker type {marker}");
            strong = true;
        }

        var names = defined.Concat(r.MethodDefinitions.Select(h => r.GetString(r.GetMethodDefinition(h).Name)))
            .Where(n => n.Length > 0 && !n.StartsWith('<') && !n.StartsWith('.'))
            .ToList();
        var odd = names.Count(n => n.Length <= 2 || n.Any(c => c < 0x20 || c > 0x7E));
        if (names.Count >= 10 && odd * 10 > names.Count * 3)
            signals.Add($"{odd} of {names.Count} type/method names are unreadable or 1-2 characters");

        var moduleType = r.TypeDefinitions.Select(h => r.GetTypeDefinition(h))
            .FirstOrDefault(t => r.GetString(t.Name) == "<Module>");
        if (moduleType.GetMethods().Any(m => r.GetString(r.GetMethodDefinition(m).Name) == ".cctor"))
            signals.Add("module initializer (<Module>..cctor) present");

        return new ObfuscationInfo { Suspected = strong || signals.Count >= 2, Signals = signals };
    }

    /// <summary>Constant values of an enum defined in an assembly, e.g. AutoCAD's CommandFlags.</summary>
    public static SortedDictionary<string, long> EnumValues(string path, string fullName)
    {
        using var stream = File.OpenRead(path);
        using var pe = new PEReader(stream);
        var r = pe.GetMetadataReader();
        var type = r.TypeDefinitions.FirstOrDefault(h => Names.Type(r, h) == fullName);
        if (type.IsNil) throw new ArgumentException($"type {fullName} not found in {path}");
        var values = new SortedDictionary<string, long>(StringComparer.Ordinal);
        foreach (var handle in r.GetTypeDefinition(type).GetFields())
        {
            var field = r.GetFieldDefinition(handle);
            var constant = field.GetDefaultValue();
            if (constant.IsNil) continue;
            var blob = r.GetBlobReader(r.GetConstant(constant).Value);
            values[r.GetString(field.Name)] = r.GetConstant(constant).TypeCode switch
            {
                ConstantTypeCode.Int32 => blob.ReadInt32(),
                ConstantTypeCode.UInt32 => blob.ReadUInt32(),
                ConstantTypeCode.Int64 => blob.ReadInt64(),
                ConstantTypeCode.Int16 => blob.ReadInt16(),
                ConstantTypeCode.Byte => blob.ReadByte(),
                _ => 0,
            };
        }
        return values;
    }
}
