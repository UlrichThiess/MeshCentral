/* Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
 * Owns the temporary MeshAgent process group. Closing stdin, losing the GUI
 * parent or receiving a termination signal closes the entire support session.
 * No service, privileged helper, login item or global process-name kill.
 */
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#include <util.h>
#else
#define _DEFAULT_SOURCE
#include <pty.h>
#endif
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;
static volatile sig_atomic_t stopping = 0;

static void stop_signal(int value) { (void)value; stopping = 1; }

static long long milliseconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* Never block cleanup if the GUI stops reading or is killed. */
static void output(const char *data, size_t size) {
    while (size > 0) {
        ssize_t count = write(STDOUT_FILENO, data, size);
        if (count > 0) { data += count; size -= (size_t)count; }
        else if (count < 0 && errno == EINTR) { continue; }
        else { break; }
    }
}

static void message(const char *text) { output(text, strlen(text)); }

static void drain(int master) {
    char buffer[4096];
    for (int i = 0; i < 16; ++i) {
        ssize_t count = read(master, buffer, sizeof(buffer));
        if (count <= 0) { break; }
        output(buffer, (size_t)count);
    }
}

/* WNOWAIT keeps the PID reserved until group cleanup has finished. */
static int child_exited(pid_t child) {
    siginfo_t info;
    memset(&info, 0, sizeof(info));
    if (waitid(P_PID, (id_t)child, &info, WEXITED | WNOHANG | WNOWAIT) < 0) {
        return errno == ECHILD;
    }
    return info.si_pid == child;
}

static int finish(pid_t child, int master) {
    /* SIGINT is MeshAgent's documented graceful console shutdown path. */
    kill(-child, SIGINT);
    long long deadline = milliseconds() + 1500;
    while (milliseconds() < deadline && !child_exited(child)) {
        struct pollfd event = { master, POLLIN, 0 };
        poll(&event, 1, 30);
        drain(master);
    }
    /* Includes KVM and remote shell descendants in this session's group. */
    kill(-child, SIGKILL);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) { break; }
    }
    drain(master);
    close(master);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}

int main(int argc, char **argv) {
    if (argc != 4 || argv[2][0] != '/' || argv[3][0] != '/') { return 64; }
    char *end = NULL;
    long parsed = strtol(argv[1], &end, 10);
    if (!end || *end || parsed <= 1 || (long)(pid_t)parsed != parsed) { return 64; }
    pid_t parent = (pid_t)parsed;
    if (getppid() != parent) { return 0; }

    /* A GUI process-group kill must not prevent this guardian from cleaning up. */
    (void)setsid();
    long maxfd = sysconf(_SC_OPEN_MAX);
    if (maxfd < 0) { maxfd = 1024; }
    for (int fd = 3; fd < maxfd; ++fd) { close(fd); }
    fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK);

    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = stop_signal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGHUP, &action, NULL);
    signal(SIGPIPE, SIG_IGN);
    signal(SIGCHLD, SIG_DFL);

    if (chdir(argv[3]) != 0) {
        message("ZOOMSOFT:ERROR Arbeitsverzeichnis nicht erreichbar.\n"); return 73;
    }
    umask(0077);
    int lockfd = open("sitzung.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (lockfd < 0 || flock(lockfd, LOCK_EX | LOCK_NB) != 0) {
        message("ZOOMSOFT:ERROR Die Fernwartung läuft bereits oder das Datenverzeichnis ist gesperrt.\n");
        if (lockfd >= 0) { close(lockfd); }
        return 73;
    }

    int master = -1, slave = -1;
    if (openpty(&master, &slave, NULL, NULL, NULL) < 0) {
        message("ZOOMSOFT:ERROR Der Agent-Ausgabekanal konnte nicht erstellt werden.\n");
        close(lockfd); return 71;
    }
    fcntl(master, F_SETFD, FD_CLOEXEC);
    fcntl(slave, F_SETFD, FD_CLOEXEC);
    fcntl(master, F_SETFL, fcntl(master, F_GETFL) | O_NONBLOCK);

    posix_spawn_file_actions_t files;
    posix_spawnattr_t attributes;
    posix_spawn_file_actions_init(&files);
    posix_spawn_file_actions_addopen(&files, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_adddup2(&files, slave, STDOUT_FILENO);
    posix_spawn_file_actions_adddup2(&files, slave, STDERR_FILENO);
    posix_spawn_file_actions_addclose(&files, master);
    posix_spawn_file_actions_addclose(&files, slave);
    posix_spawn_file_actions_addclose(&files, lockfd);
    posix_spawnattr_init(&attributes);
    sigset_t empty, defaults;
    sigemptyset(&empty);
    sigemptyset(&defaults);
    sigaddset(&defaults, SIGINT);
    sigaddset(&defaults, SIGTERM);
    sigaddset(&defaults, SIGHUP);
    sigaddset(&defaults, SIGPIPE);
    posix_spawnattr_setsigmask(&attributes, &empty);
    posix_spawnattr_setsigdefault(&attributes, &defaults);
    posix_spawnattr_setpgroup(&attributes, 0);
    posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP |
                            POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF);
    char *args[] = { argv[2], "connect", "--configUsesCWD=1", "--disableUpdate=1",
                     "--controlChannelDebug=1", NULL };
    pid_t child = -1;
    int error = posix_spawn(&child, argv[2], &files, &attributes, args, environ);
    posix_spawn_file_actions_destroy(&files);
    posix_spawnattr_destroy(&attributes);
    close(slave);
    if (error) {
        message("ZOOMSOFT:ERROR Der MeshAgent konnte nicht gestartet werden.\n");
        close(master); close(lockfd); return 71;
    }
    message("ZOOMSOFT:STARTED\n");

    int unexpected = 0;
    while (!stopping && getppid() == parent) {
        if (child_exited(child)) { unexpected = 1; break; }
        struct pollfd events[2] = {
            { STDIN_FILENO, POLLIN | POLLHUP, 0 }, { master, POLLIN, 0 }
        };
        int count = poll(events, 2, 100);
        if (count < 0 && errno != EINTR) { break; }
        if (events[0].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL)) {
            char command[32];
            ssize_t received = read(STDIN_FILENO, command, sizeof(command));
            /* Any command or EOF requests termination; there is no remote control API. */
            if (received >= 0 || errno != EINTR) { break; }
        }
        if (events[1].revents) { drain(master); }
    }
    int status = finish(child, master);
    close(lockfd);
    message("ZOOMSOFT:STOPPED\n");
    return unexpected ? (status ? status : 1) : 0;
}
