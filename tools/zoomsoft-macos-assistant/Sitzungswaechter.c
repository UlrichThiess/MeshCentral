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
#define _GNU_SOURCE
#include <pty.h>
#endif
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;
static volatile sig_atomic_t stopping = 0;
typedef struct { pid_t pid; int master; } Process;

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
    if (child <= 0) { return 0; }
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

static int spawn_process(char *agent, char *const args[], int lockfd, Process *process) {
    int master = -1, slave = -1;
    if (openpty(&master, &slave, NULL, NULL, NULL) < 0) { return errno; }
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
    int error = posix_spawn(&process->pid, agent, &files, &attributes, args, environ);
    posix_spawn_file_actions_destroy(&files);
    posix_spawnattr_destroy(&attributes);
    close(slave);
    if (error) { close(master); process->pid = -1; return error; }
    process->master = master;
    return 0;
}

#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
typedef struct { Process process; const char *path; struct stat socket; int owned; } Bildschirm;

/* Never replace an active listener or a foreign filesystem object. */
static int existing_listener(const char *path) {
    struct stat info;
    if (lstat(path, &info) < 0) { return errno == ENOENT ? 0 : -1; }
    if (!S_ISSOCK(info.st_mode) || info.st_uid != getuid()) { return -1; }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { return -1; }
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    if (strlen(path) >= sizeof(address.sun_path)) { close(fd); return -1; }
    strcpy(address.sun_path, path);
    socklen_t length = (socklen_t)(offsetof(struct sockaddr_un, sun_path) + strlen(path) + 1);
#ifdef __APPLE__
    address.sun_len = (unsigned char)length;
#endif
    fcntl(fd, F_SETFL, O_NONBLOCK);
    int connected = connect(fd, (struct sockaddr *)&address, length);
    int error = connected == 0 ? 0 : errno;
    if (error == EINPROGRESS || error == EAGAIN) {
        struct pollfd event = { fd, POLLOUT, 0 };
        if (poll(&event, 1, 200) > 0) {
            socklen_t size = sizeof(error);
            if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) < 0) { error = errno; }
        }
    }
    int trusted = 0;
    if (!error) {
#ifdef __APPLE__
        uid_t uid; gid_t gid;
        trusted = getpeereid(fd, &uid, &gid) == 0 && uid == getuid();
#else
        struct ucred credentials;
        socklen_t size = sizeof(credentials);
        trusted = getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &credentials, &size) == 0 && credentials.uid == getuid();
#endif
    }
    close(fd);
    if (!error) { return trusted ? 1 : -1; }
    if (error != ECONNREFUSED && error != ENOENT) { return -1; }
    struct stat current;
    if (lstat(path, &current) == 0 && current.st_dev == info.st_dev && current.st_ino == info.st_ino) {
        if (unlink(path) != 0) { return -1; }
    }
    return 0;
}

static void remove_owned_socket(Bildschirm *screen) {
    struct stat current;
    if (screen->owned && lstat(screen->path, &current) == 0 &&
        current.st_dev == screen->socket.st_dev && current.st_ino == screen->socket.st_ino) {
        (void)unlink(screen->path);
    }
}

static int start_screen(char *agent, int lockfd, pid_t parent, Bildschirm *screen) {
    int existing = existing_listener(screen->path);
    if (existing > 0) {
        message("ZOOMSOFT:KVMREUSED Ein vorhandener Bildschirmprozess wird mitbenutzt.\n");
        return 0;
    }
    if (existing < 0) {
        message("ZOOMSOFT:ERROR Der lokale Bildschirmkanal ist durch einen anderen Prozess belegt.\n");
        return 71;
    }
    char *args[] = { agent, "-kvmagent", (char *)screen->path, NULL };
    if (spawn_process(agent, args, lockfd, &screen->process) != 0) {
        message("ZOOMSOFT:ERROR Der Bildschirmprozess konnte nicht gestartet werden.\n");
        return 71;
    }
    char text[8192] = {0};
    size_t used = 0;
    long long deadline = milliseconds() + 5000;
    while (!stopping && getppid() == parent && milliseconds() < deadline) {
        struct stat current;
        if (lstat(screen->path, &current) == 0 && S_ISSOCK(current.st_mode) && current.st_uid == getuid()) {
            screen->socket = current;
            screen->owned = 1;
        }
        if (child_exited(screen->process.pid)) { break; }
        struct pollfd events[2] = { { STDIN_FILENO, POLLIN | POLLHUP, 0 }, { screen->process.master, POLLIN, 0 } };
        int result = poll(events, 2, 50);
        if (result < 0 && errno != EINTR) { break; }
        if (events[0].revents) { return 125; }
        if (events[1].revents) {
            char buffer[4096];
            ssize_t count = read(screen->process.master, buffer, sizeof(buffer));
            if (count > 0) {
                output(buffer, (size_t)count);
                if (used + (size_t)count >= sizeof(text)) {
                    memmove(text, text + used - 256, 256); used = 256;
                }
                memcpy(text + used, buffer, (size_t)count);
                used += (size_t)count;
                text[used] = 0;
                if (strstr(text, "LISTENING ON DOMAIN SOCKET")) {
                    if (lstat(screen->path, &screen->socket) == 0 && S_ISSOCK(screen->socket.st_mode)) {
                        screen->owned = 1;
                        message("ZOOMSOFT:KVMREADY\n");
                        return 0;
                    }
                }
            }
        }
    }
    if (stopping || getppid() != parent) { return 125; }
    message("ZOOMSOFT:ERROR Der Bildschirmprozess ist nicht bereit. Bitte erneut verbinden.\n");
    return 71;
}
#endif

