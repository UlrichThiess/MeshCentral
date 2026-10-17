/* Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0. */
#ifndef ZOOMSOFT_VERBINDUNGSSTATUS_H
#define ZOOMSOFT_VERBINDUNGSSTATUS_H
#include <string.h>

typedef enum { ZS_UNVERAENDERT, ZS_VERBINDET, ZS_VERBUNDEN, ZS_FEHLER } ZSStatus;

static ZSStatus zs_verbindungsstatus(const char *line) {
    if (!line) { return ZS_UNVERAENDERT; }
    size_t length = strlen(line);
    /* Older agents can append Connected. to the preceding connection message.
     * Authentication Complete... is debug-only and is not a required second event.
     */
    if (length >= 10 && strcmp(line + length - 10, "Connected.") == 0 &&
        (length == 10 || strncmp(line, "Connecting ", 11) == 0 ||
         strncmp(line, "[Recovery Agent] ", 17) == 0)) { return ZS_VERBUNDEN; }
    if (strncmp(line, "Control Channel Disconnected", 28) == 0 ||
        strncmp(line, "Mesh Server Connection Error", 28) == 0 ||
        strncmp(line, "Connecting ", 11) == 0 ||
        strncmp(line, "Attempting to connect", 21) == 0 ||
        strncmp(line, "AutoRetry Connect", 17) == 0) { return ZS_VERBINDET; }
    if (strncmp(line, "ZOOMSOFT:ERROR ", 15) == 0 ||
        strcmp(line, "Bad server certificate hash") == 0 ||
        strcmp(line, "Invalid server signature") == 0 ||
        strcmp(line, "Server certificate mismatch") == 0) { return ZS_FEHLER; }
    return ZS_UNVERAENDERT;
}
#endif
