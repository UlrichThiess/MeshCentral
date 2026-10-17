// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Ferwartung | ZOOMsoft GmbH")]
[assembly: AssemblyProduct("Ferwartung | ZOOMsoft GmbH")]
[assembly: AssemblyCompany("ZOOMsoft GmbH")]
[assembly: AssemblyCopyright("Copyright © 2026 ZOOMsoft GmbH. Apache-2.0.")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8")]

namespace ZOOMsoft.Fernwartung
{
    internal static class Ressourcen
    {
        internal static byte[] Lesen(string name)
        {
            using (Stream source = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
            {
                if (source == null) throw new InvalidDataException("In der App fehlt " + name + ".");
                using (var data = new MemoryStream()) { source.CopyTo(data); return data.ToArray(); }
            }
        }
    }

    internal static class Programm
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                if (Environment.OSVersion.Version.Major < 10 || Environment.OSVersion.Version.Build < 17763)
                    throw new InvalidOperationException("Diese App benötigt Windows 10 ab Version 1809 oder Windows 11.");
                string config = Konfiguration.Filtern(Encoding.UTF8.GetString(Ressourcen.Lesen("meshagent.msh")));
                string identity = Konfiguration.Kennung(config);
                string sid;
                using (var user = WindowsIdentity.GetCurrent()) sid = user.User.Value;
                using (var mutex = new Mutex(false, @"Local\ZOOMsoftFernwartung-" + sid + "-" + identity))
                {
                    bool acquired;
                    try { acquired = mutex.WaitOne(0); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired)
                    {
                        IntPtr previous = FensterNative.FindWindow(null, Konfiguration.Produkt);
                        if (previous != IntPtr.Zero)
                        {
                            FensterNative.ShowWindow(previous, 9);
                            FensterNative.SetForegroundWindow(previous);
                        }
                        return;
                    }
                    try
                    {
                        using (var form = new Fernwartungsfenster(config, identity)) Application.Run(form);
                    }
                    finally { mutex.ReleaseMutex(); }
                }
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, Konfiguration.Produkt, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
    }

    public sealed class Fernwartungsfenster : Form
    {
        private readonly Label status, screenStatus, inputStatus;
        private readonly Button retry;
        private readonly System.Windows.Forms.Timer timer;
        private readonly string config, identity;
        private readonly Image logo;
        private Sitzung session;
        private FileStream dataLock;
        private string directory, problem;
        private bool closing;
        private readonly bool administrator;

        public Fernwartungsfenster(string config, string identity)
        {
            this.config = config;
            this.identity = identity;
            using (var user = WindowsIdentity.GetCurrent())
                administrator = new WindowsPrincipal(user).IsInRole(WindowsBuiltInRole.Administrator);
            AutoScaleDimensions = new SizeF(96, 96);
            AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 13, FontStyle.Regular, GraphicsUnit.Pixel);
            ClientSize = new Size(600, 420);
            Text = Konfiguration.Produkt;
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = SystemColors.Window;
            ForeColor = SystemColors.WindowText;
            Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            using (var image = new MemoryStream(Ressourcen.Lesen("ZOOMsoft.png")))
            using (var original = Image.FromStream(image)) logo = new Bitmap(original);
            var picture = new PictureBox { Image = logo, SizeMode = PictureBoxSizeMode.Zoom,
                Location = new Point(28, 32), Size = new Size(90, 90), TabStop = false };
            Controls.Add(picture);
            Label title = Label(Konfiguration.Produkt, 140, 39, 438, 35);
            title.Font = new Font(Font.FontFamily, 21, FontStyle.Bold, GraphicsUnit.Pixel);
            Label("Die Fernwartung ist aktiv, solange dieses Fenster geöffnet ist.\nSchließen beendet die Verbindung.", 140, 77, 430, 44);
            status = Label("Verbindung wird aufgebaut …", 28, 140, 540, 30);
            status.Font = new Font(Font.FontFamily, 17, FontStyle.Bold, GraphicsUnit.Pixel);
            Label("Rechner: " + Environment.MachineName, 28, 176, 540, 22);
            screenStatus = Label("Bildschirmaufnahme: bereit", 28, 227, 544, 25);
            inputStatus = Label("Bedienung: Benutzerrechte", 28, 271, 544, 25);
            Label hint = Label("Für Administratordialoge die App als Administrator starten.", 28, 312, 544, 42);
            hint.ForeColor = SystemColors.GrayText;
            retry = Button("Erneut verbinden", 28, 364, 180);
            retry.Enabled = false;
            retry.Click += delegate { Start(); };
            var quit = Button("Fernwartung beenden", 352, 364, 220);
            quit.Click += delegate { Close(); };
            CancelButton = quit;
            timer = new System.Windows.Forms.Timer { Interval = 250 };
            timer.Tick += delegate { Tick(); };
            Shown += delegate { BeginInvoke(new Action(Start)); timer.Start(); };
            UpdatePermissions();
        }

        private Label Label(string text, int x, int y, int width, int height)
        {
            var label = new Label { Text = text, Location = new Point(x, y), Size = new Size(width, height),
                AutoSize = false, UseMnemonic = false, TextAlign = ContentAlignment.MiddleLeft };
            Controls.Add(label);
            return label;
        }

        private Button Button(string text, int x, int y, int width)
        {
            var button = new Button { Text = text, Location = new Point(x, y), Size = new Size(width, 32),
                UseVisualStyleBackColor = true };
            Controls.Add(button);
            return button;
        }

        private void Prepare()
        {
            if (dataLock != null) return;
            directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ZOOMsoft", "Fernwartung-Windows", identity);
            Directory.CreateDirectory(directory);
            var access = new DirectorySecurity();
            access.SetAccessRuleProtection(true, false);
            SecurityIdentifier currentUser;
            using (var user = WindowsIdentity.GetCurrent()) currentUser = user.User;
            foreach (SecurityIdentifier sid in new[] { currentUser,
                new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
                new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null) })
                access.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None, AccessControlType.Allow));
            Directory.SetAccessControl(directory, access);
            dataLock = new FileStream(Path.Combine(directory, "sitzung.lock"), FileMode.OpenOrCreate,
                FileAccess.ReadWrite, FileShare.None);
            try
            {
                byte[] engine = Ressourcen.Lesen("meshagent.exe");
                string target = Path.Combine(directory, "meshagent.exe");
                if (!File.Exists(target) || Konfiguration.Hash(File.ReadAllBytes(target)) != Konfiguration.Hash(engine))
                    File.WriteAllBytes(target, engine);
                File.WriteAllText(Path.Combine(directory, "meshagent.msh"), config, new UTF8Encoding(false));
            }
            catch { dataLock.Dispose(); dataLock = null; throw; }
        }

        private void Start()
        {
            if (session != null || closing) return;
            problem = null;
            retry.Enabled = false;
            status.Text = "Verbindung wird aufgebaut …";
            status.ForeColor = SystemColors.GrayText;
            try
            {
                Prepare();
                var current = new Sitzung();
                session = current;
                var parser = new StatusLeser(delegate(Verbindungsstatus state)
                {
                    Post(delegate { if (session == current && !closing) Status(state); });
                });
                current.Ausgabe += parser.Lesen;
                current.Start(Path.Combine(directory, "meshagent.exe"), directory, Sitzung.Argumente);
            }
            catch (Exception error)
            {
                if (session != null) { session.Dispose(); session = null; }
                var windowsError = error as Win32Exception;
                Failure(windowsError != null ? "Start fehlgeschlagen (Windows-Fehler " + windowsError.NativeErrorCode + ")." :
                    error is UnauthorizedAccessException ? "Zugriff auf die Verbindungsdaten nicht möglich." :
                    "Start fehlgeschlagen. Bitte erneut verbinden.");
            }
        }

        private void Status(Verbindungsstatus state)
        {
            if (state == Verbindungsstatus.Verbunden)
            {
                problem = null;
                status.Text = "Mit ZOOMsoft verbunden";
                status.ForeColor = Color.FromArgb(25, 130, 70);
            }
            else if (state == Verbindungsstatus.Verbindet)
            {
                status.Text = "Verbindung wird aufgebaut …";
                status.ForeColor = Color.FromArgb(180, 105, 0);
            }
            else if (state == Verbindungsstatus.Fehler)
            {
                problem = "Server konnte nicht bestätigt werden";
                Failure(problem);
            }
        }

        private void Failure(string text)
        {
            status.Text = text;
            status.ForeColor = Color.Firebrick;
            retry.Enabled = session == null;
        }

        private void Post(Action action)
        {
            try { if (!IsDisposed && IsHandleCreated) BeginInvoke(action); }
            catch (InvalidOperationException) { }
        }

        private void Tick()
        {
            UpdatePermissions();
            if (session == null || !session.Beendet) return;
            session.Dispose();
            session = null;
            Failure(problem ?? "Die Verbindung wurde beendet. Sie können sie erneut aufbauen.");
        }

        private void UpdatePermissions()
        {
            IntPtr desktop = FensterNative.OpenInputDesktop(0, false, 0x0001); // DESKTOP_READOBJECTS
            screenStatus.Text = desktop == IntPtr.Zero ? "Bildschirmaufnahme: Desktop derzeit geschützt" : "Bildschirmaufnahme: bereit";
            screenStatus.ForeColor = desktop == IntPtr.Zero ? Color.FromArgb(180, 105, 0) : SystemColors.GrayText;
            if (desktop != IntPtr.Zero) FensterNative.CloseDesktop(desktop);
            inputStatus.Text = administrator ? "Bedienung: Administratorrechte" : "Bedienung: Benutzerrechte";
            inputStatus.ForeColor = SystemColors.GrayText;
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            closing = true;
            timer.Stop();
            status.Text = "Verbindung wird beendet …";
            retry.Enabled = false;
            if (session != null) { session.Dispose(); session = null; }
            if (dataLock != null) { dataLock.Dispose(); dataLock = null; }
            base.OnFormClosing(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                if (session != null) { session.Dispose(); session = null; }
                if (dataLock != null) { dataLock.Dispose(); dataLock = null; }
                timer.Dispose();
                logo.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    internal static class FensterNative
    {
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] internal static extern IntPtr FindWindow(string className, string title);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool ShowWindow(IntPtr window, int command);
        [DllImport("user32.dll")] internal static extern IntPtr OpenInputDesktop(uint flags, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint access);
        [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool CloseDesktop(IntPtr desktop);
    }
}