int main(int argc, char **argv) {
    int arguments_ok = argc == 4;
#ifdef ZOOMSOFT_TEST_KVM
    arguments_ok = arguments_ok || argc == 5;
#endif
    if (!arguments_ok || argv[2][0] != '/' || argv[3][0] != '/') { return 64; }
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
    /* Remove only this app's obsolete session log after taking its lock. */
    (void)unlink("sitzung.log");
#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
    char socket_path[104];
    snprintf(socket_path, sizeof(socket_path), "/tmp/meshagent-kvm-%u.sock", (unsigned)getuid());
    Bildschirm screen = { { -1, -1 }, socket_path, {0}, 0 };
    int screen_enabled = 1;
#ifdef ZOOMSOFT_TEST_KVM
    screen_enabled = argc == 5;
    if (screen_enabled) { screen.path = argv[4]; }
#endif
    if (screen_enabled) {
        int error = start_screen(argv[2], lockfd, parent, &screen);
        if (error) {
            finish(screen.process.pid, screen.process.master);
            remove_owned_socket(&screen);
            close(lockfd);
            return error == 125 ? 0 : error;
        }
    }
#endif
    char *args[] = { argv[2], "connect", "--configUsesCWD=1", "--disableUpdate=1", NULL };
    Process engine = { -1, -1 };
    int error = spawn_process(argv[2], args, lockfd, &engine);
    if (error) {
        message("ZOOMSOFT:ERROR Der MeshAgent konnte nicht gestartet werden.\n");
#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
        finish(screen.process.pid, screen.process.master);
        remove_owned_socket(&screen);
#endif
        close(lockfd);
        return 71;
    }
    message("ZOOMSOFT:STARTED\n");

    int unexpected = 0;
    while (!stopping && getppid() == parent) {
        if (child_exited(engine.pid)) { unexpected = 1; break; }
        int screen_master = -1;
#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
        if (screen.process.pid > 0) {
            if (child_exited(screen.process.pid)) {
                message("ZOOMSOFT:ERROR Der Bildschirmprozess wurde beendet. Bitte erneut verbinden.\n");
                unexpected = 1; break;
            }
            screen_master = screen.process.master;
        }
#endif
        struct pollfd events[3] = {
            { STDIN_FILENO, POLLIN | POLLHUP, 0 }, { engine.master, POLLIN, 0 }, { screen_master, POLLIN, 0 }
        };
        int count = poll(events, 3, 100);
        if (count < 0 && errno != EINTR) { break; }
        if (events[0].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL)) {
            char command[32];
            ssize_t received = read(STDIN_FILENO, command, sizeof(command));
            /* Any command or EOF requests termination; there is no remote control API. */
            if (received >= 0 || errno != EINTR) { break; }
        }
        if (events[1].revents) { drain(engine.master); }
        if (events[2].revents) { drain(screen_master); }
    }
#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
    if (screen.process.pid > 0) { kill(-screen.process.pid, SIGINT); }
#endif
    int status = finish(engine.pid, engine.master);
#if defined(__APPLE__) || defined(ZOOMSOFT_TEST_KVM)
    finish(screen.process.pid, screen.process.master);
    remove_owned_socket(&screen);
#endif
    close(lockfd);
    message("ZOOMSOFT:STOPPED\n");
    return unexpected ? (status ? status : 1) : 0;
}
