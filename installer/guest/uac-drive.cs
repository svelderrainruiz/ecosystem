// Declined-administrator-prompt probe of the guest proof (ecosystem-control#64, SL-21a, issue #111). Compiled in the guest with the .NET
// Framework csc.exe (C# 5); no binary is committed. Usage: uac-drive.exe <installer.exe> <log file> [installer arguments].
// It starts the installer WITHOUT /S inside the window station and desktop it runs in itself, walks the pages with Next up to the
// elevation page (the only field it touches is the first radio button, "Local only (no forge)"), clicks Next there so that Elevate_Raise
// runs ExecShell "runas", and then records what a declined prompt leaves: the message box (class, owner, text), whether the process is
// still running 20 s later, the state after the box is closed, and the exit code after Cancel. Nothing is typed into a field; no secret.
// The log holds one line per observation and, at the end, RESULT key=value lines for the harness to parse.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class UacDrive
{
    private delegate bool EnumProc(IntPtr h, IntPtr lp);

    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc p, IntPtr lp);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumProc p, IntPtr lp);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr h, StringBuilder sb, int max);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] private static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] private static extern IntPtr GetDlgItem(IntPtr h, int id);
    [DllImport("user32.dll")] private static extern int GetDlgCtrlID(IntPtr h);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
    private static extern IntPtr SendMessageText(IntPtr h, uint msg, IntPtr w, StringBuilder l, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
    private static extern IntPtr SendMessageNumber(IntPtr h, uint msg, IntPtr w, IntPtr l, uint flags, uint timeout, out IntPtr result);

    private const uint WM_GETTEXT = 0x000D;
    private const uint WM_COMMAND = 0x0111;
    private const uint BM_GETCHECK = 0x00F0;
    private const uint BM_CLICK = 0x00F5;
    private const uint SMTO_ABORTIFHUNG = 0x0002;
    private const uint GW_OWNER = 4;
    private const int IDOK = 1;
    private const int IDCANCEL = 2;
    private const int IDBACK = 3;
    private const string ElevationText = "The next step needs administrator rights";

    private static StreamWriter log;
    private static Stopwatch clock = Stopwatch.StartNew();
    private static List<string> results = new List<string>();

    private static void Log(string s)
    {
        log.WriteLine(clock.Elapsed.TotalSeconds.ToString("0.0", CultureInfo.InvariantCulture) + " s  " + s);
        log.Flush();
    }

    private static void Result(string key, string value)
    {
        results.Add("RESULT " + key + "=" + value);
    }

    private static string Clip(string s, int n)
    {
        s = s.Replace("\r", " ").Replace("\n", " ");
        return s.Length <= n ? s : s.Substring(0, n) + "...";
    }

    private static string TextOf(IntPtr h)
    {
        StringBuilder sb = new StringBuilder(2048);
        IntPtr res;
        IntPtr ok = SendMessageText(h, WM_GETTEXT, (IntPtr)sb.Capacity, sb, SMTO_ABORTIFHUNG, 1500, out res);
        return ok == IntPtr.Zero ? "(no answer)" : sb.ToString();
    }

    private static string ClassOf(IntPtr h)
    {
        StringBuilder sb = new StringBuilder(256);
        GetClassName(h, sb, 256);
        return sb.ToString();
    }

    private static int GetCheck(IntPtr b)
    {
        IntPtr res;
        IntPtr ok = SendMessageNumber(b, BM_GETCHECK, IntPtr.Zero, IntPtr.Zero, SMTO_ABORTIFHUNG, 1500, out res);
        return ok == IntPtr.Zero ? -1 : res.ToInt32();
    }

    private static List<IntPtr> TopWindows(uint pid)
    {
        List<IntPtr> found = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr lp)
        {
            uint owner;
            GetWindowThreadProcessId(h, out owner);
            if (owner == pid) { found.Add(h); }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    private static List<IntPtr> Descendants(IntPtr parent)
    {
        List<IntPtr> found = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr h, IntPtr lp) { found.Add(h); return true; }, IntPtr.Zero);
        return found;
    }

    // The setup window has Back, Next and Cancel buttons; a message box has none of Back.
    private static IntPtr FindMain(List<IntPtr> tops)
    {
        foreach (IntPtr h in tops)
        {
            if (GetDlgItem(h, IDBACK) != IntPtr.Zero && GetDlgItem(h, IDCANCEL) != IntPtr.Zero) { return h; }
        }
        return IntPtr.Zero;
    }

    // A batch-logon window station never shows anything, so the box is found by its shape and its owner, never by IsWindowVisible.
    private static IntPtr FindBox(List<IntPtr> tops, IntPtr main)
    {
        foreach (IntPtr h in tops)
        {
            if (h == main || ClassOf(h) != "#32770") { continue; }
            bool owned = main != IntPtr.Zero && GetWindow(h, GW_OWNER) == main;
            bool shaped = GetDlgItem(h, IDBACK) == IntPtr.Zero && GetDlgItem(h, IDOK) != IntPtr.Zero;
            if (owned || shaped) { return h; }
        }
        return IntPtr.Zero;
    }

    private static string Describe(IntPtr h)
    {
        return string.Format("hwnd=0x{0:X} class={1} visible={2} enabled={3} owner=0x{4:X} title=[{5}]",
            h.ToInt64(), ClassOf(h), IsWindowVisible(h), IsWindowEnabled(h), GetWindow(h, GW_OWNER).ToInt64(), Clip(TextOf(h), 120));
    }

    private static void ClickBox(IntPtr box)
    {
        IntPtr b = GetDlgItem(box, IDOK);
        if (b == IntPtr.Zero)
        {
            foreach (IntPtr c in Descendants(box))
            {
                if (ClassOf(c) == "Button") { b = c; break; }
            }
        }
        if (b != IntPtr.Zero) { PostMessage(b, BM_CLICK, IntPtr.Zero, IntPtr.Zero); }
        else { PostMessage(box, WM_COMMAND, (IntPtr)IDOK, IntPtr.Zero); }
    }

    private static string BoxText(IntPtr box)
    {
        List<string> parts = new List<string>();
        foreach (IntPtr c in Descendants(box))
        {
            if (ClassOf(c) == "Static")
            {
                string s = TextOf(c);
                if (s.Length > 0) { parts.Add(s); }
            }
        }
        return string.Join(" | ", parts.ToArray());
    }

    private static string PageSignature(IntPtr main)
    {
        List<string> parts = new List<string>();
        foreach (IntPtr c in Descendants(main))
        {
            string cls = ClassOf(c);
            if (cls == "Static" || cls == "Button" || cls == "Edit" || cls == "ComboBox")
            {
                string s = TextOf(c);
                if (s.Length > 0) { parts.Add(s); }
            }
        }
        return string.Join(" | ", parts.ToArray());
    }

    private static IntPtr FindButton(IntPtr main, string text)
    {
        foreach (IntPtr c in Descendants(main))
        {
            if (ClassOf(c) == "Button" && TextOf(c) == text) { return c; }
        }
        return IntPtr.Zero;
    }

    private static void Click(IntPtr window, int id)
    {
        IntPtr b = GetDlgItem(window, id);
        if (b != IntPtr.Zero) { PostMessage(b, BM_CLICK, IntPtr.Zero, IntPtr.Zero); }
    }

    private static string Snapshot(uint pid)
    {
        List<IntPtr> tops = TopWindows(pid);
        IntPtr main = FindMain(tops);
        return main == IntPtr.Zero ? "" : PageSignature(main);
    }

    private static void ListWindows(uint pid, string why)
    {
        Log("window list (" + why + "):");
        IntPtr main = FindMain(TopWindows(pid));
        foreach (IntPtr h in TopWindows(pid))
        {
            Log("  " + Describe(h) + (h == main ? " [setup window]" : ""));
            if (h == main) { continue; }
            int n = 0;
            foreach (IntPtr c in Descendants(h))
            {
                if (n++ >= 12) { break; }
                Log(string.Format("    child id={0} class={1} visible={2} text=[{3}]", GetDlgCtrlID(c), ClassOf(c), IsWindowVisible(c), Clip(TextOf(c), 160)));
            }
        }
    }

    public static int Main(string[] args)
    {
        if (args.Length < 2) { return 2; }
        log = new StreamWriter(args[1], false, Encoding.ASCII);
        string installerArgs = args.Length > 2 ? string.Join(" ", args, 2, args.Length - 2) : "";
        Process p;
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(args[0], installerArgs);
            psi.UseShellExecute = false;
            p = Process.Start(psi);
        }
        catch (Exception e)
        {
            Log("START FAILED: " + e.GetType().Name);
            Result("started", "False");
            Finish();
            return 0;
        }
        uint pid = (uint)p.Id;
        Log("started the installer, pid " + pid + ", arguments: " + Clip(installerArgs.Replace(args.Length > 2 ? args[2].Substring(Math.Min(args[2].Length, 8)) : "", "..."), 60));
        Result("started", "True");

        // phase 1: Next through the pages up to the elevation page, and Next on it
        string lastSig = "";
        bool clickedElevation = false;
        int boxesBefore = 0;
        while (!p.HasExited && clock.Elapsed.TotalSeconds < 70 && !clickedElevation && boxesBefore < 6)
        {
            List<IntPtr> tops = TopWindows(pid);
            IntPtr main = FindMain(tops);
            IntPtr box = FindBox(tops, main);
            if (box != IntPtr.Zero)
            {
                boxesBefore++;
                Log("message box before the elevation page: " + Describe(box) + " text=[" + Clip(BoxText(box), 200) + "]");
                ClickBox(box);
                Thread.Sleep(600);
                continue;
            }
            if (main == IntPtr.Zero) { Thread.Sleep(300); continue; }
            string sig = PageSignature(main);
            if (sig != lastSig) { Log("page: " + Clip(sig, 260)); lastSig = sig; }
            bool isElevation = sig.IndexOf(ElevationText, StringComparison.Ordinal) >= 0;
            IntPtr radio = FindButton(main, "Local only (no forge)");
            if (radio != IntPtr.Zero && GetCheck(radio) != 1)
            {
                PostMessage(radio, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
                Log("selected the radio button: Local only (no forge)");
                Thread.Sleep(400);
            }
            if (isElevation)
            {
                Log("ELEVATION PAGE reached; clicking Next");
                ListWindows(pid, "baseline before Next on the elevation page");
                Result("elevation_page", "True");
                clickedElevation = true;
            }
            Click(main, IDOK);
            double until = clock.Elapsed.TotalSeconds + 6;
            while (!isElevation && clock.Elapsed.TotalSeconds < until && !p.HasExited)
            {
                Thread.Sleep(250);
                List<IntPtr> t2 = TopWindows(pid);
                if (FindBox(t2, FindMain(t2)) != IntPtr.Zero) { break; }
                string now = Snapshot(pid);
                if (now.Length > 0 && now != lastSig) { break; }
            }
        }
        if (!clickedElevation)
        {
            Log("the elevation page was not reached (alive=" + !p.HasExited + ")");
            Result("elevation_page", "False");
            ListWindows(pid, "stuck");
            Finish(p);
            return 0;
        }

        // phase 2: the declined prompt leaves a message box
        double clickAt = clock.Elapsed.TotalSeconds;
        IntPtr declinedBox = IntPtr.Zero;
        while (!p.HasExited && clock.Elapsed.TotalSeconds < clickAt + 30)
        {
            List<IntPtr> tops = TopWindows(pid);
            declinedBox = FindBox(tops, FindMain(tops));
            if (declinedBox != IntPtr.Zero) { break; }
            Thread.Sleep(250);
        }
        if (declinedBox == IntPtr.Zero)
        {
            List<IntPtr> tops = TopWindows(pid);
            IntPtr main = FindMain(tops);
            Log("NO message box within 30 s of Next on the elevation page; alive=" + !p.HasExited + "; the installer answers window messages: " + (main != IntPtr.Zero && TextOf(main) != "(no answer)"));
            Result("box", "none");
            Result("alive_after_click", (!p.HasExited).ToString());
            ListWindows(pid, "no box");
            Finish(p);
            return 0;
        }
        double boxAt = clock.Elapsed.TotalSeconds;
        string text = BoxText(declinedBox);
        Log("MESSAGE BOX after " + (boxAt - clickAt).ToString("0.0", CultureInfo.InvariantCulture) + " s: " + Describe(declinedBox) + " text=[" + Clip(text, 300) + "]");
        ListWindows(pid, "box open");
        Result("box", "yes");
        Result("box_class", ClassOf(declinedBox));
        Result("box_owner_is_setup_window", (GetWindow(declinedBox, GW_OWNER) == FindMain(TopWindows(pid))).ToString());
        Result("box_text", Clip(text, 300));
        while (!p.HasExited && clock.Elapsed.TotalSeconds < boxAt + 20)
        {
            Thread.Sleep(5000);
            Log("alive=" + !p.HasExited + " box still open=" + (FindBox(TopWindows(pid), FindMain(TopWindows(pid))) != IntPtr.Zero));
        }
        bool alive20 = !p.HasExited;
        Log("20 s after the box appeared: alive=" + alive20);
        Result("alive_after_20s", alive20.ToString());
        if (!alive20) { Finish(p); return 0; }

        // phase 3: close the box, see that the page stays, then Cancel and read the exit code
        ClickBox(declinedBox);
        double closeAt = clock.Elapsed.TotalSeconds;
        while (!p.HasExited && clock.Elapsed.TotalSeconds < closeAt + 6)
        {
            Thread.Sleep(250);
            List<IntPtr> tops = TopWindows(pid);
            if (FindBox(tops, FindMain(tops)) == IntPtr.Zero) { break; }
        }
        List<IntPtr> after = TopWindows(pid);
        bool boxGone = FindBox(after, FindMain(after)) == IntPtr.Zero;
        string pageAfter = p.HasExited ? "" : Snapshot(pid);
        bool stays = pageAfter.IndexOf(ElevationText, StringComparison.Ordinal) >= 0;
        Log("after closing the box: alive=" + !p.HasExited + " box gone=" + boxGone + " elevation page still shown=" + stays);
        Result("alive_after_close", (!p.HasExited).ToString());
        Result("box_gone_after_close", boxGone.ToString());
        Result("elevation_page_kept", stays.ToString());
        if (!p.HasExited)
        {
            IntPtr main = FindMain(after);
            Click(main, IDCANCEL);
            Log("clicked Cancel");
            double cancelAt = clock.Elapsed.TotalSeconds;
            while (!p.HasExited && clock.Elapsed.TotalSeconds < cancelAt + 15)
            {
                Thread.Sleep(300);
                List<IntPtr> tops = TopWindows(pid);
                IntPtr confirm = FindBox(tops, FindMain(tops));
                if (confirm != IntPtr.Zero)
                {
                    Log("a message box after Cancel: " + Describe(confirm) + " text=[" + Clip(BoxText(confirm), 200) + "]");
                    Result("box_after_cancel", Clip(BoxText(confirm), 200));
                    ClickBox(confirm);
                }
            }
        }
        Finish(p);
        return 0;
    }

    private static void Finish() { Finish(null); }

    private static void Finish(Process p)
    {
        if (p != null)
        {
            if (!p.HasExited && !p.WaitForExit(2000)) { p.Kill(); Result("exit_code", "killed (still running at the end)"); }
            else { Result("exit_code", p.ExitCode.ToString()); }
        }
        foreach (string r in results) { log.WriteLine(r); }
        log.Flush();
        log.Close();
    }
}
