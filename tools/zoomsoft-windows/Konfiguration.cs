// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace ZOOMsoft.Fernwartung
{
    public static class Konfiguration
    {
        public const string Produkt = "Ferwartung | ZOOMsoft GmbH";
        public const string Dienstkennung = "ZOOMsoftFernwartung";
        private static readonly string[] Netzschluessel = {
            "MeshName", "MeshType", "MeshID", "ServerID", "MeshServer",
            "WebProxy", "autoproxy", "ignoreProxyFile"
        };
        private static readonly byte[] PolicyMarker = {
            0xB9, 0x96, 0x01, 0x58, 0x80, 0x54, 0x4A, 0x19,
            0xB7, 0xF7, 0xE9, 0xBE, 0x44, 0x91, 0x4C, 0x19
        };

        public static string EingebetteteEinstellungen(byte[] vorlage)
        {
            if (vorlage == null || vorlage.Length < 20)
                throw new InvalidDataException("Die Vorlage enthält keine MeshCentral-Verbindungseinstellungen.");
            for (int i = 0; i < PolicyMarker.Length; i++)
                if (vorlage[vorlage.Length - 16 + i] != PolicyMarker[i])
                    throw new InvalidDataException("Die Vorlage enthält keine Verbindungseinstellungen. Bitte einen Windows-Agenten aus deiner Gerätegruppe herunterladen oder -Konfiguration angeben.");
            int offset = vorlage.Length - 20;
            // MeshCentral's streamExeWithMeshPolicy writes the length big endian.
            uint length = ((uint)vorlage[offset] << 24) | ((uint)vorlage[offset + 1] << 16) |
                          ((uint)vorlage[offset + 2] << 8) | vorlage[offset + 3];
            if (length == 0 || length > 1024 * 1024 || length > offset)
                throw new InvalidDataException("Die eingebettete Konfiguration ist beschädigt.");
            return new UTF8Encoding(false, true).GetString(vorlage, offset - (int)length, (int)length);
        }

        public static Dictionary<string, string> Lesen(string text)
        {
            if (text == null || text.IndexOf('\0') >= 0)
                throw new InvalidDataException("Ungültige Verbindungseinstellungen.");
            var settings = new Dictionary<string, string>(StringComparer.Ordinal);
            using (var reader = new StringReader(text.TrimStart('\uFEFF')))
            {
                string line;
                while ((line = reader.ReadLine()) != null)
                {
                    line = line.Trim();
                    if (line.Length == 0 || line.StartsWith("#") || line.StartsWith(";")) continue;
                    int equal = line.IndexOf('=');
                    if (equal < 1) continue;
                    string key = line.Substring(0, equal).Trim();
                    if (Array.IndexOf(Netzschluessel, key) < 0) continue;
                    if (settings.ContainsKey(key))
                        throw new InvalidDataException("Mehrdeutige Verbindungseinstellung: " + key);
                    settings.Add(key, line.Substring(equal + 1).Trim());
                }
            }
            foreach (string key in new[] { "MeshType", "MeshID", "ServerID", "MeshServer" })
                if (!settings.ContainsKey(key) || settings[key].Length == 0)
                    throw new InvalidDataException("In der Vorlage fehlt " + key + ".");
            if (settings["MeshType"] != "2")
                throw new InvalidDataException("Die Vorlage muss zu einer Agentengerätegruppe gehören (MeshType=2).");
            Uri server;
            if (!Uri.TryCreate(settings["MeshServer"], UriKind.Absolute, out server) ||
                server.Scheme != "wss" || String.IsNullOrEmpty(server.Host) ||
                !String.IsNullOrEmpty(server.UserInfo) || !String.IsNullOrEmpty(server.Fragment))
                throw new InvalidDataException("Die Vorlage benötigt eine verschlüsselte MeshServer-Adresse (wss://…).");
            return settings;
        }

        public static string Filtern(string text)
        {
            var settings = Lesen(text);
            var result = new StringBuilder();
            foreach (string key in Netzschluessel)
                if (settings.ContainsKey(key)) result.Append(key).Append('=').Append(settings[key]).Append('\n');
            result.Append("disableUpdate=1\ndisplayName=").Append(Produkt)
                  .Append("\nmeshServiceName=").Append(Dienstkennung).Append('\n');
            return result.ToString();
        }

        public static string Kennung(string text)
        {
            var settings = Lesen(text);
            return Hash(Encoding.UTF8.GetBytes(settings["ServerID"] + "\n" + settings["MeshID"]));
        }

        public static string Hash(byte[] data)
        {
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }

        public static ushort AgentPruefen(byte[] data)
        {
            if (data == null || data.Length < 256 || data[0] != 'M' || data[1] != 'Z')
                throw new InvalidDataException("Die Vorlage ist kein Windows-Agent.");
            int pe = BitConverter.ToInt32(data, 0x3C);
            if (pe < 0 || pe > data.Length - 256 || BitConverter.ToUInt32(data, pe) != 0x00004550)
                throw new InvalidDataException("Ungültige Windows-Programmdatei.");
            ushort machine = BitConverter.ToUInt16(data, pe + 4);
            ushort magic = BitConverter.ToUInt16(data, pe + 24);
            if ((machine != 0x014C && machine != 0x8664 && machine != 0xAA64) ||
                (magic != 0x10B && magic != 0x20B))
                throw new InvalidDataException("Nicht unterstützte Windows-Architektur.");
            int directories = pe + 24 + (magic == 0x20B ? 112 : 96);
            if (directories + 15 * 8 > data.Length || BitConverter.ToUInt32(data, directories + 14 * 8) != 0)
                throw new InvalidDataException("Bitte den nativen Windows-MeshAgent verwenden, nicht MeshCentralAssistant.exe.");
            string binary = Encoding.ASCII.GetString(data);
            foreach (string feature in new[] { "configUsesCWD", "disableUpdate", "MeshServer", "connect", "-nocertstore" })
                if (binary.IndexOf(feature, StringComparison.Ordinal) < 0)
                    throw new InvalidDataException("Die Vorlage unterstützt eine benötigte Agentenfunktion nicht: " + feature);
            return machine;
        }
    }
}
