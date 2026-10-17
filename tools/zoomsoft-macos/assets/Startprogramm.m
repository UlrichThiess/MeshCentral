#import <Cocoa/Cocoa.h>
#import <dispatch/dispatch.h>
#include <sys/sysctl.h>

static NSString *const Produktname = @"Fernwartung | ZOOMsoft GmbH";

static NSString *ShellString(NSString *value) {
    return [NSString stringWithFormat:@"'%@'",
        [value stringByReplacingOccurrencesOfString:@"'" withString:@"'\"'\"'"]];
}

static NSString *AppleScriptString(NSString *value) {
    NSString *escaped = [value stringByReplacingOccurrencesOfString:@"\\" withString:@"\\\\"];
    escaped = [escaped stringByReplacingOccurrencesOfString:@"\"" withString:@"\\\""];
    return [NSString stringWithFormat:@"\"%@\"", escaped];
}

@interface FernwartungDialog : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSWindow *fortschritt;
@property(nonatomic, assign) BOOL deinstallation;
@property(nonatomic, assign) BOOL beschaeftigt;
- (void)fertigMitFehler:(NSDictionary *)fehler;
@end

@implementation FernwartungDialog
- (NSAlert *)meldung:(NSString *)text details:(NSString *)details {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = text;
    alert.informativeText = details;
    NSImage *icon = [[NSImage alloc] initWithContentsOfFile:
        [[NSBundle mainBundle] pathForResource:@"AppIcon" ofType:@"icns"]];
    if (icon) alert.icon = icon;
    return alert;
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    (void)notification;
    NSBundle *bundle = [NSBundle mainBundle];
    self.deinstallation = [[bundle objectForInfoDictionaryKey:@"ZOOMsoftVorgang"] isEqualToString:@"deinstallation"];
    [NSApp activateIgnoringOtherApps:YES];
    if (!self.deinstallation) {
        int arm = 0;
        size_t size = sizeof(arm);
        sysctlbyname("hw.optional.arm64", &arm, &size, NULL, 0);
        NSDictionary *minimums = [bundle objectForInfoDictionaryKey:@"ZOOMsoftMindestversionen"];
        NSString *minimum = minimums[arm ? @"arm64" : @"x86_64"];
        NSArray *parts = [minimum componentsSeparatedByString:@"."];
        NSOperatingSystemVersion required = {0, 0, 0};
        if (parts.count > 0) required.majorVersion = [parts[0] integerValue];
        if (parts.count > 1) required.minorVersion = [parts[1] integerValue];
        if (parts.count > 2) required.patchVersion = [parts[2] integerValue];
        if (!minimum || ![[NSProcessInfo processInfo] isOperatingSystemAtLeastVersion:required]) {
            NSString *text = [NSString stringWithFormat:@"Für Fernwartung | ZOOMsoft GmbH wird auf diesem Mac mindestens macOS %@ benötigt.", minimum ?: @"in einer neueren Version"];
            NSAlert *hinweis = [self meldung:Produktname details:text];
            [hinweis addButtonWithTitle:@"Schließen"];
            [hinweis runModal];
            [NSApp terminate:nil];
            return;
        }
    }
    NSString *vorgang = self.deinstallation ? @"Deinstallieren" : @"Installieren";
    NSString *frage = [NSString stringWithFormat:
        @"Für alle Benutzer dieses Macs %@?\n\nDafür sind Administratorrechte erforderlich.",
        self.deinstallation ? @"deinstallieren" : @"installieren"];
    NSAlert *confirm = [self meldung:Produktname details:frage];
    [confirm addButtonWithTitle:vorgang];
    [confirm addButtonWithTitle:@"Abbrechen"];
    if ([confirm runModal] != NSAlertFirstButtonReturn) {
        [NSApp terminate:nil];
        return;
    }
    self.beschaeftigt = YES;
    self.fortschritt = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 500, 190)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    self.fortschritt.title = Produktname;
    [self.fortschritt center];
    NSImageView *bild = [[NSImageView alloc] initWithFrame:NSMakeRect(24, 44, 96, 96)];
    bild.image = [[NSImage alloc] initWithContentsOfFile:[bundle pathForResource:@"AppIcon" ofType:@"icns"]];
    bild.imageScaling = NSImageScaleProportionallyUpOrDown;
    [self.fortschritt.contentView addSubview:bild];
    NSTextField *titel = [NSTextField labelWithString:self.deinstallation
        ? @"Deinstallation läuft …" : @"Installation läuft …"];
    titel.font = [NSFont boldSystemFontOfSize:18];
    titel.frame = NSMakeRect(142, 113, 336, 30);
    [self.fortschritt.contentView addSubview:titel];
    NSTextField *hinweis = [NSTextField wrappingLabelWithString:@"Für alle Benutzer dieses Macs.\nBitte bestätigen Sie die Administratorabfrage."];
    hinweis.frame = NSMakeRect(142, 55, 330, 52);
    [self.fortschritt.contentView addSubview:hinweis];
    NSProgressIndicator *spinner = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(145, 25, 22, 22)];
    spinner.style = NSProgressIndicatorStyleSpinning;
    [self.fortschritt.contentView addSubview:spinner];
    [spinner startAnimation:nil];
    [self.fortschritt makeKeyAndOrderFront:nil];

    // OSA einmal im Hauptthread initialisieren, bevor die Arbeit im Hintergrund beginnt.
    NSDictionary *startfehler = nil;
    [[[NSAppleScript alloc] initWithSource:@"return true"] executeAndReturnError:&startfehler];
    NSString *paket = [bundle pathForResource:@"Vorgang" ofType:@"pkg"];
    if (!paket) {
        [self fertigMitFehler:@{ NSAppleScriptErrorNumber: @1 }];
        return;
    }
    NSString *protokoll = self.deinstallation
        ? @"/var/log/zoomsoft-fernwartung-deinstallation.log"
        : @"/var/log/zoomsoft-fernwartung-installation.log";
    // Jede Ausführung erhält eine neue Befehlskennung. Dadurch wird nicht die
    // fünfminütige AppleScript-Freigabe desselben Befehls wiederverwendet.
    NSString *kennung = [[NSUUID UUID] UUIDString];
    NSString *kommando = [NSString stringWithFormat:
        @": %@; umask 077; /usr/sbin/installer -pkg %@ -target / > %@ 2>&1",
        ShellString(kennung), ShellString(paket), ShellString(protokoll)];
    NSString *script = [NSString stringWithFormat:@"do shell script %@ with administrator privileges",
        AppleScriptString(kommando)];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            NSDictionary *fehler = nil;
            NSAppleScript *ausfuehrung = [[NSAppleScript alloc] initWithSource:script];
            NSAppleEventDescriptor *resultat = [ausfuehrung executeAndReturnError:&fehler];
            if (!resultat && !fehler) fehler = @{ NSAppleScriptErrorNumber: @1 };
            dispatch_async(dispatch_get_main_queue(), ^{ [self fertigMitFehler:fehler]; });
        }
    });
}

