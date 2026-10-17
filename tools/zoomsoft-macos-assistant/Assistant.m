// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <CoreGraphics/CoreGraphics.h>
#import <dispatch/dispatch.h>
#include <signal.h>
#include <unistd.h>

static NSString *const Produkt = @"Fernwartung | ZOOMsoft GmbH";

@interface Assistant : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTextField *status;
@property(nonatomic, strong) NSTextField *screenStatus;
@property(nonatomic, strong) NSTextField *inputStatus;
@property(nonatomic, strong) NSButton *retryButton;
@property(nonatomic, strong) NSTask *guardian;
@property(nonatomic, strong) NSPipe *control;
@property(nonatomic, strong) NSFileHandle *reader;
@property(nonatomic, strong) NSMutableData *outputBuffer;
@property(nonatomic, strong) NSTimer *permissionsTimer;
@property(nonatomic, strong) NSMutableArray *signalSources;
@property(nonatomic, assign) BOOL quitting;
@property(nonatomic, assign) BOOL connected;
@property(nonatomic, assign) BOOL authenticated;
@property(nonatomic, copy) NSString *sessionError;
- (void)start;
- (void)permissions;
- (void)consume:(NSData *)bytes;
- (void)failure:(NSString *)text;
- (void)closeControl;
@end

@implementation Assistant
- (NSTextField *)label:(NSString *)text x:(CGFloat)x y:(CGFloat)y width:(CGFloat)width height:(CGFloat)height {
    NSTextField *label = [NSTextField wrappingLabelWithString:text];
    label.frame = NSMakeRect(x, y, width, height);
    [self.window.contentView addSubview:label];
    return label;
}

- (NSButton *)button:(NSString *)title action:(SEL)action x:(CGFloat)x y:(CGFloat)y width:(CGFloat)width {
    NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
    button.bezelStyle = NSBezelStyleRounded;
    button.frame = NSMakeRect(x, y, width, 32);
    [self.window.contentView addSubview:button];
    return button;
}

