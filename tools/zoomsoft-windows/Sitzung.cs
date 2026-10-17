// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace ZOOMsoft.Fernwartung
{
    // Only the GUI owns the unnamed job handle. Windows kills its agent and
    // descendants when the GUI exits, including TerminateProcess/Task Manager.
    // JOB_LIST attaches the child atomically during CreateProcess; it cannot
    // escape during the gap between creation and AssignProcessToJobObject.
    public sealed class Sitzung : IDisposable
    {
        private IntPtr job, process, console, input;
        private Thread reader;
        private int disposed;
        public uint ProzessId { get; private set; }
        public event Action<string> Ausgabe;

        public static string Argumente
        {
            get { return "connect -nocertstore --configUsesCWD=1 --disableUpdate=1"; }
        }

        public bool Beendet
        {
            get { return process == IntPtr.Zero || Native.WaitForSingleObject(process, 0) == 0; }
        }

        public void Start(string executable, string directory, string arguments)
        {
            if (job != IntPtr.Zero || disposed != 0) throw new InvalidOperationException("Sitzung bereits verwendet.");
            IntPtr inRead = IntPtr.Zero, outRead = IntPtr.Zero, outWrite = IntPtr.Zero;
            IntPtr attributes = IntPtr.Zero, jobList = IntPtr.Zero;
            bool initialized = false;
            Native.PROCESS_INFORMATION info = new Native.PROCESS_INFORMATION();
            try
            {
                job = Native.CreateJobObject(IntPtr.Zero, null);
                Check(job != IntPtr.Zero);
                var limits = new Native.JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
                limits.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE, no breakaway
                Check(Native.SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)));
                Check(Native.CreatePipe(out inRead, out input, IntPtr.Zero, 0));
                Check(Native.CreatePipe(out outRead, out outWrite, IntPtr.Zero, 0));
                int hr = Native.CreatePseudoConsole(new Native.COORD(512, 40), inRead, outWrite, 0, out console);
                if (hr < 0) Marshal.ThrowExceptionForHR(hr);

                // Drain on a dedicated thread throughout shutdown. Closing a
                // pseudoconsole can emit one final frame and wait for a reader.
                IntPtr readHandle = outRead;
                reader = new Thread(delegate() { ReadOutput(readHandle); });
                reader.IsBackground = true;
                reader.Name = "ZOOMsoft Verbindungsstatus";
                reader.Start();
                outRead = IntPtr.Zero; // reader owns this handle

                IntPtr bytes = IntPtr.Zero;
                Native.InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref bytes);
                if (bytes == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
                attributes = Marshal.AllocHGlobal(bytes);
                Check(Native.InitializeProcThreadAttributeList(attributes, 2, 0, ref bytes));
                initialized = true;
                Check(Native.UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x00020016), console,
                    new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero));
                jobList = Marshal.AllocHGlobal(IntPtr.Size);
                Marshal.WriteIntPtr(jobList, job);
                Check(Native.UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x0002000D), jobList,
                    new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero));
                var startup = new Native.STARTUPINFOEX();
                startup.StartupInfo.cb = Marshal.SizeOf(startup);
                // Explicit null standard handles prevent Windows duplicating
                // a redirected parent's pipes instead of using the ConPTY.
                startup.StartupInfo.dwFlags = 0x00000100; // STARTF_USESTDHANDLES
                startup.lpAttributeList = attributes;
                var command = new StringBuilder("\"" + executable + "\" " + arguments);
                Check(Native.CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, false,
                    0x00080000 | 0x00000004, IntPtr.Zero, directory, ref startup, out info));
                process = info.hProcess;
                info.hProcess = IntPtr.Zero;
                ProzessId = info.dwProcessId;
                if (Native.ResumeThread(info.hThread) == UInt32.MaxValue)
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            catch
            {
                Close(ref inRead);
                Close(ref outWrite);
                Close(ref outRead);
                Dispose();
                throw;
            }
            finally
            {
                Close(ref info.hThread);
                Close(ref info.hProcess);
                Close(ref inRead);
                Close(ref outWrite);
                Close(ref outRead);
                if (initialized) Native.DeleteProcThreadAttributeList(attributes);
                if (attributes != IntPtr.Zero) Marshal.FreeHGlobal(attributes);
                if (jobList != IntPtr.Zero) Marshal.FreeHGlobal(jobList);
            }
        }

        private void ReadOutput(IntPtr handle)
        {
            try
            {
                using (var file = new FileStream(new SafeFileHandle(handle, true), FileAccess.Read, 4096, false))
                {
                    var buffer = new byte[4096];
                    var chars = new char[Encoding.UTF8.GetMaxCharCount(buffer.Length)];
                    Decoder decoder = Encoding.UTF8.GetDecoder();
                    int count;
                    // Read one available pipe block; never wait for a complete
                    // text line or a requested number of decoded characters.
                    while ((count = file.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        int length = decoder.GetChars(buffer, 0, count, chars, 0, false);
                        Action<string> output = Ausgabe;
                        if (output == null) continue;
                        try { output(new string(chars, 0, length)); }
                        catch (Exception) { /* Continue draining even if the UI closes. */ }
                    }
                }
            }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            try
            {
                if (!Beendet && input != IntPtr.Zero)
                {
                    uint written;
                    Native.WriteFile(input, new byte[] { 3 }, 1, out written, IntPtr.Zero); // Ctrl+C
                    Native.WaitForSingleObject(process, 1500);
                }
            }
            finally
            {
                Close(ref job); // terminates all remaining owned processes
                if (process != IntPtr.Zero) Native.WaitForSingleObject(process, 1500);
                if (console != IntPtr.Zero) { Native.ClosePseudoConsole(console); console = IntPtr.Zero; }
                Close(ref input);
                Close(ref process);
                if (reader != null) reader.Join(1500);
            }
        }

        private static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
        private static void Close(ref IntPtr handle)
        {
            if (handle != IntPtr.Zero && handle != new IntPtr(-1)) Native.CloseHandle(handle);
            handle = IntPtr.Zero;
        }
    }

    internal static class Native
    {
        [StructLayout(LayoutKind.Sequential)]
        internal struct COORD
        {
            public short X, Y;
            public COORD(short x, short y) { X = x; Y = y; }
        }
        [StructLayout(LayoutKind.Sequential)]
        internal struct STARTUPINFO
        {
            public int cb;
            public IntPtr lpReserved, lpDesktop, lpTitle;
            public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
            public ushort wShowWindow, cbReserved2;
            public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
        }
        [StructLayout(LayoutKind.Sequential)]
        internal struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr lpAttributeList; }
        [StructLayout(LayoutKind.Sequential)]
        internal struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public uint dwProcessId, dwThreadId; }
        [StructLayout(LayoutKind.Sequential)]
        internal struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        internal struct IO_COUNTERS { public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount; }
        [StructLayout(LayoutKind.Sequential)]
        internal struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        internal static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint length);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool CreatePipe(out IntPtr read, out IntPtr write, IntPtr attributes, uint size);
        [DllImport("kernel32.dll")]
        internal static extern int CreatePseudoConsole(COORD size, IntPtr input, IntPtr output, uint flags, out IntPtr console);
        [DllImport("kernel32.dll")]
        internal static extern void ClosePseudoConsole(IntPtr console);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returnedSize);
        [DllImport("kernel32.dll")]
        internal static extern void DeleteProcThreadAttributeList(IntPtr list);
        [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes,
            [MarshalAs(UnmanagedType.Bool)] bool inherit, uint flags, IntPtr environment, string directory, ref STARTUPINFOEX startup, out PROCESS_INFORMATION process);
        [DllImport("kernel32.dll", SetLastError = true)] internal static extern uint ResumeThread(IntPtr thread);
        [DllImport("kernel32.dll", SetLastError = true)] internal static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        internal static extern bool WriteFile(IntPtr handle, byte[] data, uint size, out uint written, IntPtr overlapped);
        [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] internal static extern bool CloseHandle(IntPtr handle);
    }
}
