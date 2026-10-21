using System.Runtime.InteropServices;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(Mta.Synthetic.Sd05.Commands))]

namespace Mta.Synthetic.Sd05;

public static class Native
{
    // Writing through a null pointer inside native code: an access violation that no managed code sees.
    [DllImport("msvcrt.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr memset(IntPtr destination, int value, UIntPtr count);
}

public class Commands
{
    [CommandMethod("SD05", "SD05_CRASH", CommandFlags.Modal)]
    public void Crash() => Native.memset(IntPtr.Zero, 0, (UIntPtr)64);
}
