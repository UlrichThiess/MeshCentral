// Copyright 2026 ZOOMsoft GmbH. Licensed under Apache-2.0.
#import <Cocoa/Cocoa.h>

static void text(NSString *value, NSRect rect, CGFloat size, BOOL bold, NSColor *color) {
    NSMutableParagraphStyle *style = [[NSMutableParagraphStyle alloc] init];
    style.alignment = NSTextAlignmentCenter;
    [value drawInRect:rect withAttributes:@{
        NSFontAttributeName: bold ? [NSFont boldSystemFontOfSize:size] : [NSFont systemFontOfSize:size],
        NSForegroundColorAttributeName: color, NSParagraphStyleAttributeName: style
    }];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) { return 64; }
        NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL
            pixelsWide:720 pixelsHigh:440 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES
            isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
        if (!bitmap) { return 1; }
        [NSGraphicsContext saveGraphicsState];
        [NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:bitmap]];
        [[NSColor colorWithCalibratedWhite:0.97 alpha:1] setFill];
        NSRectFill(NSMakeRect(0, 0, 720, 440));
        NSColor *ink = [NSColor colorWithCalibratedWhite:0.18 alpha:1];
        NSColor *subtle = [NSColor colorWithCalibratedWhite:0.38 alpha:1];
        NSImage *logo = [[NSImage alloc] initWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]];
        [logo drawInRect:NSMakeRect(24, 348, 64, 64) fromRect:NSZeroRect
            operation:NSCompositingOperationSourceOver fraction:1];
        text(@"Ferwartung | ZOOMsoft GmbH", NSMakeRect(92, 370, 600, 40), 25, YES, ink);
        text(@"Ziehen Sie die App in „Programme“.", NSMakeRect(80, 320, 560, 32), 20, NO, ink);
        [[NSColor colorWithCalibratedRed:0.16 green:0.40 blue:0.70 alpha:1] setStroke];
        NSBezierPath *arrow = [NSBezierPath bezierPath];
        arrow.lineWidth = 5;
        arrow.lineCapStyle = NSLineCapStyleRound;
        [arrow moveToPoint:NSMakePoint(314, 218)];
        [arrow lineToPoint:NSMakePoint(406, 218)];
        [arrow moveToPoint:NSMakePoint(388, 236)];
        [arrow lineToPoint:NSMakePoint(406, 218)];
        [arrow lineToPoint:NSMakePoint(388, 200)];
        [arrow stroke];
        text(@"Starten Sie die App anschließend aus „Programme“.",
            NSMakeRect(40, 64, 640, 32), 17, NO, ink);
        text(@"Fenster schließen beendet die Fernwartung.",
            NSMakeRect(40, 28, 640, 28), 14, NO, subtle);
        [NSGraphicsContext restoreGraphicsState];
        NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
        NSError *error = nil;
        if (!png || ![png writeToFile:[NSString stringWithUTF8String:argv[2]]
            options:NSDataWritingAtomic error:&error]) { return 1; }
    }
    return 0;
}
