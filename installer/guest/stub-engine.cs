// Stand-in container engine for the image-pull probes of the guest proof (ecosystem-control#64): never a real engine, no network, pulls nothing.
// Compiled in the guest with the .NET Framework csc.exe as docker.exe; no binary is committed. It appends its whole command line to
// C:\Temp\stub-engine.txt and exits with the number in C:\Temp\stub-rc.txt (0 when that file is absent or holds no number).
using System;
using System.IO;

public static class StubEngine
{
    public static int Main(string[] args)
    {
        string log = @"C:\Temp\stub-engine.txt";
        string rcFile = @"C:\Temp\stub-rc.txt";
        try
        {
            File.AppendAllText(log, Environment.CommandLine + "\r\n" + "args: " + string.Join("|", args) + "\r\n");
        }
        catch (Exception) { }
        int rc = 0;
        try
        {
            if (File.Exists(rcFile)) { rc = int.Parse(File.ReadAllText(rcFile).Trim()); }
        }
        catch (Exception) { rc = 0; }
        return rc;
    }
}
