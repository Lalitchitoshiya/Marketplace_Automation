using System.Collections.Immutable;
using System.Reflection.Metadata;

namespace Mta.Inspect;

/// <summary>
/// Turns metadata type handles and signatures into readable names, so custom attribute blobs can be decoded
/// without loading the referenced assemblies. Enums of referenced assemblies (e.g. AutoCAD CommandFlags) are
/// assumed to be Int32, which is true for every AutoCAD attribute MTA decodes.
/// </summary>
internal sealed class NameProvider(MetadataReader reader)
    : ICustomAttributeTypeProvider<string>, ISignatureTypeProvider<string, object?>
{
    public string GetPrimitiveType(PrimitiveTypeCode typeCode) => "System." + typeCode;

    public string GetSystemType() => "System.Type";

    public string GetSZArrayType(string elementType) => elementType + "[]";

    public string GetTypeFromDefinition(MetadataReader r, TypeDefinitionHandle handle, byte rawTypeKind) =>
        Names.Type(r, handle);

    public string GetTypeFromReference(MetadataReader r, TypeReferenceHandle handle, byte rawTypeKind) =>
        Names.Type(r, handle);

    public string GetTypeFromSerializedName(string name) => name.Split(',')[0].Trim();

    public PrimitiveTypeCode GetUnderlyingEnumType(string type) => PrimitiveTypeCode.Int32;

    public bool IsSystemType(string type) => type == "System.Type";

    public string GetArrayType(string elementType, ArrayShape shape) => elementType + "[*]";

    public string GetByReferenceType(string elementType) => elementType + "&";

    public string GetFunctionPointerType(MethodSignature<string> signature) => "fnptr";

    public string GetGenericInstantiation(string genericType, ImmutableArray<string> typeArguments) => genericType;

    public string GetGenericMethodParameter(object? genericContext, int index) => "!!" + index;

    public string GetGenericTypeParameter(object? genericContext, int index) => "!" + index;

    public string GetModifiedType(string modifier, string unmodifiedType, bool isRequired) => unmodifiedType;

    public string GetPinnedType(string elementType) => elementType;

    public string GetPointerType(string elementType) => elementType + "*";

    public string GetTypeFromSpecification(MetadataReader r, object? genericContext, TypeSpecificationHandle handle, byte rawTypeKind) =>
        r.GetTypeSpecification(handle).DecodeSignature(this, genericContext);

    public MetadataReader Reader => reader;
}

internal static class Names
{
    public static string Type(MetadataReader r, EntityHandle handle) => handle.Kind switch
    {
        HandleKind.TypeDefinition => Type(r, (TypeDefinitionHandle)handle),
        HandleKind.TypeReference => Type(r, (TypeReferenceHandle)handle),
        HandleKind.TypeSpecification =>
            r.GetTypeSpecification((TypeSpecificationHandle)handle).DecodeSignature(new NameProvider(r), null),
        _ => "?",
    };

    public static string Type(MetadataReader r, TypeDefinitionHandle handle)
    {
        var def = r.GetTypeDefinition(handle);
        var name = r.GetString(def.Name);
        var declaring = def.GetDeclaringType();
        if (!declaring.IsNil)
            return Type(r, declaring) + "+" + name;
        var ns = r.GetString(def.Namespace);
        return ns.Length == 0 ? name : ns + "." + name;
    }

    public static string Type(MetadataReader r, TypeReferenceHandle handle)
    {
        var reference = r.GetTypeReference(handle);
        var name = r.GetString(reference.Name);
        if (reference.ResolutionScope.Kind == HandleKind.TypeReference)
            return Type(r, (TypeReferenceHandle)reference.ResolutionScope) + "+" + name;
        var ns = r.GetString(reference.Namespace);
        return ns.Length == 0 ? name : ns + "." + name;
    }

    /// <summary>Full name of the type that declares a custom attribute's constructor.</summary>
    public static string AttributeType(MetadataReader r, CustomAttribute attribute) => attribute.Constructor.Kind switch
    {
        HandleKind.MemberReference => Type(r, r.GetMemberReference((MemberReferenceHandle)attribute.Constructor).Parent),
        HandleKind.MethodDefinition =>
            Type(r, r.GetMethodDefinition((MethodDefinitionHandle)attribute.Constructor).GetDeclaringType()),
        _ => "?",
    };
}
