using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using ZOOMsoft.Fernwartung;

internal static class Pruefungen
{
    private const string Settings = "MeshName=Test\nMeshType=2\nMeshID=0x1234\nServerID=ABCDEF\nMeshServer=wss://assist.example.invalid/agent.ashx\n";
    private static string fixture, root;
    private static int passed;

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--vorlage")
        {
            File.WriteAllBytes(args[1], Template(Settings));
            return 0;
        }
        if (args.Length == 3 && args[0] == "--elternprozess")
        {
            using (var session = new Sitzung())
            {
                session.Start(args[1], args[2], Sitzung.Argumente);
                File.WriteAllText(Path.Combine(args[2], "parent.ready"), "1");
                while (true) Thread.Sleep(1000);
            }
        }
        fixture = args[0]; root = args[1];
        try
        {
            Run("Verbindungseinstellungen und Update-Sperre", Config);
            Run("Ablehnung ungültiger oder unsicherer Einstellungen", RejectConfig);
            Run("Windows-Vorlage und Big-Endian-Konfiguration", EmbeddedConfig);
            Run("Verbindungsstatus ohne optionale Debugmeldung", States);
            Run("Geteilte Terminalsequenzen und Wiederverbindung", Terminal);
            Run("Windows-Strukturgrößen", Abi);
            Run("Status ohne Zeilenende und Aufräumen der Prozessgruppe", Lifecycle);
            Run("Abbruch eines nicht reagierenden Agenten", Stubborn);
            Run("Unerwartetes Agent-Ende und verbleibender Kindprozess", AgentExit);
            Run("Task-Manager-Ende des Elternprozesses", ParentExit);
            Run("Fehlgeschlagener Prozessstart", FailedStart);
            Run("Fenster und ZOOMsoft-Logo rendern", Window);
            Console.WriteLine(passed + " Prüfungen bestanden.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }

    private static void Run(string name, Action test)
    {
        test(); passed++; Console.WriteLine("OK: " + name);
    }
    private static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }
    private static void Wait(Func<bool> condition, int milliseconds = 6000)
    {
        var clock = Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < milliseconds) { if (condition()) return; Thread.Sleep(20); }
        throw new Exception("Zeitüberschreitung in der Prozessprüfung.");
    }
    private static bool Alive(int pid)
    {
        try { using (var process = Process.GetProcessById(pid)) return !process.HasExited; }
        catch (ArgumentException) { return false; }
    }
    private static string Data(string mode)
    {
        string path = Path.Combine(root, "Daten ü mit Leerzeichen " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        File.WriteAllText(Path.Combine(path, "mode"), mode);
        return path;
    }
    private static void Ready(string path)
    {
        Wait(() => File.Exists(Path.Combine(path, "ready")) && File.Exists(Path.Combine(path, "child.pid")));
    }
    private static void Stopped(string path)
    {
        foreach (string name in new[] { "agent.pid", "child.pid" })
        {
            string file = Path.Combine(path, name);
            if (File.Exists(file)) { int pid = Int32.Parse(File.ReadAllText(file)); Wait(() => !Alive(pid)); }
        }
    }

    private static void Config()
    {
        string filtered = Konfiguration.Filtern(Settings + "disableUpdate=0\nAgentCapabilities=0\nStartupType=1\ncontrolChannelDebug=1\nmeshServiceName=Other\nnoUpdateCoreModule=1\n");
        Check(filtered.Contains("ServerID=ABCDEF\n") && filtered.Contains("MeshID=0x1234\n"), "Serverbindung geändert");
        Check(filtered.Contains("disableUpdate=1\n"), "Update-Sperre fehlt");
        foreach (string excluded in new[] { "AgentCapabilities", "StartupType", "controlChannelDebug", "Other", "noUpdateCoreModule" })
            Check(!filtered.Contains(excluded), "Nicht erlaubte Einstellung: " + excluded);
        Check(Konfiguration.Kennung(Settings) == Konfiguration.Kennung(filtered), "Instabile Gerätezuordnung");
        Check(Konfiguration.Kennung(Settings.Replace("ABCDEF", "123456")) != Konfiguration.Kennung(Settings), "Fremder Server teilt Daten");
        Check(Sitzung.Argumente.StartsWith("connect -nocertstore "), "Temporärer Modus oder eigene Identität fehlt");
    }
    private static void RejectConfig()
    {
        foreach (string text in new[] { Settings.Replace("ServerID=ABCDEF\n", ""), Settings + "MeshServer=wss://other.invalid/\n",
            Settings.Replace("wss://", "ws://"), Settings.Replace("wss://", "wss://user:pass@"), Settings.Replace("MeshType=2", "MeshType=1"), Settings + "\0" })
        {
            bool rejected = false;
            try { Konfiguration.Filtern(text); } catch (InvalidDataException) { rejected = true; }
            Check(rejected, "Unsichere Konfiguration akzeptiert");
        }
    }
    internal static byte[] Template(string settings)
    {
        var pe = new byte[512]; pe[0] = (byte)'M'; pe[1] = (byte)'Z'; pe[0x3C] = 0x80;
        pe[0x80] = (byte)'P'; pe[0x81] = (byte)'E'; pe[0x84] = 0x64; pe[0x85] = 0x86;
        pe[0x98] = 0x0B; pe[0x99] = 0x02;
        byte[] features = Encoding.ASCII.GetBytes("configUsesCWD\0disableUpdate\0MeshServer\0connect\0-nocertstore\0");
        Buffer.BlockCopy(features, 0, pe, 400, features.Length);
        byte[] policy = Encoding.UTF8.GetBytes(settings);
        using (var result = new MemoryStream())
        {
            result.Write(pe, 0, pe.Length); result.Write(policy, 0, policy.Length);
            uint length = (uint)policy.Length;
            foreach (int shift in new[] { 24, 16, 8, 0 }) result.WriteByte((byte)(length >> shift));
            byte[] marker = { 0xB9, 0x96, 0x01, 0x58, 0x80, 0x54, 0x4A, 0x19, 0xB7, 0xF7, 0xE9, 0xBE, 0x44, 0x91, 0x4C, 0x19 };
            result.Write(marker, 0, marker.Length); return result.ToArray();
        }
    }
    private static void EmbeddedConfig()
    {
        byte[] pe = Template(Settings);
        Check(Konfiguration.AgentPruefen(pe) == 0x8664, "Falsche Agent-Architektur");
        Check(Konfiguration.EingebetteteEinstellungen(pe) == Settings, "Eingebettete Konfiguration beschädigt");
        pe[pe.Length - 20] = 0x7F;
        bool rejected = false;
        try { Konfiguration.EingebetteteEinstellungen(pe); } catch (InvalidDataException) { rejected = true; }
        Check(rejected, "Ungültige Konfigurationslänge akzeptiert");
        pe = Template(Settings); pe[0x98 + 112 + 14 * 8] = 1;
        rejected = false;
        try { Konfiguration.AgentPruefen(pe); } catch (InvalidDataException) { rejected = true; }
        Check(rejected, "Assistant statt nativem Agent akzeptiert");
    }
    private static void States()
    {
        Check(StatusLeser.Erkennen("Connected.") == Verbindungsstatus.Verbunden, "Verbindung ohne Debugmeldung fehlt");
        Check(StatusLeser.Erkennen("Connecting to: wss://example.invalidConnected.") == Verbindungsstatus.Verbunden, "Verkettete Ausgabe fehlt");
        Check(StatusLeser.Erkennen("Not Connected.") == Verbindungsstatus.Unveraendert, "Falscher Verbindungsstatus");
        Check(StatusLeser.Erkennen("Invalid server signature") == Verbindungsstatus.Fehler, "Zertifikatsfehler fehlt");
    }
    private static void Terminal()
    {
        var states = new List<Verbindungsstatus>();
        var parser = new StatusLeser(states.Add);
        foreach (string text in new[] { "\x1B[?2", "5l\x1B[32mCon", "nected.", "\x1B[0m\r\nControl Channel Dis", "connected [4]...\r\n", "\x1B]0;title", "\aConnected." }) parser.Lesen(text);
        Check(states.SequenceEqual(new[] { Verbindungsstatus.Verbunden, Verbindungsstatus.Verbindet, Verbindungsstatus.Verbunden }), "Terminaldaten verändern den Verbindungsstatus");
    }
    private static void Abi()
    {
        Check(Marshal.SizeOf(typeof(Native.STARTUPINFOEX)) == (IntPtr.Size == 8 ? 112 : 72), "STARTUPINFOEX falsch");
        Check(Marshal.SizeOf(typeof(Native.JOBOBJECT_EXTENDED_LIMIT_INFORMATION)) == (IntPtr.Size == 8 ? 144 : 112), "Job-Struktur falsch");
    }
    private static void Lifecycle()
    {
        string path = Data("normal");
        using (var unrelated = Process.Start(new ProcessStartInfo(fixture, "child") {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Data("normal") }))
        {
            try
            {
                var connected = new ManualResetEvent(false);
                using (var session = new Sitzung())
                {
                    var parser = new StatusLeser(state => { if (state == Verbindungsstatus.Verbunden) connected.Set(); });
                    session.Ausgabe += parser.Lesen;
                    session.Start(fixture, path, Sitzung.Argumente);
                    Ready(path);
                    Check(connected.WaitOne(2500), "Kurze Statusausgabe wartet auf weitere Daten");
                    Check(!session.Beendet, "Agent ist vor Statusanzeige beendet");
                    Check(File.ReadAllText(Path.Combine(path, "cwd.txt")) == path, "Falsches Arbeitsverzeichnis");
                    Check(File.ReadAllLines(Path.Combine(path, "args.txt")).SequenceEqual(Sitzung.Argumente.Split(' ')), "Falsche Startargumente");
                    Check(!File.Exists(Path.Combine(path, "sitzung.log")), "Sitzungsprotokoll erzeugt");
                }
                Stopped(path);
                Check(!unrelated.HasExited, "Fremder Prozess wurde beendet");
            }
            finally { if (!unrelated.HasExited) { unrelated.Kill(); unrelated.WaitForExit(); } }
        }
    }
    private static void Stubborn()
    {
        string path = Data("stubborn");
        var session = new Sitzung();
        try { session.Start(fixture, path, Sitzung.Argumente); Ready(path); }
        finally
        {
            var timer = Stopwatch.StartNew(); session.Dispose();
            Check(timer.ElapsedMilliseconds < 5000, "Sitzungsende ist blockiert");
        }
        Stopped(path);
    }
    private static void AgentExit()
    {
        string path = Data("exit");
        using (var session = new Sitzung()) { session.Start(fixture, path, Sitzung.Argumente); Ready(path); Wait(() => session.Beendet); }
        Stopped(path);
    }
    private static void ParentExit()
    {
        string path = Data("normal");
        var info = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
            "--elternprozess \"" + fixture + "\" \"" + path + "\"") { UseShellExecute = false, CreateNoWindow = true };
        using (var parent = Process.Start(info))
        {
            try { Ready(path); parent.Kill(); parent.WaitForExit(3000); Stopped(path); }
            finally { if (!parent.HasExited) { parent.Kill(); parent.WaitForExit(); } }
        }
    }
    private static void FailedStart()
    {
        bool rejected = false;
        using (var session = new Sitzung())
            try { session.Start(Path.Combine(root, "missing.exe"), Data("normal"), Sitzung.Argumente); }
            catch (System.ComponentModel.Win32Exception) { rejected = true; }
        Check(rejected, "Fehlgeschlagener Start bleibt unbemerkt");
    }
    private static void Window()
    {
        Application.EnableVisualStyles();
        using (var form = new Fernwartungsfenster(Konfiguration.Filtern(Settings), Konfiguration.Kennung(Settings)))
        using (var bitmap = new Bitmap(form.Width, form.Height))
        {
            Check(form.Text == Konfiguration.Produkt, "Falscher Fenstertitel");
            form.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height));
            bitmap.Save(Path.Combine(root, "Fenstervorschau.png"), ImageFormat.Png);
        }
    }
}
