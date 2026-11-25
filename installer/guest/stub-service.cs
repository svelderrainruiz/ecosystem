// Harmless test service for the guest proof (ecosystem-control#64): never a real runner, no network, no forge contact.
// Compiled in the guest with the .NET Framework csc.exe, installed as <folder>\program\runner.exe by installer.guest.service_proof.
// On start it writes <folder>\probe.txt (its own identity and whether it can read <folder>\config.toml); it exits 3 s after
// start when program\crash.txt exists (the injected failed health check).
using System;
using System.IO;
using System.Security.Principal;
using System.ServiceProcess;
using System.Threading;

public class StubService : ServiceBase
{
    private Timer crash;

    public static void Main()
    {
        ServiceBase.Run(new StubService());
    }

    protected override void OnStart(string[] args)
    {
        string program = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
        string folder = Path.GetDirectoryName(program);
        try
        {
            string read;
            try { File.ReadAllText(Path.Combine(folder, "config.toml")); read = "read=ok"; }
            catch (Exception e) { read = "read=" + e.GetType().Name; }
            string text = WindowsIdentity.GetCurrent().Name + "\r\n" + read + "\r\n";
            File.WriteAllText(Path.Combine(folder, "probe.txt"), text);
        }
        catch (Exception) { }
        try
        {
            // grant probe only: a folder the probe makes world-writable, so a service with no write right in its own folder can still report
            string alt = @"C:\g5\probe-out";
            if (Directory.Exists(alt))
            {
                string r2;
                try { File.ReadAllText(Path.Combine(Path.GetDirectoryName(program), "config.toml")); r2 = "read=ok"; }
                catch (Exception e) { r2 = "read=" + e.GetType().Name; }
                File.WriteAllText(Path.Combine(alt, "probe.txt"), WindowsIdentity.GetCurrent().Name + "\r\n" + r2 + "\r\n");
            }
        }
        catch (Exception) { }
        if (File.Exists(Path.Combine(program, "crash.txt")))
        {
            crash = new Timer(delegate (object o) { Environment.Exit(1); }, null, 3000, Timeout.Infinite);
        }
    }
}
