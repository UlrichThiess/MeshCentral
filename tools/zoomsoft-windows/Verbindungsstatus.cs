// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
using System;
using System.Text;

namespace ZOOMsoft.Fernwartung
{
    public enum Verbindungsstatus { Unveraendert, Verbindet, Verbunden, Fehler }

    // ConPTY emits UTF-8 text plus terminal controls. Keep the lexer state across
    // reads, and recognise short status messages even without a trailing newline.
    public sealed class StatusLeser
    {
        private readonly StringBuilder line = new StringBuilder();
        private readonly Action<Verbindungsstatus> changed;
        private Verbindungsstatus previous = Verbindungsstatus.Unveraendert;
        private int escape;

        public StatusLeser(Action<Verbindungsstatus> changed) { this.changed = changed; }

        public static Verbindungsstatus Erkennen(string text)
        {
            if (String.IsNullOrEmpty(text)) return Verbindungsstatus.Unveraendert;
            text = text.Trim();
            if (text.EndsWith("Connected.", StringComparison.Ordinal) &&
                (text == "Connected." || text.StartsWith("Connecting ", StringComparison.Ordinal) ||
                 text.StartsWith("[Recovery Agent] ", StringComparison.Ordinal)))
                return Verbindungsstatus.Verbunden;
            foreach (string prefix in new[] { "Connecting ", "Attempting to connect", "AutoRetry Connect",
                                               "Control Channel Disconnected", "Mesh Server Connection Error",
                                               "Network Timeout occurred" })
                if (text.StartsWith(prefix, StringComparison.Ordinal)) return Verbindungsstatus.Verbindet;
            foreach (string error in new[] { "Bad server certificate hash", "Invalid server signature", "Server certificate mismatch" })
                if (text == error) return Verbindungsstatus.Fehler;
            return Verbindungsstatus.Unveraendert;
        }

        private void Emit()
        {
            Verbindungsstatus state = Erkennen(line.ToString());
            if (state == Verbindungsstatus.Unveraendert || state == previous) return;
            previous = state;
            changed(state);
        }

        public void Lesen(string text)
        {
            foreach (char ch in text)
            {
                if (escape == 1) { escape = ch == '[' ? 2 : (ch == ']' ? 3 : 0); continue; }
                if (escape == 2) { if (ch >= '@' && ch <= '~') escape = 0; continue; }
                if (escape == 3) { if (ch == '\a') escape = 0; else if (ch == '\x1B') escape = 4; continue; }
                if (escape == 4) { escape = ch == '\\' ? 0 : 3; continue; }
                if (ch == '\x1B') { escape = 1; continue; }
                if (ch == '\r' || ch == '\n') { Emit(); line.Clear(); continue; }
                if (ch == '\b') { if (line.Length > 0) line.Length--; continue; }
                if (ch < ' ' && ch != '\t') continue;
                line.Append(ch);
                if (line.Length > 65536) line.Clear();
                // A single console frame may contain several complete messages.
                if (ch == '.') Emit();
            }
            Emit();
        }
    }
}