- (void)fertigMitFehler:(NSDictionary *)fehler {
    self.beschaeftigt = NO;
    [self.fortschritt close];
    [NSApp activateIgnoringOtherApps:YES];
    BOOL abgebrochen = [fehler[NSAppleScriptErrorNumber] integerValue] == -128;
    NSString *titel;
    NSString *text;
    if (fehler) {
        titel = abgebrochen ? @"Vorgang abgebrochen"
            : (self.deinstallation ? @"Deinstallation fehlgeschlagen" : @"Installation fehlgeschlagen");
        text = abgebrochen
            ? @"Fernwartung | ZOOMsoft GmbH: Die Administratorabfrage wurde abgebrochen."
            : @"Fernwartung | ZOOMsoft GmbH: Der Vorgang konnte nicht vollständig abgeschlossen werden. Bitte wenden Sie sich an den Support von ZOOMsoft GmbH.";
    } else {
        titel = self.deinstallation ? @"Deinstallation abgeschlossen" : @"Installation abgeschlossen";
        text = [NSString stringWithFormat:@"%@\nFür alle Benutzer dieses Macs %@.",
            Produktname, self.deinstallation ? @"deinstalliert" : @"installiert"];
    }
    NSAlert *fertig = [self meldung:titel details:text];
    [fertig.window setTitle:Produktname];
    [fertig addButtonWithTitle:@"Schließen"];
    [fertig runModal];
    [NSApp terminate:nil];
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    return self.beschaeftigt ? NSTerminateCancel : NSTerminateNow;
}
@end

int main(int argc, const char *argv[]) {
    (void)argc;
    (void)argv;
    @autoreleasepool {
        [[NSUserDefaults standardUserDefaults] setObject:@[@"de"] forKey:@"AppleLanguages"];
        [[NSUserDefaults standardUserDefaults] setObject:@"de_DE" forKey:@"AppleLocale"];
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        __attribute__((objc_precise_lifetime)) FernwartungDialog *delegate = [[FernwartungDialog alloc] init];
        app.delegate = delegate;
        [app run];
    }
    return 0;
}
