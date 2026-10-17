// Isolated fixture only. Never connects to a server or installs a service.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;

internal static class TestAgent
{
    private static int Main(string[] args)
    {
        string mode = File.ReadAllText("mode");
        if (args[0] == "child")
        {
            File.WriteAllText("child.pid", Process.GetCurrentProcess().Id.ToString());
            while (true) Thread.Sleep(1000);
        }
        Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) { e.Cancel = mode == "stubborn"; };
        File.WriteAllLines("args.txt", args);
        File.WriteAllText("cwd.txt", Directory.GetCurrentDirectory());
        File.WriteAllText("agent.pid", Process.GetCurrentProcess().Id.ToString());
        Process.Start(new ProcessStartInfo(Assembly.GetExecutingAssembly().Location, "child") {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Directory.GetCurrentDirectory()
        });
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.Write("Connected."); // no newline: the UI must not wait for one
        Console.Out.Flush();
        File.WriteAllText("ready", "1");
        if (mode == "exit") return 7;
        while (true) Thread.Sleep(1000);
    }
}