- (void)menu {
    NSMenu *bar = [[NSMenu alloc] init];
    NSMenuItem *item = [[NSMenuItem alloc] init];
    NSMenu *menu = [[NSMenu alloc] initWithTitle:Produkt];
    NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"Fernwartung beenden"
        action:@selector(beenden:) keyEquivalent:@"q"];
    quit.target = self;
    [menu addItem:quit];
    item.submenu = menu;
    [bar addItem:item];
    NSApp.mainMenu = bar;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    NSBundle *bundle = [NSBundle mainBundle];
    for (NSRunningApplication *app in [NSRunningApplication runningApplicationsWithBundleIdentifier:bundle.bundleIdentifier]) {
        if (app.processIdentifier != getpid()) {
            [app activateWithOptions:NSApplicationActivateIgnoringOtherApps];
            [NSApp terminate:nil];
            return;
        }
    }
    [self menu];
    [NSApp activateIgnoringOtherApps:YES];
    NSString *path = bundle.bundlePath;
    if ([path hasPrefix:@"/Volumes/"] || [path containsString:@"/AppTranslocation/"]) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = Produkt;
        alert.informativeText = @"Ziehen Sie die App zuerst in „Programme“ und starten Sie sie anschließend von dort.";
        [alert addButtonWithTitle:@"Programme öffnen"];
        [alert addButtonWithTitle:@"Schließen"];
        if ([alert runModal] == NSAlertFirstButtonReturn) {
            [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:@"/Applications" isDirectory:YES]];
        }
        [NSApp terminate:nil];
        return;
    }

    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 600, 420)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
        backing:NSBackingStoreBuffered defer:NO];
    self.window.title = Produkt;
    self.window.delegate = self;
    self.window.releasedWhenClosed = NO;
    self.window.restorable = NO;
    [self.window center];
    NSImageView *logo = [[NSImageView alloc] initWithFrame:NSMakeRect(28, 298, 90, 90)];
    logo.image = [NSImage imageNamed:NSImageNameApplicationIcon];
    logo.imageScaling = NSImageScaleProportionallyUpOrDown;
    [self.window.contentView addSubview:logo];
    NSTextField *title = [self label:Produkt x:140 y:346 width:438 height:35];
    title.font = [NSFont boldSystemFontOfSize:21];
    [self label:@"Die Fernwartung ist aktiv, solange dieses Fenster geöffnet ist.\nSchließen beendet die Verbindung."
        x:140 y:299 width:430 height:44];
    self.status = [self label:@"Verbindung wird aufgebaut …" x:28 y:250 width:540 height:30];
    self.status.font = [NSFont boldSystemFontOfSize:17];
    NSString *computer = [NSHost currentHost].localizedName ?: [NSProcessInfo processInfo].hostName;
    [self label:[@"Rechner: " stringByAppendingString:computer] x:28 y:222 width:540 height:22];
    self.screenStatus = [self label:@"Bildschirmaufnahme: Freigabe prüfen …" x:28 y:168 width:340 height:25];
    [self button:@"Bildschirm freigeben" action:@selector(bildschirm:) x:376 y:164 width:196];
    self.inputStatus = [self label:@"Bedienung: Freigabe prüfen …" x:28 y:124 width:340 height:25];
    [self button:@"Bedienung freigeben" action:@selector(bedienung:) x:376 y:120 width:196];
    NSTextField *hint = [self label:@"Beim ersten Start sind die macOS-Freigaben zu bestätigen."
        x:28 y:80 width:544 height:28];
    hint.textColor = NSColor.secondaryLabelColor;
    self.retryButton = [self button:@"Erneut verbinden" action:@selector(erneut:) x:28 y:24 width:180];
    self.retryButton.enabled = NO;
    [self button:@"Fernwartung beenden" action:@selector(beenden:) x:352 y:24 width:220];
    [self.window makeKeyAndOrderFront:nil];
    [self permissions];
    self.permissionsTimer = [NSTimer scheduledTimerWithTimeInterval:2 target:self
        selector:@selector(permissions) userInfo:nil repeats:YES];
    [[NSProcessInfo processInfo] disableAutomaticTermination:@"Fernwartung läuft"];

    self.signalSources = [NSMutableArray array];
    for (NSNumber *number in @[@(SIGTERM), @(SIGINT), @(SIGHUP)]) {
        int value = number.intValue;
        signal(value, SIG_IGN);
        dispatch_source_t source = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL,
            (uintptr_t)value, 0, dispatch_get_main_queue());
        dispatch_source_set_event_handler(source, ^{ [NSApp terminate:nil]; });
        dispatch_resume(source);
        [self.signalSources addObject:source];
    }
    [self start];
}

- (void)permissions {
    BOOL screen = CGPreflightScreenCaptureAccess();
    BOOL input = AXIsProcessTrusted();
    self.screenStatus.stringValue = screen ? @"Bildschirmaufnahme: freigegeben" : @"Bildschirmaufnahme: noch erlauben";
    self.inputStatus.stringValue = input ? @"Bedienung: freigegeben" : @"Bedienung: noch erlauben";
    self.screenStatus.textColor = screen ? NSColor.secondaryLabelColor : NSColor.systemOrangeColor;
    self.inputStatus.textColor = input ? NSColor.secondaryLabelColor : NSColor.systemOrangeColor;
}

- (void)bildschirm:(id)sender {
    (void)sender;
    if (!CGPreflightScreenCaptureAccess()) { (void)CGRequestScreenCaptureAccess(); }
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:
        @"x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"]];
    [self permissions];
}

- (void)bedienung:(id)sender {
    (void)sender;
    NSDictionary *options = @{ (__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES };
    (void)AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:
        @"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]];
    [self permissions];
}

- (void)start {
    if (self.guardian || self.quitting) { return; }
    NSBundle *bundle = [NSBundle mainBundle];
    NSError *error = nil;
    NSFileManager *manager = [NSFileManager defaultManager];
    NSURL *support = [manager URLForDirectory:NSApplicationSupportDirectory
        inDomain:NSUserDomainMask appropriateForURL:nil create:YES error:&error];
    NSURL *data = [support URLByAppendingPathComponent:bundle.bundleIdentifier isDirectory:YES];
    if (!data || ![manager createDirectoryAtURL:data withIntermediateDirectories:YES
        attributes:@{ NSFilePosixPermissions: @0700 } error:&error] ||
        ![manager setAttributes:@{ NSFilePosixPermissions: @0700 } ofItemAtPath:data.path error:&error]) {
        [self failure:@"Das persönliche Verzeichnis für die Verbindungsdaten ist nicht erreichbar."];
        return;
    }
    NSData *configuration = [NSData dataWithContentsOfURL:[bundle URLForResource:@"meshagent" withExtension:@"msh"]];
    NSURL *destination = [data URLByAppendingPathComponent:@"meshagent.msh"];
    if (!configuration || ![configuration writeToURL:destination options:NSDataWritingAtomic error:&error] ||
        ![manager setAttributes:@{ NSFilePosixPermissions: @0600 } ofItemAtPath:destination.path error:&error]) {
        [self failure:@"Die Verbindungseinstellungen konnten nicht geladen werden."];
        return;
    }
    self.outputBuffer = [NSMutableData data];
    self.sessionError = nil;
    self.connected = NO;
    self.authenticated = NO;
    self.control = [NSPipe pipe];
    NSPipe *output = [NSPipe pipe];
    self.reader = output.fileHandleForReading;
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [bundle.bundleURL URLByAppendingPathComponent:@"Contents/MacOS/Sitzungswaechter"];
    NSURL *agent = [bundle.bundleURL URLByAppendingPathComponent:@"Contents/MacOS/meshagent"];
    task.arguments = @[[NSString stringWithFormat:@"%d", getpid()], agent.path, data.path];
    task.standardInput = self.control;
    task.standardOutput = output;
    task.standardError = output;
    task.currentDirectoryURL = data;
    __weak Assistant *weakSelf = self;
    __weak NSTask *weakTask = task;
    self.reader.readabilityHandler = ^(NSFileHandle *handle) {
        NSData *bytes = [handle readDataUpToLength:16384 error:NULL];
        if (bytes.length == 0) { handle.readabilityHandler = nil; return; }
        dispatch_async(dispatch_get_main_queue(), ^{
            Assistant *strongSelf = weakSelf;
            if (strongSelf && strongSelf.guardian == weakTask) { [strongSelf consume:bytes]; }
        });
    };
    task.terminationHandler = ^(NSTask *finished) {
        (void)finished;
        dispatch_async(dispatch_get_main_queue(), ^{
            Assistant *strongSelf = weakSelf;
            if (!strongSelf || strongSelf.guardian != finished) { return; }
            strongSelf.reader.readabilityHandler = nil;
            [strongSelf.reader closeAndReturnError:NULL];
            strongSelf.reader = nil;
            [strongSelf closeControl];
            strongSelf.guardian = nil;
            if (strongSelf.quitting) { [NSApp replyToApplicationShouldTerminate:YES]; }
            else { [strongSelf failure:strongSelf.sessionError ?: @"Die Verbindung wurde beendet. Sie können sie erneut aufbauen."]; }
        });
    };
    self.guardian = task;
    if (![task launchAndReturnError:&error]) {
        self.reader.readabilityHandler = nil;
        [self.reader closeAndReturnError:NULL];
        [self closeControl];
        self.reader = nil;
        self.control = nil;
        self.guardian = nil;
        [self failure:@"Die Fernwartung konnte nicht gestartet werden."];
        return;
    }
    self.retryButton.enabled = NO;
    self.status.stringValue = @"Verbindung wird aufgebaut …";
    self.status.textColor = NSColor.secondaryLabelColor;
}

- (void)consume:(NSData *)bytes {
    if (self.quitting) { return; }
    [self.outputBuffer appendData:bytes];
    const unsigned char *content = self.outputBuffer.bytes;
    NSUInteger consumed = 0;
    for (NSUInteger index = 0; index < self.outputBuffer.length; ++index) {
        if (content[index] != '\n') { continue; }
        NSData *lineData = [self.outputBuffer subdataWithRange:NSMakeRange(consumed, index - consumed)];
        NSString *line = [[NSString alloc] initWithData:lineData encoding:NSUTF8StringEncoding];
        line = [line stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        consumed = index + 1;
        if ([line isEqualToString:@"Authentication Complete..."]) {
            self.authenticated = YES;
        } else if ([line isEqualToString:@"Connected."]) {
            self.connected = YES;
        } else if ([line hasPrefix:@"Control Channel Disconnected"] ||
                   [line hasPrefix:@"Mesh Server Connection Error"] ||
                   [line hasPrefix:@"Connecting to"] || [line hasPrefix:@"Attempting to connect"] ) {
            self.status.stringValue = @"Verbindung wird aufgebaut …";
            self.status.textColor = NSColor.systemOrangeColor;
            self.connected = NO;
            self.authenticated = NO;
        } else if ([line hasPrefix:@"ZOOMSOFT:ERROR "]) {
            self.sessionError = [line substringFromIndex:15];
            [self failure:self.sessionError];
        } else if ([line isEqualToString:@"Bad server certificate hash"] ||
                   [line isEqualToString:@"Invalid server signature"]) {
            self.status.stringValue = @"Server konnte nicht bestätigt werden";
            self.status.textColor = NSColor.systemRedColor;
            self.connected = NO;
            self.authenticated = NO;
        }
        if (self.connected && self.authenticated) {
            self.status.stringValue = @"Mit ZOOMsoft verbunden";
            self.status.textColor = NSColor.systemGreenColor;
        }
    }
    if (consumed) { [self.outputBuffer replaceBytesInRange:NSMakeRange(0, consumed) withBytes:NULL length:0]; }
    if (self.outputBuffer.length > 65536) { [self.outputBuffer setLength:0]; }
}

- (void)failure:(NSString *)text {
    self.status.stringValue = text;
    self.status.textColor = NSColor.systemRedColor;
    self.retryButton.enabled = self.guardian == nil;
}

- (void)erneut:(id)sender { (void)sender; [self start]; }
- (void)beenden:(id)sender { (void)sender; [NSApp terminate:nil]; }

- (void)closeControl {
    NSFileHandle *writer = self.control.fileHandleForWriting;
    self.control = nil;
    [writer closeAndReturnError:NULL];
}

- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender;
    [NSApp terminate:nil];
    return NO;
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    (void)sender; (void)visible;
    if (!self.quitting) { [self.window makeKeyAndOrderFront:nil]; }
    return YES;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    if (!self.guardian) { return NSTerminateNow; }
    if (!self.quitting) {
        self.quitting = YES;
        self.status.stringValue = @"Verbindung wird beendet …";
        self.retryButton.enabled = NO;
        [self.permissionsTimer invalidate];
        [self closeControl];
    }
    return NSTerminateLater;
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    (void)notification;
    [self closeControl];
    [self.permissionsTimer invalidate];
}
@end

int main(void) {
    @autoreleasepool {
        [[NSUserDefaults standardUserDefaults] setObject:@[@"de"] forKey:@"AppleLanguages"];
        [[NSUserDefaults standardUserDefaults] setObject:@"de_DE" forKey:@"AppleLocale"];
        [[NSUserDefaults standardUserDefaults] setBool:NO forKey:@"NSQuitAlwaysKeepsWindows"];
        NSApplication *application = [NSApplication sharedApplication];
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        __attribute__((objc_precise_lifetime)) Assistant *delegate = [[Assistant alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
